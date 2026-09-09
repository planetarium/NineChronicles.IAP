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
from shared.utils.nonce import max_db_nonce, pick_nonce
from sqlalchemy import create_engine, select, text
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

    def test_stage_failure_retries_without_terminating(self, sess):
        """
        nonce 를 잡은 뒤의 실패는 **종단시키지 않는다**. 종단시키면 (1) 채번한 nonce 가 결번으로
        남아 지급 지갑 전체가 멈추고, (2) 스테이징 응답만 유실된 경우 "환급했는데 지급됨" 이 된다.
        """
        product = make_product(sess)
        row = make_outbox(sess, product)
        account = FakeAccount()
        stage = stage_fail()

        for expected in range(1, gt.MAX_ATTEMPTS + 3):
            gt.process_grant(
                sess, row, account=account, next_nonce_fn=nonce_fn(), stage_fn=stage
            )
            assert row.attempts == expected
            assert row.status == GrantStatus.PENDING  # MAX 를 넘겨도 PENDING
            assert "stage failed" in row.last_error

        # 서명은 처음 한 번뿐 — 재시도는 같은 tx 를 다시 넣기만 한다(같은 nonce·같은 tx id).
        assert account.signed == 1
        assert len(set(stage.calls)) == 1
        # nonce 를 물고 있는 행은 MAX 를 넘겨도 계속 재시도 대상이어야 한다(결번 방지).
        assert row.id in [r.id for r in sess.scalars(gt.pending_dispatch_query()).all()]
        # 침전은 알림으로 사람에게 도달한다.
        assert gt.stalled_count(sess) == 1

    def test_pre_nonce_failure_terminates_after_max_attempts(self, sess):
        """nonce 를 잡기 전 실패(노드 nonce 조회 불가)는 MAX 소진 시 종단 — 결번이 없으므로 안전."""
        product = make_product(sess)
        row = make_outbox(sess, product)

        def boom(planet_id, address):
            raise ValueError("node down")

        for _ in range(gt.MAX_ATTEMPTS):
            gt.process_grant(
                sess,
                row,
                account=FakeAccount(),
                next_nonce_fn=boom,
                stage_fn=stage_ok(),
            )

        assert row.attempts == gt.MAX_ATTEMPTS
        assert row.status == GrantStatus.FAILED
        assert row.nonce is None
        assert row.tx is None

    def test_terminal_failed_row_is_not_redriven(self, sess):
        """종단 FAILED 는 재구동하지 않는다 — 포탈이 이미 환급했을 수 있다."""
        product = make_product(sess)
        row = make_outbox(sess, product, status=GrantStatus.FAILED)
        stage = stage_ok()

        result = gt.process_grant(
            sess, row, account=FakeAccount(), next_nonce_fn=nonce_fn(), stage_fn=stage
        )

        assert result == "already failed"
        assert stage.calls == []
        assert row.tx is None

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
        assert row.nonce is None


