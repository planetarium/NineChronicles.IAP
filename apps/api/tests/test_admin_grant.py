"""
(PLD-1564) 영수증 없는 범용 지급 API — 계약(필드명·상태값·HTTP 코드)과 멱등 불변식.

**실 앱(`main.app`)을 그대로 띄운다.** 라우터 스텁이 아니라 진짜 앱이어야 검증되는 것들이 있다:
  · 실제 경로가 `/api/admin/grant` 라는 사실(라우터 prefix 중첩 — 계약 문서의 `/admin/grant` 와
    다르므로 여기서 못박아 둔다)
  · 검증 실패가 **400** 이라는 것(FastAPI 기본값은 422 인데 main.py 가 핸들러로 400 으로 바꾼다)
  · 라우터 레벨 인증이 붙어 있다는 것

`app.config.Settings` 는 필수 env 가 많아 임포트 시점에 죽는다 → 더미 env 를 먼저 심는다.
(개발자 `.env` 에 의존하지 않게 `setdefault` 가 아니라 없을 때만 넣는 것으로 충분하다 —
 테스트는 `cd apps/api && .venv/bin/python -m pytest tests/` 로 도는데 그 cwd 에 .env 가 없으면
 이 값들이 쓰인다.)

DB 는 in-memory SQLite. 이 경로가 실제로 건드리는 테이블만 만든다(`receipt` 는 PG 전용 JSONB 라
만들 수 없고, 이 경로는 receipt 를 보지 않는다 — 그게 이 설계의 요점이다).
"""
import os

for _key, _value in {
    "API_BACKOFFICE_JWT_SECRET": "test-secret",
    "API_SEASON_PASS_HOST": "http://localhost",
    "API_SEASON_PASS_JWT_SECRET": "x",
    "API_GOOGLE_CREDENTIAL": "x",
    "API_APPLE_CREDENTIAL": "x",
    "API_APPLE_BUNDLE_ID": "x",
    "API_APPLE_KEY_ID": "x",
    "API_APPLE_ISSUER_ID": "x",
    "API_APPLE_VALIDATION_URL": "http://localhost",
    "API_STRIPE_SECRET_KEY": "x",
    "API_STRIPE_TEST_SECRET_KEY": "x",
    "API_CLOUDFLARE_API_KEY": "x",
    "API_CLOUDFLARE_ASSETS_K_ZONE_ID": "x",
    "API_CLOUDFLARE_ASSETS_ZONE_ID": "x",
    "API_CLOUDFLARE_EMAIL": "x@example.com",
    "API_R2_ACCESS_KEY_ID": "x",
    "API_R2_ACCOUNT_ID": "x",
    "API_R2_BUCKET": "x",
    "API_R2_SECRET_ACCESS_KEY": "x",
    "API_S3_BUCKET": "x",
    "API_CLOUDFRONT_DISTRIBUTION_1": "x",
    "API_CLOUDFRONT_DISTRIBUTION_2": "x",
    "API_REDEEM_API_BASE_URL": "http://localhost",
}.items():
    os.environ.setdefault(_key, _value)

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from shared.enums import (  # noqa: E402
    GrantStatus,
    PlanetID,
    ProductAssetUISize,
    ProductRarity,
    ProductType,
    TxStatus,
)
from shared.models.base import Base  # noqa: E402
from shared.models.grant_outbox import GrantOutbox  # noqa: E402
from shared.models.product import (  # noqa: E402
    FungibleAssetProduct,
    FungibleItemProduct,
    Product,
)
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import main  # noqa: E402  — 실 FastAPI 앱(에러 핸들러·라우터 등록 포함)
from app import grant_guard  # noqa: E402
from app.api import admin  # noqa: E402
from app.dependencies import session as session_dep  # noqa: E402
from app.utils import verify_token  # noqa: E402

GRANT_URL = "/api/admin/grant"
GRANTS_URL = "/api/admin/grants"
AVATAR = "0x" + "ab" * 20
AGENT = "0x" + "cd" * 20
ODIN = PlanetID.ODIN.value.decode()

_TABLES = (
    "product",
    "fungible_asset_product",
    "fungible_item_product",
    "grant_outbox",
    # (PLD-1562) Product.gacha_entry_list 가 joinedload 대상이라, 없으면 상품 조회가
    #   통째로 "no such table" 로 죽는다(뽑기를 안 쓰는 테스트도 같이).
    "product_gacha_entry",
)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng, tables=[Base.metadata.tables[t] for t in _TABLES])
    return eng


