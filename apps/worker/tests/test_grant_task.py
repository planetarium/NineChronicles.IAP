"""
(PLD-1564) 영수증 없는 지급 워커 — 멱등(이중 tx 금지)·재시도·확정 추적·nonce 통합.

DB 는 in-memory SQLite. 이 경로가 실제로 건드리는 테이블만 만든다.
⚠️ `receipt` 는 `Base.metadata` 로 만들 수 없다(`data` 컬럼이 PG 전용 JSONB). 그런데 nonce 통합
   규칙이 receipt 를 조회하므로, **nonce 조회에 필요한 컬럼만** 가진 동명 테이블을 raw DDL 로
   만든다(planet_id/nonce). 스키마 전체를 흉내낼 필요는 없다 — 검증 대상은 "두 테이블의 max 를
   함께 보는가" 이다.
"""
import datetime
from unittest.mock import MagicMock

import pytest
from shared.enums import (
    GrantStatus,
    PlanetID,
    ProductAssetUISize,
    ProductRarity,
    ProductType,
    TxStatus,
)
from shared.models.base import Base
from shared.models.grant_outbox import GrantOutbox
from shared.models.product import FungibleAssetProduct, FungibleItemProduct, Product
from shared.utils.grant import build_claim_data, promo_multiplier
from shared.utils.nonce import max_db_nonce, max_db_nonce_by_planet, pick_nonce
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.tasks import grant_task as gt

_TABLES = (
    "product",
    "fungible_asset_product",
    "fungible_item_product",
    "grant_outbox",
)

# nonce 통합 조회(shared.utils.nonce)가 보는 컬럼만. 실제 receipt 는 훨씬 넓다.
_RECEIPT_DDL = """
CREATE TABLE receipt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id BLOB,
    nonce INTEGER
)
"""

AVATAR = "0x" + "ab" * 20
AGENT = "0x" + "cd" * 20


class FakeAccount:
    """KMS 없이 서명 흐름만 통과시키는 대역(`shared.utils.grant.Signer` 인터페이스)."""

    address = "0x" + "11" * 20
    pubkey = b"\x02" * 33

    def __init__(self):
        self.signed = 0

    def sign_tx(self, unsigned_tx: bytes) -> bytes:
        self.signed += 1
        return b"\x30\x06\x02\x01\x01\x02\x01\x01"  # DER 모양의 더미


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng, tables=[Base.metadata.tables[t] for t in _TABLES])
    with eng.begin() as conn:
        conn.execute(text(_RECEIPT_DDL))
    return eng


