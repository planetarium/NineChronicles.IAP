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
def client(sess, worker):
    main.app.dependency_overrides[session_dep] = lambda: sess
    main.app.dependency_overrides[verify_token] = lambda: None
    with TestClient(main.app) as test_client:
        test_client.headers.update({"Authorization": "Bearer test"})
        yield test_client
    main.app.dependency_overrides.clear()


def make_product(sess, *, with_item=True, name="point-shop-item") -> Product:
    product = Product(
        name=name,
        order=1,
        google_sku=f"sku_{name}",
        apple_sku=f"sku_{name}",
        apple_sku_k=f"sku_{name}_k",
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
        }
        assert body["externalRef"] == "shop:order-1"
        assert body["status"] == "PENDING"
        assert body["txId"] is None
        assert body["txStatus"] is None
        assert body["attempts"] == 0
        assert body["lastError"] is None
        assert body["grantedAt"] is None
        assert body["createdAt"] is not None
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