@pytest.fixture
def sess(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def worker(monkeypatch):
    """큐 발행 대역. `send_to_worker` 호출 횟수 = 워커에 넘긴 지급 요청 수."""
    mock = MagicMock(return_value="task-id")
    monkeypatch.setattr(admin, "send_to_worker", mock)
    return mock


@pytest.fixture
def alert(monkeypatch):
    """
    (PLD-1575) 가드 위반 Slack 알림 대역. 호출 횟수 = 채널에 뜬 알림 수.

    프로세스 전역 스로틀 상태를 테스트마다 비운다 — 안 그러면 앞 테스트의 알림 때문에
    뒤 테스트가 조용해진다(사유 키가 겹칠 때). 위반용/경고용 저장소가 분리돼 있어 둘 다 비운다.
    """
    grant_guard._alert_sent_at.clear()
    grant_guard._warn_sent_at.clear()
    mock = MagicMock(return_value=True)
    monkeypatch.setattr(admin, "send_slack_alert", mock)
    return mock


@pytest.fixture
def limits(monkeypatch):
    """
    가드 임계값 주입 헬퍼. `limits(max_grants_per_hour=2, ...)` 로 설정만 바꾼다.

    가드는 요청마다 `config` 를 읽으므로(`limits_from_settings`) 설정 객체를 monkeypatch 하면
    된다 — 재시작이나 앱 재조립이 필요 없다. monkeypatch 가 테스트 끝에 원복한다.
    """

    def _set(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(admin.config, key, value)

    return _set


@pytest.fixture
def client(sess, worker, alert):
    main.app.dependency_overrides[session_dep] = lambda: sess
    main.app.dependency_overrides[verify_token] = lambda: None
    with TestClient(main.app) as test_client:
        test_client.headers.update({"Authorization": "Bearer test"})
        yield test_client
    main.app.dependency_overrides.clear()


def make_product(
    sess,
    *,
    with_item=True,
    name="point-shop-item",
    grantable=True,
    product_type=ProductType.FREE,
    google_sku=None,
    item_amount=10,
    fav_amount=None,
) -> Product:
    """
    지급 대상 상품 1건. 기본값은 **가드를 통과하는** 포인트샵 상품
    (`point_shop_grantable=True` · 비현금 유형) — PLD-1575 이후 이게 정상 요청의 전제다.
    """
    product = Product(
        name=name,
        order=1,
        google_sku=google_sku if google_sku is not None else f"sku_{name}",
        apple_sku=f"sku_{name}",
        apple_sku_k=f"sku_{name}_k",
        product_type=product_type,
        active=True,
        rarity=ProductRarity.NORMAL,
        size=ProductAssetUISize.ONE_BY_ONE,
        path="p.png",
        l10n_key="L10N_P",
        mileage=0,
        discount=0,
        point_shop_grantable=grantable,
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
                amount=item_amount,
            )
        )
        sess.commit()
    if fav_amount is not None:
        sess.add(
            FungibleAssetProduct(
                product_id=product.id,
                ticker="FAV__CRYSTAL",
                decimal_places=18,
                amount=fav_amount,
            )
        )
        sess.commit()
    sess.refresh(product)
    return product


def payload(product, *, external_ref="shop:order-1", **overrides) -> dict:
    body = {
        "externalRef": external_ref,
        "planetId": ODIN,
        "productId": product.id,
        "avatarAddress": AVATAR,
    }
    body.update(overrides)
    return body


class TestCreateGrant:
    def test_new_request_returns_201_with_contract_fields(self, client, sess, worker):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 201
        body = resp.json()
        # 계약 필드명(camelCase)과 상태값 어휘를 그대로 못박는다 — 포탈 클라이언트가 이걸 읽는다.
        assert set(body) == {
            "externalRef",
            "status",
            "txId",
            "txStatus",
            "attempts",
            "lastError",
            "createdAt",
            "grantedAt",
            # (PLD-1562) 뽑기 결과. 고정 상품은 None 이고, 이 필드가 늘어난 것은
            #   **추가**라 기존 포탈 클라이언트와 하위호환이다.
            "drawResult",
        }
        assert body["externalRef"] == "shop:order-1"
        assert body["status"] == "PENDING"
        assert body["txId"] is None
        assert body["txStatus"] is None
        assert body["attempts"] == 0
        assert body["lastError"] is None
        assert body["grantedAt"] is None
        assert body["createdAt"] is not None
        assert body["drawResult"] is None, "고정 상품에는 추첨 결과가 없다"
        assert worker.call_count == 1
        assert worker.call_args[0][0] == "iap.send_grant"
        assert worker.call_args[0][1] == {"external_ref": "shop:order-1"}

    def test_five_identical_posts_create_one_row_and_one_task(
        self, client, sess, worker
    ):
        """불변식: 같은 externalRef N회 → 아웃박스 1행 · 워커 발행 1건(= 온체인 tx 1건)."""
        product = make_product(sess)

        statuses = [
            client.post(GRANT_URL, json=payload(product)).status_code for _ in range(5)
        ]

        assert statuses == [201, 200, 200, 200, 200]
        rows = sess.scalars(select(GrantOutbox)).all()
        assert len(rows) == 1
        assert worker.call_count == 1  # 재요청은 큐에 다시 넣지 않는다(이중 tx 금지)

    def test_repeat_returns_live_state_not_request_echo(self, client, sess):
        """재요청 응답은 요청 본문이 아니라 **현재 행 상태**다(이미 tx 가 나갔을 수 있다)."""
        product = make_product(sess)
        client.post(GRANT_URL, json=payload(product))
        row = sess.scalar(select(GrantOutbox))
        row.tx_id = "0xdeadbeef"
        row.tx_status = TxStatus.STAGED
        row.attempts = 2
        row.last_error = "stage failed: node is down"
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 200
        body = resp.json()
        assert body["txId"] == "0xdeadbeef"
        assert body["txStatus"] == "STAGED"
        assert body["attempts"] == 2
        assert body["lastError"] == "stage failed: node is down"

    def test_memo_is_generated_from_external_ref(self, client, sess):
        product = make_product(sess)

        client.post(GRANT_URL, json=payload(product, external_ref="shop:abc-123"))

        row = sess.scalar(select(GrantOutbox))
        assert json.loads(row.memo) == {"shop": {"order": "abc-123"}}

    def test_supplied_memo_keeps_order_marker(self, client, sess):
        """호출자 memo 를 존중하되 주문 표식은 보장한다 — 체인 역추적 불변식."""
        product = make_product(sess)

        client.post(
            GRANT_URL,
            json=payload(product, memo={"note": "vip", "shop": {"campaign": "x"}}),
        )

        row = sess.scalar(select(GrantOutbox))
        memo = json.loads(row.memo)
        assert memo["note"] == "vip"
        assert memo["shop"]["order"] == "order-1"
        assert memo["shop"]["campaign"] == "x"

    def test_supplied_memo_cannot_override_order_marker(self, client, sess):
        """호출자가 다른 order 를 넣어도 externalRef 의 주문키가 이긴다(역추적 불변식)."""
        product = make_product(sess)

        client.post(
            GRANT_URL,
            json=payload(product, memo={"shop": {"order": "someone-elses-order"}}),
        )

        row = sess.scalar(select(GrantOutbox))
        assert json.loads(row.memo)["shop"]["order"] == "order-1"

    def test_concurrent_insert_falls_back_to_200(
        self, client, sess, monkeypatch, worker
    ):
        """
        UNIQUE(external_ref) 경합 — 같은 ref 가 동시에 들어와 commit 이 터지는 분기.

        "기존 행 조회"가 None 을 돌려주도록 한 번만 속여, 실제 UNIQUE 위반을 만든다.
        """
        product = make_product(sess)
        client.post(GRANT_URL, json=payload(product))
        real_scalar = sess.scalar
        calls = {"n": 0}

        def blind_first_lookup(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:  # 멱등 조회만 속인다(그 다음 상품 조회는 정상)
                return None
            return real_scalar(*args, **kwargs)

        monkeypatch.setattr(sess, "scalar", blind_first_lookup)

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 200
        assert resp.json()["externalRef"] == "shop:order-1"
        monkeypatch.undo()
        assert len(sess.scalars(select(GrantOutbox)).all()) == 1
        assert worker.call_count == 1  # 경합 패자는 큐에 다시 넣지 않는다

    def test_grant_is_not_queued_behind_paid_purchases(self, client, sess, worker):
        """무상 지급은 결제 지급 큐(product_queue)에 섞지 않는다."""
        product = make_product(sess)

        client.post(GRANT_URL, json=payload(product))

        assert worker.call_args.kwargs["queue"] == "background_job_queue"

    def test_addresses_are_normalized(self, client, sess):
        product = make_product(sess)

        client.post(
            GRANT_URL,
            json=payload(
                product,
                avatarAddress=AVATAR.upper().replace("0X", "0x"),
                agentAddress=AGENT,
            ),
        )

        row = sess.scalar(select(GrantOutbox))
        assert row.avatar_addr == AVATAR  # 소문자 0x 형식
        assert row.agent_addr == AGENT
        assert row.planet_id == PlanetID.ODIN.value
        assert row.status == GrantStatus.PENDING

    @pytest.mark.parametrize(
        "overrides",
        [
            {"avatarAddress": "0xnothex"},
            {"avatarAddress": "ab" * 20},  # 0x 없음
            {"avatarAddress": "0x" + "ab" * 19},  # 짧음
            {"externalRef": ""},
            {"externalRef": "shop:" + "x" * 130},  # 128자 초과
            {"externalRef": "shop:has space"},
            {"productId": 0},
        ],
    )
    def test_validation_errors_are_400(self, client, sess, overrides):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, **overrides))

        assert resp.status_code == 400

    def test_unknown_product_is_400(self, client, sess):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, productId=999999))

        assert resp.status_code == 400
        assert "not found" in json.dumps(resp.json())
        assert sess.scalars(select(GrantOutbox)).all() == []

    def test_product_without_components_is_400(self, client, sess):
        product = make_product(sess, with_item=False, name="empty")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "no grantable components" in json.dumps(resp.json())

    def test_unknown_planet_is_400(self, client, sess):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, planetId="0x0000000000ff"))

        assert resp.status_code == 400
        assert "planetId" in json.dumps(resp.json())

    def test_too_long_memo_is_400(self, client, sess):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, memo={"pad": "x" * 600}))

        assert resp.status_code == 400
        assert "memo too long" in json.dumps(resp.json())

    def test_queue_failure_still_returns_201(self, client, sess, worker):
        """큐 장애로 요청을 깨지 않는다 — 행은 커밋되고 beat 가 다시 집는다."""
        product = make_product(sess)
        worker.side_effect = RuntimeError("broker down")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 201
        assert len(sess.scalars(select(GrantOutbox)).all()) == 1