@pytest.fixture
def sess(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def make_product(sess, *, with_item=True, with_fav=False) -> Product:
    product = Product(
        name="point-shop-item",
        order=1,
        google_sku="sku_point",
        apple_sku="sku_point",
        apple_sku_k="sku_point_k",
        product_type=ProductType.FREE,
        active=True,
        rarity=ProductRarity.NORMAL,
        size=ProductAssetUISize.ONE_BY_ONE,
        path="p.png",
        l10n_key="L10N_P",
        mileage=0,
        discount=0,
    )
    sess.add(product)
    sess.commit()
    if with_item:
        sess.add(
            FungibleItemProduct(
                product_id=product.id,
                sheet_item_id=300010,
                name="AP Potion",
                fungible_item_id="Item_NT_500000",
                amount=10,
            )
        )
    if with_fav:
        sess.add(
            FungibleAssetProduct(
                product_id=product.id,
                ticker="FAV__CRYSTAL",
                decimal_places=18,
                amount=100,
            )
        )
    sess.commit()
    sess.refresh(product)
    return product


def make_outbox(sess, product, *, external_ref="shop:order-1", **kwargs) -> GrantOutbox:
    kwargs.setdefault("status", GrantStatus.PENDING)
    row = GrantOutbox(
        external_ref=external_ref,
        product_id=product.id,
        planet_id=PlanetID.ODIN.value,
        avatar_addr=AVATAR,
        agent_addr=AGENT,
        memo='{"shop": {"order": "order-1"}}',
        **kwargs,
    )
    sess.add(row)
    sess.commit()
    sess.refresh(row)
    return row


def stage_ok(tx_id="0xtx-1"):
    calls = []

    def _stage(row):
        calls.append(row.tx)
        return True, "", tx_id

    _stage.calls = calls
    return _stage


def stage_fail(msg="node is down"):
    calls = []

    def _stage(row):
        calls.append(row.tx)
        return False, msg, None

    _stage.calls = calls
    return _stage


def nonce_fn(value=7):
    def _next(planet_id, address):
        return value

    return _next


class TestProcessGrant:
    def test_creates_signs_and_stages(self, sess):
        product = make_product(sess)
        row = make_outbox(sess, product)
        account = FakeAccount()
        stage = stage_ok()

        result = gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(7), stage_fn=stage
        )

        assert result.startswith("staged")
        assert row.nonce == 7
        assert row.tx is not None
        assert row.tx_id == "0xtx-1"
        assert row.tx_status == TxStatus.STAGED
        # 체인 확정 전에는 GRANTED 로 올리지 않는다.
        assert row.status == GrantStatus.PENDING
        assert account.signed == 1
        assert len(stage.calls) == 1

    def test_second_call_does_not_create_new_tx(self, sess):
        """멱등 — 이미 스테이징된 행은 재진입해도 tx 를 다시 만들지 않는다."""
        product = make_product(sess)
        row = make_outbox(sess, product)
        account = FakeAccount()
        stage = stage_ok()
        gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(), stage_fn=stage
        )
        first_tx = row.tx

        result = gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(), stage_fn=stage
        )

        assert result == "already staged"
        assert row.tx == first_tx
        assert account.signed == 1  # 재서명 없음
        assert len(stage.calls) == 1  # 재스테이징 없음

    def test_already_granted_short_circuits(self, sess):
        product = make_product(sess)
        row = make_outbox(sess, product, status=GrantStatus.GRANTED)
        stage = stage_ok()

        result = gt.process_grant(
            sess, row, account=FakeAccount(), next_nonce_fn=nonce_fn(), stage_fn=stage
        )

        assert result == "already granted"
        assert stage.calls == []

    def test_retry_increments_attempts_then_fails(self, sess):
        product = make_product(sess)
        row = make_outbox(sess, product)
        account = FakeAccount()
        stage = stage_fail()

        for expected in range(1, gt.MAX_ATTEMPTS):
            gt.process_grant(
                sess, row, account=account, next_nonce_fn=nonce_fn(), stage_fn=stage
            )
            assert row.attempts == expected
            assert row.status == GrantStatus.PENDING
            assert "stage failed" in row.last_error

        # MAX 번째 실패에서 종단(FAILED) — 포탈이 이걸 보고 환급한다.
        gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(), stage_fn=stage
        )
        assert row.attempts == gt.MAX_ATTEMPTS
        assert row.status == GrantStatus.FAILED
        # 서명은 처음 한 번뿐 — 재시도는 같은 tx 를 다시 넣기만 한다(같은 nonce·같은 tx id).
        assert account.signed == 1
        assert len(set(stage.calls)) == 1

    def test_product_without_components_fails_terminally(self, sess):
        product = make_product(sess, with_item=False)
        row = make_outbox(sess, product)
        stage = stage_ok()

        result = gt.process_grant(
            sess, row, account=FakeAccount(), next_nonce_fn=nonce_fn(), stage_fn=stage
        )

        assert "no grantable components" in result
        assert row.status == GrantStatus.FAILED
        assert row.tx is None
        assert stage.calls == []

    def test_missing_product_fails_terminally(self, sess):
        product = make_product(sess)
        row = make_outbox(sess, product)
        row.product_id = 999999
        sess.commit()

        result = gt.process_grant(
            sess,
            row,
            account=FakeAccount(),
            next_nonce_fn=nonce_fn(),
            stage_fn=stage_ok(),
        )

        assert "not found" in result
        assert row.status == GrantStatus.FAILED

    def test_node_error_is_retried_not_terminal(self, sess):
        """노드에서 nonce 를 못 얻으면 재시도 — 지급을 종단시키지 않는다."""
        product = make_product(sess)
        row = make_outbox(sess, product)

        def boom(planet_id, address):
            raise ValueError("Failed to get nonce from node")

        result = gt.process_grant(
            sess, row, account=FakeAccount(), next_nonce_fn=boom, stage_fn=stage_ok()
        )

        assert result.startswith("retry")
        assert row.status == GrantStatus.PENDING
        assert row.attempts == 1
        assert row.tx is None


class TestTrackGrant:
    def _staged_row(self, sess):
        product = make_product(sess)
        row = make_outbox(sess, product)
        gt.process_grant(
            sess,
            row,
            account=FakeAccount(),
            next_nonce_fn=nonce_fn(),
            stage_fn=stage_ok(),
        )
        return row

    def test_success_marks_granted(self, sess):
        row = self._staged_row(sess)
        before = datetime.datetime.now(datetime.timezone.utc)

        result = gt.track_grant(sess, row, status_fn=lambda r: (TxStatus.SUCCESS, "[]"))

        assert result == "granted"
        assert row.status == GrantStatus.GRANTED
        assert row.tx_status == TxStatus.SUCCESS
        assert row.granted_at is not None
        granted_at = row.granted_at
        if granted_at.tzinfo is None:  # sqlite 는 tz 를 버린다(PG 에서는 aware)
            granted_at = granted_at.replace(tzinfo=datetime.timezone.utc)
        assert granted_at >= before - datetime.timedelta(seconds=5)

    def test_chain_failure_is_terminal(self, sess):
        row = self._staged_row(sess)

        result = gt.track_grant(
            sess, row, status_fn=lambda r: (TxStatus.FAILURE, '["Some"]')
        )

        assert row.status == GrantStatus.FAILED
        assert "tx failed on chain" in result
        assert row.granted_at is None

    def test_invalid_is_retried(self, sess):
        row = self._staged_row(sess)

        gt.track_grant(sess, row, status_fn=lambda r: (TxStatus.INVALID, "[]"))

        assert row.status == GrantStatus.PENDING
        assert row.attempts == 1
        # 재스테이징 대상으로 다시 잡혀야 한다.
        assert row.id in [r.id for r in sess.scalars(gt.pending_dispatch_query()).all()]

    def test_unknown_status_changes_nothing(self, sess):
        row = self._staged_row(sess)

        result = gt.track_grant(sess, row, status_fn=lambda r: (None, "node down"))

        assert result == "unknown"
        assert row.status == GrantStatus.PENDING
        assert row.tx_status == TxStatus.STAGED
        assert row.attempts == 0