class TestConcurrentDispatch:
    """
    같은 행을 두 워커가 동시에 집어도 **온체인 tx 는 1건**이어야 한다.
    (`iap.send_grant` 는 background 큐, beat 는 별 프로세스 — 실제로 겹칠 수 있다.)
    """

    def test_second_worker_discards_its_tx(self, sess, engine):
        product = make_product(sess)
        row = make_outbox(sess, product)
        other_sess = Session(engine)
        try:
            other_row = other_sess.scalar(
                select(GrantOutbox).where(GrantOutbox.id == row.id)
            )
            stage_a, stage_b = stage_ok("0xtx-A"), stage_ok("0xtx-B")

            # A 가 먼저 서명·스테이징까지 끝낸다.
            gt.process_grant(
                sess,
                row,
                account=FakeAccount(),
                next_nonce_fn=nonce_fn(7),
                stage_fn=stage_a,
            )
            # B 는 A 커밋 전 스냅샷(tx None)을 들고 뒤늦게 진입한다.
            result_b = gt.process_grant(
                other_sess,
                other_row,
                account=FakeAccount(),
                next_nonce_fn=nonce_fn(7),
                stage_fn=stage_b,
            )

            assert result_b in ("nonce claimed by another worker", "already staged")
            assert stage_b.calls == []  # B 의 tx 는 체인에 나가지 않는다
            other_sess.refresh(other_row)
            assert other_row.tx_id == "0xtx-A"
        finally:
            other_sess.close()

    def test_tx_claim_loser_does_not_stage(self, sess, engine):
        """nonce 는 이미 잡힌 상태에서 tx 서명만 겹친 경우 — 먼저 쓴 tx 만 스테이징된다."""
        product = make_product(sess)
        row = make_outbox(sess, product, nonce=7)
        with Session(engine) as other:
            other.execute(
                text(
                    "UPDATE grant_outbox SET tx = 'aabb', tx_status = 'CREATED'"
                    " WHERE id = :id"
                ),
                {"id": row.id},
            )
            other.commit()
        account = FakeAccount()
        stage = stage_ok()

        result = gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(7), stage_fn=stage
        )

        assert result == "tx claimed by another worker"
        assert account.signed == 1  # 서명은 했지만
        assert stage.calls == []  # 체인에는 안 나간다
        assert row.tx == "aabb"  # 먼저 쓴 tx 가 남는다


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

    def test_invalid_restage_reuses_same_tx(self, sess):
        """멤풀 탈락 후 재스테이징은 **같은 tx**여야 한다(새 서명·새 nonce 금지)."""
        row = self._staged_row(sess)
        tx_before, nonce_before = row.tx, row.nonce
        gt.track_grant(sess, row, status_fn=lambda r: (TxStatus.INVALID, "[]"))
        account = FakeAccount()
        stage = stage_ok(tx_id="0xtx-2")

        gt.process_grant(
            sess, row, account=account, next_nonce_fn=nonce_fn(999), stage_fn=stage
        )

        assert row.tx == tx_before
        assert row.nonce == nonce_before
        assert account.signed == 0  # 재서명하지 않는다
        assert stage.calls == [tx_before]

    def test_headless_staging_maps_to_staged(self, sess):
        """헤드리스의 STAGING 은 우리 STAGED 로 매핑 — 정상 대기가 경고로 새지 않게."""
        row = self._staged_row(sess)

        def fake_status(r):
            # fetch_tx_status 의 매핑 규칙만 확인(네트워크는 타지 않는다)
            raw = "STAGING"
            assert raw in gt._PENDING_CHAIN_STATUSES
            return TxStatus.STAGED, "[]"

        result = gt.track_grant(sess, row, status_fn=fake_status)

        assert result == "STAGED"
        assert row.status == GrantStatus.PENDING
        assert row.attempts == 0

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
        # 다른 행성은 섞이지 않는다.
        assert max_db_nonce(sess, PlanetID.HEIMDALL.value) is None

    def test_pick_nonce_prefers_db_when_ahead(self):
        assert pick_nonce(10, 41) == 42  # 스테이징 대기분이 있으면 노드보다 DB 가 앞선다
        assert pick_nonce(50, 41) == 50  # 체인이 앞서면 노드 값
        assert pick_nonce(3, None) == 3  # DB 에 아무것도 없으면 노드 값 그대로

    def test_claim_nonce_uses_db_max(self, sess):
        product = make_product(sess)
        make_outbox(sess, product, external_ref="shop:old", nonce=100)
        row = make_outbox(sess, product, external_ref="shop:new")

        assert gt.claim_nonce(sess, row, FakeAccount(), next_nonce_fn=nonce_fn(5))

        assert row.nonce == 101

    def test_claim_nonce_loses_to_concurrent_claim(self, sess, engine):
        """다른 워커가 먼저 채번했으면 선점 실패 → 호출자는 물러난다(중복 tx 방지)."""
        product = make_product(sess)
        row = make_outbox(sess, product)

        def steal(planet_id, address):
            # 노드 조회 시점에 다른 세션이 먼저 nonce 를 박는다.
            with Session(engine) as other:
                other.execute(
                    text("UPDATE grant_outbox SET nonce = 55 WHERE id = :id"),
                    {"id": row.id},
                )
                other.commit()
            return 7

        assert gt.claim_nonce(sess, row, FakeAccount(), next_nonce_fn=steal) is False
        assert row.nonce == 55  # 남의 값을 그대로 둔다


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