class TestGetGrant:
    def test_returns_current_state(self, client, sess):
        product = make_product(sess)
        client.post(GRANT_URL, json=payload(product))

        resp = client.get(f"{GRANT_URL}/shop:order-1")

        assert resp.status_code == 200
        assert resp.json()["externalRef"] == "shop:order-1"
        assert resp.json()["status"] == "PENDING"

    def test_unknown_ref_is_404(self, client, sess):
        resp = client.get(f"{GRANT_URL}/shop:nope")

        assert resp.status_code == 404


class TestListGrants:
    def _seed(self, client, sess, count=3):
        product = make_product(sess)
        for i in range(count):
            client.post(GRANT_URL, json=payload(product, external_ref=f"shop:o-{i}"))
        return product

    def test_status_filter(self, client, sess):
        self._seed(client, sess, 3)
        rows = sess.scalars(select(GrantOutbox)).all()
        rows[0].status = GrantStatus.FAILED
        rows[0].last_error = "stage failed"
        rows[1].status = GrantStatus.GRANTED
        sess.commit()

        pending = client.get(GRANTS_URL, params={"status": "PENDING"}).json()
        failed = client.get(GRANTS_URL, params={"status": "FAILED"}).json()

        assert [item["externalRef"] for item in pending["items"]] == ["shop:o-2"]
        assert [item["externalRef"] for item in failed["items"]] == ["shop:o-0"]
        assert failed["items"][0]["lastError"] == "stage failed"
        assert failed["nextCursor"] is None

    def test_cursor_pagination_walks_all_rows(self, client, sess):
        self._seed(client, sess, 3)

        first = client.get(GRANTS_URL, params={"limit": 2}).json()
        assert [i["externalRef"] for i in first["items"]] == ["shop:o-2", "shop:o-1"]
        assert first["nextCursor"] is not None

        second = client.get(
            GRANTS_URL, params={"limit": 2, "cursor": first["nextCursor"]}
        ).json()
        assert [i["externalRef"] for i in second["items"]] == ["shop:o-0"]
        assert second["nextCursor"] is None

    def test_bad_cursor_is_400(self, client, sess):
        assert client.get(GRANTS_URL, params={"cursor": "abc"}).status_code == 400

    def test_bad_status_is_400(self, client, sess):
        assert client.get(GRANTS_URL, params={"status": "NOPE"}).status_code == 400


class TestAuth:
    """라우터 레벨 인증이 실제로 붙어 있는지 — 오버라이드 없이 확인."""

    @pytest.fixture
    def unauthed_client(self, sess, worker):
        main.app.dependency_overrides[session_dep] = lambda: sess
        with TestClient(main.app) as test_client:
            yield test_client
        main.app.dependency_overrides.clear()

    def test_missing_header_is_rejected(self, unauthed_client, sess):
        resp = unauthed_client.get(f"{GRANT_URL}/shop:x")
        assert resp.status_code in (401, 403)

    def test_bogus_token_is_401(self, unauthed_client, sess):
        resp = unauthed_client.get(
            f"{GRANT_URL}/shop:x", headers={"Authorization": "Bearer bogus"}
        )
        assert resp.status_code == 401


# ── (PLD-1575) 머니 가드 ───────────────────────────────────────────────────────
#   지급 API 는 `GrantItems` force-grant(잔액 없이 발행)를 여는 엔드포인트다. 여기 테스트는
#   "무엇을·얼마나·누가"의 세 축이 실제로 닫혀 있는지, 그리고 **거절이 계약을 깨지 않는지**
#   (행 없음·FAILED 없음·멱등 재요청 불변)를 못박는다.

WHITELIST_URL = "/api/admin/point-shop-products"


def rows_of(sess):
    return sess.scalars(select(GrantOutbox)).all()