class TestPollingQueries:
    def test_dispatch_picks_untxed_and_skips_exhausted(self, sess):
        product = make_product(sess)
        fresh = make_outbox(sess, product, external_ref="shop:fresh")
        exhausted = make_outbox(
            sess, product, external_ref="shop:exhausted", attempts=gt.MAX_ATTEMPTS
        )
        staged = make_outbox(
            sess,
            product,
            external_ref="shop:staged",
            tx="deadbeef",
            tx_id="0xtx",
            tx_status=TxStatus.STAGED,
        )
        granted = make_outbox(
            sess, product, external_ref="shop:granted", status=GrantStatus.GRANTED
        )

        picked = [
            r.external_ref for r in sess.scalars(gt.pending_dispatch_query()).all()
        ]
        tracked = [r.external_ref for r in sess.scalars(gt.pending_track_query()).all()]

        assert picked == [fresh.external_ref]
        assert exhausted.external_ref not in picked
        assert granted.external_ref not in picked
        assert tracked == [staged.external_ref]


class TestNonceSharing:
    """
    nonce 는 receipt·grant_outbox **양쪽**의 max 를 봐야 한다. 한쪽만 보면 같은 지갑이 같은
    nonce 를 두 번 발급해 둘 중 하나가 영구히 스테이징 실패한다.
    """

    def test_max_db_nonce_spans_both_tables(self, sess):
        product = make_product(sess)
        make_outbox(sess, product, external_ref="shop:a", nonce=40)
        sess.execute(
            text("INSERT INTO receipt (planet_id, nonce) VALUES (:p, 41)"),
            {"p": PlanetID.ODIN.value},
        )
        sess.commit()

        assert max_db_nonce(sess, PlanetID.ODIN.value) == 41
        assert max_db_nonce_by_planet(sess)[PlanetID.ODIN.value] == 41
        # 다른 행성은 섞이지 않는다.
        assert max_db_nonce(sess, PlanetID.HEIMDALL.value) is None

    def test_pick_nonce_prefers_db_when_ahead(self):
        assert pick_nonce(10, 41) == 42  # 스테이징 대기분이 있으면 노드보다 DB 가 앞선다
        assert pick_nonce(50, 41) == 50  # 체인이 앞서면 노드 값
        assert pick_nonce(3, None) == 3  # DB 에 아무것도 없으면 노드 값 그대로

    def test_assign_nonce_uses_db_max(self, sess):
        product = make_product(sess)
        make_outbox(sess, product, external_ref="shop:old", nonce=100)
        row = make_outbox(sess, product, external_ref="shop:new")

        nonce = gt.assign_nonce(sess, row, FakeAccount(), next_nonce_fn=nonce_fn(5))

        assert nonce == 101
        assert row.nonce == 101


class TestSharedGrantBuilder:
    """구성품→티커 변환을 send_product 와 공유한다(복제 회귀 방지)."""

    def test_build_claim_data_covers_items_and_favs(self, sess):
        product = make_product(sess, with_item=True, with_fav=True)

        claim_data = build_claim_data(product)

        tickers = {fav.currency.ticker: fav.amount for fav in claim_data}
        assert tickers == {"Item_NT_500000": 10, "FAV__CRYSTAL": 100}

    def test_multiplier_applies(self, sess):
        product = make_product(sess, with_item=True, with_fav=True)

        claim_data = build_claim_data(product, multiplier=2)

        assert {fav.amount for fav in claim_data} == {20, 200}

    def test_promo_multiplier_is_thor_only(self):
        assert promo_multiplier(PlanetID.ODIN) == 1
        assert promo_multiplier(PlanetID.HEIMDALL) == 1
        assert promo_multiplier(PlanetID.THOR) == 2
        assert promo_multiplier(PlanetID.THOR_INTERNAL) == 2

    def test_grant_path_does_not_double_on_thor(self, sess):
        """무상 지급은 결제 프로모션(THOR 2배)을 타지 않는다 — 수량 권위는 포탈."""
        assert gt.GRANT_MULTIPLIER == 1


class TestSendGrantTask:
    def test_missing_row_is_not_retried(self, sess, monkeypatch):
        """행이 없는 메시지는 재시도해도 없다 — 조용히 끝낸다."""
        monkeypatch.setattr(
            gt,
            "scoped_session",
            lambda factory: MagicMock(
                **{
                    "scalar.return_value": None,
                    "remove.return_value": None,
                }
            ),
        )
        result = gt.send_grant.run({"external_ref": "shop:ghost"})
        assert result == "not found"