class TestProductWhitelist:
    def test_non_whitelisted_product_is_400_without_row(
        self, client, sess, worker, alert
    ):
        product = make_product(sess, grantable=False, name="not-listed")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "point_shop_grantable" in json.dumps(resp.json())
        assert rows_of(sess) == []  # 아웃박스에 아무 행도 안 남는다(FAILED 포함)
        assert worker.call_count == 0
        assert alert.call_count == 1

    def test_cash_product_is_400_even_if_flag_is_stale(self, client, sess, alert):
        """플래그가 켜진 채 현금 상품(IAP)으로 바뀐 경우 — 지급 시점 재검증이 잡는다."""
        product = make_product(
            sess, grantable=True, product_type=ProductType.IAP, name="cash"
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "현금 상품" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []
        assert alert.call_count == 1

    def test_season_pass_sku_is_400(self, client, sess):
        product = make_product(
            sess, grantable=True, google_sku="g_pkg_couragepass01", name="cp"
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "시즌패스" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []


CRYSTAL = "FAV__CRYSTAL"


class TestFavTickerAllowlist:
    """
    화폐(FAV) 는 티커 자체를 얼로우리스트로 막는다 — 수량 상한은 티커를 구분하지 못한다.

    `fungible-assets/import` 로 화이트리스트에 올라간 상품의 구성품을 CRYSTAL → NCG 로
    갈아치우면 수량 상한은 그대로 통과한다. 그 경로를 닫는 게 이 가드다.
    """

    def test_unset_allowlist_is_503_not_400(self, client, sess, alert):
        """
        허용목록이 **비어 있는데** FAV 상품이 오면 503 이다(400 아님).

        빈 목록은 "배선을 잊었다"와 구분되지 않는다. 400 을 주면 포탈이 그 주문을 영구 실패로
        확정해 포인트를 환급하는데, 상한 미주입(`limits_unset`)을 503 으로 만든 근거와 같은
        상황이다. 진짜로 FAV 를 안 주는 정책이면 그 상품을 화이트리스트에 켜지 않으면 된다.
        """
        product = make_product(sess, with_item=False, fav_amount=1, name="fav-default")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 503
        assert "fav_tickers_unset" in json.dumps(resp.json())
        assert rows_of(sess) == []
        assert alert.call_count == 1

    def test_ticker_outside_a_configured_allowlist_is_400(self, client, sess, limits):
        """목록이 있는데 이 상품 티커가 밖 = 상품 구성 오류(재시도해도 같다) → 400."""
        limits(grant_allowed_fav_tickers="FAV__NCG")
        product = make_product(sess, with_item=False, fav_amount=1, name="fav-other")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "fav_ticker_not_allowed" in json.dumps(resp.json())
        assert rows_of(sess) == []

    def test_allowed_ticker_passes(self, client, sess, limits):
        limits(grant_allowed_fav_tickers=CRYSTAL)
        product = make_product(sess, with_item=False, fav_amount=1, name="fav-allowed")

        assert client.post(GRANT_URL, json=payload(product)).status_code == 201

    def test_item_only_product_is_unaffected(self, client, sess):
        """기본값(빈 목록)이 아이템 지급을 막지 않는다 — 포인트샵의 정상 케이스."""
        product = make_product(sess, name="item-only")

        assert client.post(GRANT_URL, json=payload(product)).status_code == 201


class TestIssuanceCaps:
    def test_fav_units_over_cap_is_400(self, client, sess, limits, alert):
        limits(grant_max_fav_units_per_request=10, grant_allowed_fav_tickers=CRYSTAL)
        product = make_product(sess, with_item=False, fav_amount=100, name="fav-big")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "FAV 발행량" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []
        assert alert.call_count == 1

    def test_fav_units_at_cap_passes(self, client, sess, limits):
        limits(grant_max_fav_units_per_request=10, grant_allowed_fav_tickers=CRYSTAL)
        product = make_product(sess, with_item=False, fav_amount=10, name="fav-ok")

        assert client.post(GRANT_URL, json=payload(product)).status_code == 201

    def test_item_units_over_cap_is_400(self, client, sess, limits):
        limits(grant_max_item_units_per_request=5)
        product = make_product(sess, item_amount=6, name="item-big")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "아이템 발행량" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []

    def test_item_cap_does_not_leak_into_fav_cap(self, client, sess, limits):
        """FAV 와 아이템은 따로 센다 — 물약 상한이 NCG 발행 상한이 되면 가드가 무의미하다."""
        limits(
            grant_max_item_units_per_request=1000,
            grant_max_fav_units_per_request=1,
            grant_allowed_fav_tickers=CRYSTAL,
        )
        product = make_product(sess, item_amount=1000, fav_amount=2, name="mixed")

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "FAV 발행량" in json.dumps(resp.json(), ensure_ascii=False)

    def test_hourly_total_cap_stops_further_grants(self, client, sess, limits, alert):
        limits(grant_max_grants_per_hour=2)
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:o-{i}")
            ).status_code
            for i in range(3)
        ]

        assert statuses == [201, 201, 400]
        assert len(rows_of(sess)) == 2  # 초과분은 행을 만들지 않는다
        assert alert.call_count == 1
        assert "상한 초과" in json.dumps(alert.call_args[0][1], ensure_ascii=False)

    def test_daily_total_cap_stops_further_grants(self, client, sess, limits):
        limits(grant_max_grants_per_day=1)
        product = make_product(sess)

        first = client.post(GRANT_URL, json=payload(product, external_ref="shop:d-1"))
        second = client.post(GRANT_URL, json=payload(product, external_ref="shop:d-2"))

        assert (first.status_code, second.status_code) == (201, 400)
        assert len(rows_of(sess)) == 1

    def test_pressure_warning_fires_before_rejection(self, client, sess, limits, alert):
        """
        거절 **전에** 임박 경고가 나가야 한다 — 위반 알림만 있으면 첫 초과 주문이 이미
        영구 실패다. 운영자가 상한을 올릴 시간을 버는 게 이 경고의 목적.
        """
        limits(grant_max_grants_per_hour=5)
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:w-{i}")
            ).status_code
            for i in range(5)
        ]

        assert statuses == [201] * 5  # 아직 거절 없음
        assert len(rows_of(sess)) == 5
        assert alert.call_count == 1  # 80% 지점(5번째 요청, 이미 4건)에서 한 번
        text = alert.call_args[0][1]
        assert "per_hour_exceeded_warn" in text
        assert "임박" in text

    def test_idempotent_repeat_is_not_rate_limited(self, client, sess, limits, worker):
        """
        상한을 넘긴 뒤에도 **같은 externalRef 재요청은 200** 이어야 한다.

        계약: 재요청 = 200 + 현재 상태. 진행 중 주문이 뒤늦은 상한 변경으로 400 이 되면
        포탈 폴링이 깨지고, 이미 온체인에 나간 지급을 실패로 오판한다.
        """
        limits(grant_max_grants_per_hour=1)
        product = make_product(sess)
        assert client.post(GRANT_URL, json=payload(product)).status_code == 201

        repeat = client.post(GRANT_URL, json=payload(product))

        assert repeat.status_code == 200
        assert repeat.json()["status"] == "PENDING"
        assert len(rows_of(sess)) == 1
        assert worker.call_count == 1


OTHER_AVATAR = "0x" + "ef" * 20


class TestAvatarCaps:
    """
    (PLD-1575) **아바타 축** 시간창 상한 — 전역 상한은 총노출을, 이 축은 집중도를 묶는다.

    이 경로는 "유저가 포인트를 냈는지"를 IAP 가 검증하지 못한다(원장은 포탈에 있고 IAP 는
    잔액을 모른다). 즉 포탈을 신뢰하는 구조라, 포탈 버그 하나가 전역 시간창 전량을 **한
    아바타에** 쏟아넣을 수 있었다. 그 집중을 막는 게 이 축이다.
    """

    def test_avatar_hour_cap_stops_further_grants(self, client, sess, limits, alert):
        limits(grant_max_grants_per_avatar_per_hour=2)
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:av-{i}")
            ).status_code
            for i in range(3)
        ]

        assert statuses == [201, 201, 400]
        assert len(rows_of(sess)) == 2  # 초과분은 행을 만들지 않는다(환급 오발 방지)
        detail = json.dumps(alert.call_args[0][1], ensure_ascii=False)
        assert "per_avatar_hour_exceeded" in detail
        assert "2건 ≥ 상한 2" in detail  # 실제 카운트·상한·창이 문구에 있어야 한다

    def test_avatar_day_cap_stops_further_grants(self, client, sess, limits, worker):
        limits(grant_max_grants_per_avatar_per_day=1)
        product = make_product(sess)

        first = client.post(GRANT_URL, json=payload(product, external_ref="shop:ad-1"))
        second = client.post(GRANT_URL, json=payload(product, external_ref="shop:ad-2"))

        assert (first.status_code, second.status_code) == (201, 400)
        assert "per_avatar_day_exceeded" in json.dumps(
            second.json(), ensure_ascii=False
        )
        assert len(rows_of(sess)) == 1
        assert worker.call_count == 1  # 거절된 요청은 워커로 가지 않는다

    def test_one_capped_avatar_does_not_starve_others(self, client, sess, limits):
        """한 아바타가 자기 상한을 채워도 **다른 아바타는 통과**한다(전역 상한 미달일 때)."""
        limits(grant_max_grants_per_avatar_per_hour=1, grant_max_grants_per_hour=10)
        product = make_product(sess)

        mine = client.post(GRANT_URL, json=payload(product, external_ref="shop:m-1"))
        mine_again = client.post(
            GRANT_URL, json=payload(product, external_ref="shop:m-2")
        )
        other = client.post(
            GRANT_URL,
            json=payload(product, external_ref="shop:o-1", avatarAddress=OTHER_AVATAR),
        )

        assert (mine.status_code, mine_again.status_code, other.status_code) == (
            201,
            400,
            201,
        )
        assert len(rows_of(sess)) == 2

    def test_cap_is_case_insensitive_on_the_address(self, client, sess, limits):
        """
        같은 아바타를 **대소문자만 바꿔** 보내도 같은 축으로 센다.

        요청 스키마가 `0x[0-9a-fA-F]{40}` 를 허용하므로(대문자 hex 가능) 정규화 없이 문자열
        비교하면 대문자 한 번으로 아바타 상한을 우회한다 — 저장은 `format_addr`(소문자)라
        카운트가 0 이 되고, 그건 **조용한 fail-open** 이다.
        """
        limits(grant_max_grants_per_avatar_per_hour=1)
        product = make_product(sess)
        assert (
            client.post(
                GRANT_URL, json=payload(product, external_ref="shop:case-1")
            ).status_code
            == 201
        )

        # `0x` 접두어는 스키마가 소문자로 고정하고, hex 본문만 대문자로 바꾼다.
        upper = client.post(
            GRANT_URL,
            json=payload(
                product,
                external_ref="shop:case-2",
                avatarAddress="0x" + AVATAR[2:].upper(),
            ),
        )

        assert upper.status_code == 400
        assert "per_avatar_hour_exceeded" in json.dumps(
            upper.json(), ensure_ascii=False
        )
        assert len(rows_of(sess)) == 1

    def test_global_cap_still_applies_independently(self, client, sess, limits):
        """
        아바타 축이 여유여도 전역 상한은 그대로 막는다. 사유 토큰도 전역 것이어야 한다 —
        계약 v1.2 의 부류 판정(일시적/영구)이 토큰 문자열에 붙어 있어서, 여러 축이 동시에
        초과일 때 포탈이 보던 토큰이 바뀌면 안 된다.
        """
        limits(grant_max_grants_per_hour=2, grant_max_grants_per_avatar_per_hour=100)
        product = make_product(sess)

        responses = [
            client.post(GRANT_URL, json=payload(product, external_ref=f"shop:g-{i}"))
            for i in range(3)
        ]

        assert [resp.status_code for resp in responses] == [201, 201, 400]
        rejected = json.dumps(responses[-1].json(), ensure_ascii=False)
        assert "per_hour_exceeded" in rejected
        assert "per_avatar" not in rejected  # 전역 축이 먼저 표면화된다
        assert len(rows_of(sess)) == 2

    def test_avatar_axis_is_unset_by_default(self, client, sess, limits, alert):
        """
        새 설정 미주입 = **그 축 미적용**(503 아님). 다른 축은 그대로 동작한다.

        미주입을 503(limits_unset)으로 만들면 차트에 값이 배선되기 전에 이미지가 뜨는 순간
        포인트샵 전체가 멈춘다 — 그래서 이 축은 `missing()` 밖이다.
        """
        limits(grant_max_grants_per_hour=10)  # 아바타 축은 건드리지 않는다(=None)
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:u-{i}")
            ).status_code
            for i in range(5)
        ]

        assert statuses == [201] * 5  # 한 아바타로 5건 — 아바타 축이 없으니 통과
        assert alert.call_count == 0

    def test_avatar_pressure_warning_fires_before_rejection(
        self, client, sess, limits, alert, worker
    ):
        """임박 경고도 새 축에서 나가야 한다 — 거절이 시작된 뒤에만 알리면 손쓸 시간이 없다."""
        limits(grant_max_grants_per_avatar_per_hour=5)
        product = make_product(sess)
        seen = {}
        # 순서를 고정하는 쪽은 **worker.call_count** 다. `len(rows_of(sess))` 는 단독으로는
        #   약하다 — `sess.add(row)` 직후 SELECT 가 autoflush 를 일으켜 **커밋 전에도** 5를
        #   돌려주므로 "커밋 전 알림" 회귀를 못 잡는다. worker 픽스처를 떼면 이 테스트가
        #   조용히 무력해진다는 뜻이다.
        alert.side_effect = lambda *a, **kw: seen.setdefault(
            "at_alert", (len(rows_of(sess)), worker.call_count)
        )

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:aw-{i}")
            ).status_code
            for i in range(5)
        ]

        assert statuses == [201] * 5  # 아직 거절 없음
        assert alert.call_count == 1  # 80% 지점(5번째 요청, 이미 4건)에서 한 번
        text = alert.call_args[0][1]
        assert "per_avatar_hour_exceeded_warn" in text
        assert "임박" in text
        # 경고 webhook 은 **커밋·큐 발행 뒤**여야 한다. `on_warning` 은 advisory lock 안에서
        #   호출되므로 거기서 바로 webhook(타임아웃 3초)을 때리면 전 지급 요청이 잠금 뒤에
        #   줄을 서고, 큐 발행보다 앞에 두면 Slack 지연이 워커 착수를 늦춘다.
        #   알림 시점에 (행 5건 커밋됨, 큐 5건 발행됨) 이어야 그 순서가 지켜진 것이다.
        assert seen["at_alert"] == (5, 5)

    def test_pressure_warnings_are_folded_across_avatars(
        self, client, sess, limits, alert
    ):
        """
        임박 경고의 스로틀 키는 **아바타를 접는다** — 어느 아바타인지는 문구·로그에 남는다.

        정확 키를 쓰면 상한 근처의 아바타 수만큼 요청 경로에서 webhook POST 가 나가고(아바타
        30 = POST 30건), 그 키들이 스로틀 저장소를 채워 위반 알림 스로틀까지 밀어낸다.
        """
        limits(grant_max_grants_per_avatar_per_hour=5)
        product = make_product(sess)

        for slot, avatar in enumerate((AVATAR, OTHER_AVATAR)):
            for i in range(5):
                resp = client.post(
                    GRANT_URL,
                    json=payload(
                        product,
                        external_ref=f"shop:fold-{slot}-{i}",
                        avatarAddress=avatar,
                    ),
                )
                assert resp.status_code == 201

        # 두 아바타가 각자 80% 를 넘겼지만 채널은 1건만 본다(둘 다 문구는 남는다).
        assert alert.call_count == 1
        assert AVATAR in alert.call_args[0][1]

    def test_axis_counts_across_planets(self, client, sess, limits):
        """
        같은 아바타 주소는 **행성을 가리지 않고** 합산한다(`GrantScope` 는 planet 을 안 본다).

        발행 총량 관점에서 더 엄격한 방향이라 안전한 쪽 오차다 — 뒤집으려면 의도적 결정이
        필요하므로 여기서 못박는다.
        """
        limits(grant_max_grants_per_avatar_per_hour=1)
        product = make_product(sess)
        assert (
            client.post(
                GRANT_URL, json=payload(product, external_ref="shop:p-1")
            ).status_code
            == 201
        )

        other_planet = client.post(
            GRANT_URL,
            json=payload(
                product,
                external_ref="shop:p-2",
                planetId=PlanetID.HEIMDALL.value.decode(),
            ),
        )

        assert other_planet.status_code == 400
        assert len(rows_of(sess)) == 1

    def test_failed_rows_still_consume_the_axis(self, client, sess, limits):
        """
        상태를 보지 않는다 — FAILED 행도 축을 소모한다(`_count_since` 의 의도된 설계).

        FAILED 도 nonce·tx 를 썼을 수 있어서 "발행 시도"로 센다. 부작용은 체인 장애 뒤
        재구매가 창이 지날 때까지 막힐 수 있다는 것이고, 그때 처방은 상한 상향이다.
        """
        limits(grant_max_grants_per_avatar_per_hour=1)
        product = make_product(sess)
        assert (
            client.post(
                GRANT_URL, json=payload(product, external_ref="shop:f-1")
            ).status_code
            == 201
        )
        row = sess.scalar(
            select(GrantOutbox).where(GrantOutbox.external_ref == "shop:f-1")
        )
        row.status = GrantStatus.FAILED
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product, external_ref="shop:f-2"))

        assert resp.status_code == 400
        assert "per_avatar_hour_exceeded" in json.dumps(resp.json(), ensure_ascii=False)

    def test_idempotent_repeat_is_not_avatar_rate_limited(
        self, client, sess, limits, worker, alert
    ):
        """
        새 축을 넣어도 **멱등 재요청은 가드를 타지 않는다**(계약 v1.2 불변식 3).

        이미 접수된 주문이 뒤늦은 상한 변경/새 축에 걸려 400 이 되면 포탈 폴링이 깨지고,
        이미 온체인에 나간 지급을 실패로 오판한다.
        """
        limits(
            grant_max_grants_per_avatar_per_hour=1,
            grant_duplicate_alert_window_seconds=60,
        )
        product = make_product(sess)
        assert client.post(GRANT_URL, json=payload(product)).status_code == 201

        repeat = client.post(GRANT_URL, json=payload(product))

        assert repeat.status_code == 200  # 상한을 이미 채운 아바타라도 재요청은 200
        assert repeat.json()["status"] == "PENDING"
        assert len(rows_of(sess)) == 1
        assert worker.call_count == 1
        # 재요청은 가드를 타지 않으므로 중복 경고도 나가지 않는다(같은 주문이니 중복이 아니다).
        assert alert.call_count == 0


class TestDuplicateDetection:
    """
    (PLD-1575) 의미적 중복은 **경고**다 — 거절하지 않는다.

    포탈이 같은 구매에 새 orderId 를 붙여 재요청하면 `external_ref` 가 달라 IAP 멱등키가
    걸리지 않는다. 하지만 짧은 창의 같은 `(아바타, 상품)` 반복은 **정상 반복 구매와 구분되지
    않는다**(1회 뽑기 연속 클릭·같은 팩 2개). 거절하면 정상 구매를 막으므로, 거절은 아바타 축
    상한이 하고 여기서는 사람이 볼 근거만 만든다.
    """

    def test_repeat_within_window_passes_with_one_warning(
        self, client, sess, limits, alert, worker
    ):
        limits(grant_duplicate_alert_window_seconds=60)
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:dup-{i}")
            ).status_code
            for i in range(3)
        ]

        assert statuses == [201] * 3  # **통과** — 거절은 아바타 축 상한이 한다
        assert len(rows_of(sess)) == 3
        assert worker.call_count == 3
        assert alert.call_count == 1  # 2·3번째가 모두 중복이지만 스로틀로 1건
        text = alert.call_args[0][1]
        assert "duplicate_grant_warn" in text
        assert "새 external_ref" in text  # 운영자가 무엇을 볼지 문구에 있어야 한다
        assert "shop_order" in text

    def test_warning_key_is_per_avatar_and_product(self, client, sess, limits, alert):
        """
        서로 다른 (아바타, 상품)의 중복이 서로를 삼키지 않는다 — 스로틀 키에 둘이 들어간다.

        키를 사유만으로 접으면 먼저 발화한 한 건이 1분간 나머지 전부를 가린다.
        """
        limits(grant_duplicate_alert_window_seconds=60)
        one = make_product(sess, name="dup-a")
        two = make_product(sess, name="dup-b")

        for ref, prod, avatar in (
            ("shop:k-1", one, AVATAR),
            ("shop:k-2", one, AVATAR),  # 경고 1 — (AVATAR, one)
            ("shop:k-3", two, AVATAR),
            ("shop:k-4", two, AVATAR),  # 경고 2 — (AVATAR, two)
            ("shop:k-5", one, OTHER_AVATAR),
            ("shop:k-6", one, OTHER_AVATAR),  # 경고 3 — (OTHER, one)
        ):
            resp = client.post(
                GRANT_URL,
                json=payload(prod, external_ref=ref, avatarAddress=avatar),
            )
            assert resp.status_code == 201

        assert alert.call_count == 3

    def test_repeat_outside_window_is_silent(self, client, sess, limits, alert):
        limits(grant_duplicate_alert_window_seconds=60)
        product = make_product(sess)
        assert (
            client.post(
                GRANT_URL, json=payload(product, external_ref="shop:old-1")
            ).status_code
            == 201
        )
        # 첫 행을 창 밖으로 밀어낸다(60초 창 / 1시간 전).
        first = sess.scalar(
            select(GrantOutbox).where(GrantOutbox.external_ref == "shop:old-1")
        )
        first.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product, external_ref="shop:old-2"))

        assert resp.status_code == 201
        assert alert.call_count == 0  # 창 밖 반복은 중복 신호가 아니다

    def test_detection_is_off_by_default(self, client, sess, alert):
        """
        기본값은 **끔**이다 — 정상 반복 구매에서도 발화하는 신호라, 기본으로 켜면 거절 알림과
        같은 채널이 오탐으로 채워진다(알림 피로 → 진짜 거절을 놓친다).
        """
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:off-{i}")
            ).status_code
            for i in range(3)
        ]

        assert statuses == [201] * 3
        assert alert.call_count == 0

    @pytest.mark.parametrize("window", [0, None])
    def test_zero_or_none_window_is_a_kill_switch(
        self, client, sess, limits, alert, window
    ):
        """env 로 끌 때 넣는 값(0)과 미주입(None)이 같게 동작해야 한다."""
        limits(grant_duplicate_alert_window_seconds=window)
        product = make_product(sess)

        for i in range(2):
            assert (
                client.post(
                    GRANT_URL, json=payload(product, external_ref=f"shop:z{window}-{i}")
                ).status_code
                == 201
            )

        assert alert.call_count == 0

    def test_different_avatar_same_product_is_not_a_duplicate(
        self, client, sess, limits, alert
    ):
        limits(grant_duplicate_alert_window_seconds=60)
        product = make_product(sess)

        first = client.post(GRANT_URL, json=payload(product, external_ref="shop:x-1"))
        other = client.post(
            GRANT_URL,
            json=payload(product, external_ref="shop:x-2", avatarAddress=OTHER_AVATAR),
        )

        assert (first.status_code, other.status_code) == (201, 201)
        assert alert.call_count == 0


class TestNamespaceRegistry:
    def test_unregistered_namespace_is_400(self, client, sess, alert, worker):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, external_ref="promo:1"))

        assert resp.status_code == 400
        assert "네임스페이스" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []
        assert worker.call_count == 0
        assert alert.call_count == 1

    def test_missing_namespace_is_400(self, client, sess):
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, external_ref="order-1"))

        assert resp.status_code == 400
        assert rows_of(sess) == []

    def test_registered_extra_namespace_passes(self, client, sess, limits):
        limits(grant_allowed_namespaces="shop, promo")
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product, external_ref="promo:1"))

        assert resp.status_code == 201

    def test_kill_switch_blocks_every_namespace(self, client, sess, limits):
        limits(grant_allowed_namespaces="-")
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert rows_of(sess) == []

    def test_namespace_rate_limit_is_per_namespace(self, client, sess, limits):
        limits(
            grant_allowed_namespaces="shop,promo",
            grant_max_grants_per_namespace_per_minute=1,
        )
        product = make_product(sess)

        first = client.post(GRANT_URL, json=payload(product, external_ref="shop:a"))
        second = client.post(GRANT_URL, json=payload(product, external_ref="shop:b"))
        other = client.post(GRANT_URL, json=payload(product, external_ref="promo:a"))

        # 같은 네임스페이스만 막힌다 — 한 호출자의 버스트가 다른 출처를 굶기지 않는다.
        assert (first.status_code, second.status_code, other.status_code) == (
            201,
            400,
            201,
        )
        assert len(rows_of(sess)) == 2


class TestProductionFailClosed:
    def test_prod_without_limits_is_503_and_alerts(self, client, sess, limits, alert):
        """
        prod 인데 상한 미주입 = 운영 실수 → 503(재시도 가능). 400 이면 포탈이 주문을 영구
        실패로 처리(포인트 환급)하는데, 실제로는 아무 일도 안 일어났다.
        """
        limits(stage="production")
        product = make_product(sess)

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 503
        assert rows_of(sess) == []
        assert alert.call_count == 1
        assert "limits_unset" in json.dumps(alert.call_args[0][1], ensure_ascii=False)

    def test_prod_with_limits_grants(self, client, sess, limits):
        limits(
            stage="production",
            grant_max_fav_units_per_request=100,
            grant_max_item_units_per_request=100,
            grant_max_grants_per_hour=10,
            grant_max_grants_per_day=100,
            grant_max_grants_per_namespace_per_minute=5,
        )
        product = make_product(sess)

        assert client.post(GRANT_URL, json=payload(product)).status_code == 201


class TestViolationAlerting:
    def test_unregistered_namespace_flood_alerts_once(self, client, sess, alert):
        """
        미등록 네임스페이스를 매번 바꿔 던져도 알림은 1건이어야 한다.

        스로틀 키에 **호출자가 조종하는 값**(검증 전 네임스페이스)이 들어가면, ref 만 바꾸는
        것으로 스로틀이 무력화돼 요청마다 webhook POST 가 나간다(Slack 도배 + 요청 경로 지연).
        """
        product = make_product(sess)

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"promo{i}:x")
            ).status_code
            for i in range(5)
        ]

        assert statuses == [400] * 5
        assert alert.call_count == 1
        assert rows_of(sess) == []

    def test_alert_happens_after_transaction_is_released(self, client, sess, alert):
        """
        알림(webhook POST)은 **트랜잭션·advisory lock 을 놓은 뒤**여야 한다.

        시간창 위반은 잠금을 잡은 채로 던져진다 — 그 상태로 Slack 을 기다리면 하필 호출자가
        몰아치는 순간에 모든 지급 요청이 잠금 뒤에 줄을 선다.
        """
        seen = {}
        alert.side_effect = lambda *a, **kw: seen.setdefault(
            "in_transaction", sess.in_transaction()
        )
        product = make_product(sess, grantable=False, name="tx-check")

        assert client.post(GRANT_URL, json=payload(product)).status_code == 400
        assert alert.call_count == 1
        assert seen["in_transaction"] is False

    def test_repeat_violation_alerts_once(self, client, sess, alert):
        """알림 스로틀 — 루프 도는 호출자가 Slack 을 도배하지 못한다(거절은 매번 한다)."""
        product = make_product(sess, grantable=False, name="loop")

        statuses = [
            client.post(
                GRANT_URL, json=payload(product, external_ref=f"shop:x-{i}")
            ).status_code
            for i in range(5)
        ]

        assert statuses == [400] * 5
        assert alert.call_count == 1
        assert rows_of(sess) == []


class TestWhitelistAdmin:
    def test_put_then_get_lists_only_grantable(self, client, sess, alert):
        listed = make_product(sess, grantable=False, name="to-list")
        make_product(sess, grantable=False, name="stays-off")

        resp = client.put(
            WHITELIST_URL, json={"product_id": listed.id, "grantable": True}
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "product_id": listed.id,
            "point_shop_grantable": True,
        }
        # 민터 대상 목록이 넓어지는 사건이라 사람이 보는 채널에도 남는다.
        assert alert.call_count == 1
        assert "grant whitelist" in alert.call_args[0][1]
        # 응답 키는 기존 admin 관례(snake_case) — camelCase 계약은 포탈이 읽는 grant 응답만이다.
        items = client.get(WHITELIST_URL).json()
        assert [i["product_id"] for i in items] == [listed.id]
        assert items[0]["point_shop_grantable"] is True

    def test_put_grantable_on_cash_product_is_400(self, client, sess):
        product = make_product(
            sess, grantable=False, product_type=ProductType.IAP, name="cash-put"
        )

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": True}
        )

        assert resp.status_code == 400
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_turning_off_is_always_allowed_even_in_prod(
        self, client, sess, limits, alert
    ):
        """킬스위치는 게이트 뒤에 두지 않는다 — prod 상한 미주입이어도 끄기는 통과."""
        limits(stage="production")
        product = make_product(sess, grantable=True, name="killswitch")

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": False}
        )

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is False
        assert alert.call_count == 0  # 끄기는 안전한 방향이라 알리지 않는다

    def test_prod_without_limits_cannot_turn_on(self, client, sess, limits):
        limits(stage="production")
        product = make_product(sess, grantable=False, name="prod-on")

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": True}
        )

        assert resp.status_code == 400
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_unknown_product_is_404(self, client, sess):
        resp = client.put(WHITELIST_URL, json={"product_id": 999999, "grantable": True})

        assert resp.status_code == 404

    def test_fav_product_cannot_be_enabled_while_tickers_unset(self, client, sess):
        """
        FAV 티커를 **켜는 시점에** 검증한다 — 지급 시점만 보면 운영자는 200 을 받고 켠 줄 알지만
        실주문이 들어오는 순간 전부 막힌다(그때는 이미 주문이 쌓인 뒤다).
        """
        product = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-enable"
        )

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": True}
        )

        assert resp.status_code == 503
        assert "fav_tickers_unset" in json.dumps(resp.json())
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_fav_product_with_ticker_outside_allowlist_is_400(
        self, client, sess, limits
    ):
        """
        목록이 **있는데** 이 상품 티커가 밖 = 상품 구성 오류 → 400(재시도해도 같다).

        미주입(503)과 갈라지는 이 두 갈래는 지급 시점(`check_fav_tickers`)의 규약이고, 켜는
        경로도 같은 함수를 재사용해 같은 코드를 준다 — 운영자가 "설정을 잊었다"와 "상품이
        잘못됐다"를 상태코드로 구분할 수 있어야 한다.
        """
        limits(grant_allowed_fav_tickers="FAV__NCG")
        product = make_product(
            sess,
            grantable=False,
            with_item=False,
            fav_amount=1,
            name="fav-enable-other",
        )

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": True}
        )

        assert resp.status_code == 400
        assert "fav_ticker_not_allowed" in json.dumps(resp.json())
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_fav_product_can_be_enabled_once_ticker_is_allowed(
        self, client, sess, limits
    ):
        limits(grant_allowed_fav_tickers=CRYSTAL)
        product = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-enable-ok"
        )

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": True}
        )

        assert resp.status_code == 200


PRODUCTS_IMPORT_URL = "/api/admin/products/import"

# 상품 CSV 헤더. `process_csv_row` 가 `row["…"]` 로 **직접** 읽는 컬럼은 하나라도 빠지면
#   KeyError 라 전부 넣는다. `point_shop_grantable` 만 `row.get` 이라(선택 컬럼) 값 없이도 된다.
CSV_HEADER = (
    "id,name,google_sku,apple_sku,apple_sku_k,daily_limit,weekly_limit,account_limit,"
    "order,active,open_timestamp,close_timestamp,discount,rarity,size,popup_path_key,"
    "required_level,product_type,mileage,mileage_price,point_shop_grantable"
)


def _csv_cells(product_id, name, google_sku, apple_sku, apple_sku_k, grantable) -> str:
    """상품 CSV 1행. 나머지 컬럼은 이 테스트가 신경 쓰지 않는 최소 유효값이다."""
    return ",".join(
        [
            product_id,
            name,
            google_sku,
            apple_sku,
            apple_sku_k,
            "",  # daily_limit
            "",  # weekly_limit
            "",  # account_limit
            "1",  # order
            "TRUE",  # active
            "",  # open_timestamp
            "",  # close_timestamp
            "0",  # discount (NOT NULL — 빈칸이면 None 이 되어 제약 위반)
            "NORMAL",  # rarity
            "ONE_BY_ONE",  # size
            "",  # popup_path_key
            "",  # required_level
            "FREE",  # product_type
            "0",  # mileage
            "",  # mileage_price
            grantable,  # point_shop_grantable
        ]
    )


def csv_row(product, *, grantable="", name=None) -> str:
    """기존 상품 1건을 그대로 다시 쓰는 행. `grantable` 빈칸 = 유지(3상태 파서)."""
    return _csv_cells(
        str(product.id),
        name if name is not None else product.name,
        product.google_sku,
        product.apple_sku,
        product.apple_sku_k,
        grantable,
    )


def new_csv_row(*, product_id="", name="csv-new", grantable="TRUE") -> str:
    """DB 에 아직 없는 상품을 만드는 행. `product_id` 빈칸 = autoincrement."""
    sku = f"sku_{name}"
    return _csv_cells(product_id, name, sku, sku, f"{sku}_k", grantable)


class TestWhitelistCsvImport:
    """
    상품 CSV(`POST /admin/products/import`) 도 화이트리스트를 **켜는 경로**다.

    백오피스 CRUD 와 같은 FAV 티커 게이트가 걸려야 하고(안 걸면 임포트는 200 인데 실주문이
    전부 거절된다), 상태코드도 지급 시점과 같아야 한다(미주입 503 / 목록 밖 400).
    거절은 **임포트 전체를 롤백**한다 — voucher 행 검증과 같은 원자성이다.
    """

    def _import(self, client, *rows):
        return client.post(
            PRODUCTS_IMPORT_URL,
            json={
                "environment": "internal",
                "csv_content": "\n".join((CSV_HEADER,) + rows) + "\n",
            },
        )

    def test_fav_product_cannot_be_enabled_while_tickers_unset(self, client, sess):
        product = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-csv-unset"
        )

        resp = self._import(client, csv_row(product, grantable="TRUE"))

        assert resp.status_code == 503
        assert "fav_tickers_unset" in json.dumps(resp.json())
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_ticker_outside_allowlist_is_400(self, client, sess, limits):
        limits(grant_allowed_fav_tickers="FAV__NCG")
        product = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-csv-other"
        )

        resp = self._import(client, csv_row(product, grantable="TRUE"))

        assert resp.status_code == 400
        assert "fav_ticker_not_allowed" in json.dumps(resp.json())
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_allowed_ticker_turns_flag_on(self, client, sess, limits):
        limits(grant_allowed_fav_tickers=CRYSTAL)
        product = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-csv-ok"
        )

        resp = self._import(client, csv_row(product, grantable="TRUE"))

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is True

    def test_item_only_product_is_unaffected(self, client, sess):
        """기본값(빈 목록)이 아이템 상품 임포트를 막지 않는다 — 포인트샵의 정상 케이스."""
        product = make_product(sess, grantable=False, name="item-csv")

        resp = self._import(client, csv_row(product, grantable="TRUE"))

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is True

    def test_turning_off_is_never_gated(self, client, sess):
        """끄는 행은 검사하지 않는다 — 킬스위치를 게이트 뒤에 두면 되돌릴 수단이 없어진다."""
        product = make_product(
            sess, grantable=True, with_item=False, fav_amount=1, name="fav-csv-off"
        )

        resp = self._import(client, csv_row(product, grantable="FALSE"))

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is False

    def test_blank_cell_keeps_flag_without_revalidating(self, client, sess):
        """
        빈칸은 **유지**라 켜는 행이 아니다 → 재검증하지 않는다.

        빈칸까지 검사하면 컬럼 없는 기존 시트의 정기 임포트가 이미 켜진 FAV 상품 때문에
        통째로 막힌다(그 상품의 실주문은 어차피 지급 시점 가드가 막는다).
        """
        product = make_product(
            sess, grantable=True, with_item=False, fav_amount=1, name="fav-csv-blank"
        )

        resp = self._import(client, csv_row(product))

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is True

    def test_rejected_row_rolls_back_whole_import(self, client, sess):
        """
        한 행이 거절되면 **앞 행의 변경까지** 롤백된다(부분 적용 금지).

        CSV 는 시트 한 장이 하나의 의도라 절반만 반영되면 운영자가 무엇이 적용됐는지 알 수
        없다 — voucher 행 검증(`_apply_voucher_row`)이 세운 관례를 그대로 지킨다.
        """
        ok = make_product(sess, grantable=False, name="csv-first-row")
        bad = make_product(
            sess, grantable=False, with_item=False, fav_amount=1, name="fav-csv-last"
        )

        resp = self._import(
            client,
            csv_row(ok, grantable="TRUE", name="csv-renamed"),
            csv_row(bad, grantable="TRUE"),
        )

        assert resp.status_code == 503
        sess.refresh(ok)
        assert ok.name == "csv-first-row"  # 이름 변경도 되돌아갔다
        assert ok.point_shop_grantable is False
        sess.refresh(bad)
        assert bad.point_shop_grantable is False

    def test_reimport_of_an_already_on_row_is_revalidated(self, client, sess):
        """
        이미 켜진 상품도 셀이 TRUE 면 **매번** 재검증한다 — 전이(False→True)만 보지 않는다.

        같은 행의 `product_type` 검사(`validate_point_shop_grantable_eligible`)와 같은 규칙이다:
        시트가 진실 소스라 TRUE 는 "지금 켜져 있어야 한다"는 선언이고, 얼로우리스트가 좁아졌다면
        그 선언이 더는 유효하지 않다.
        ⚠️ 운영상 결과를 알고 받는다 — 시트에 TRUE 가 박힌 FAV 상품이 하나라도 있으면 그 뒤
        **모든** 상품 CSV 임포트(가격·오픈시각 변경 포함)가 허용 티커 설정에 묶인다. 그래서
        `API_GRANT_ALLOWED_FAV_TICKERS` 주입이 화이트리스트를 켜기 전 배포 순서에 들어간다.
        """
        product = make_product(
            sess, grantable=True, with_item=False, fav_amount=1, name="fav-csv-again"
        )

        resp = self._import(client, csv_row(product, grantable="TRUE"))

        assert resp.status_code == 503
        assert "fav_tickers_unset" in json.dumps(resp.json())
        sess.refresh(product)
        assert product.point_shop_grantable is True  # 원래 켜져 있었고 롤백됐다

    def test_new_product_rows_are_not_gated(self, client, sess):
        """
        DB 에 없던 상품을 켜진 상태로 만드는 행은 검사할 구성품이 없다 → 통과.

        FAV 는 뒤이은 `fungible-assets/import` 로 붙고(그 경로엔 이 게이트가 없다 — TODO),
        실주문은 지급 시점 가드가 막는다. id 빈칸(autoincrement)·명시 id 둘 다 같다.
        """
        resp = self._import(
            client,
            new_csv_row(name="csv-blank-id"),
            new_csv_row(product_id="98765", name="csv-explicit-id"),
        )

        assert resp.status_code == 200
        created = sess.scalars(
            select(Product).where(Product.name.in_(["csv-blank-id", "csv-explicit-id"]))
        ).all()
        assert len(created) == 2
        assert all(p.point_shop_grantable is True for p in created)
