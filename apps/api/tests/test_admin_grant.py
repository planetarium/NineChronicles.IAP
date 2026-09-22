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
from fastapi import HTTPException  # noqa: E402
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
    ProductGachaEntry,
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
    """Slack 알림 대역. 호출 횟수 = 채널에 뜬 알림 수(지금은 화이트리스트 변경 알림뿐)."""
    mock = MagicMock(return_value=True)
    monkeypatch.setattr(admin, "send_slack_alert", mock)
    return mock


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


# ── 상품 화이트리스트 (남은 유일한 요청 시점 가드) ─────────────────────────────
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

    def test_cash_product_is_400_even_if_flag_is_stale(self, client, sess):
        """플래그가 켜진 채 현금 상품(IAP)으로 바뀐 경우 — 지급 시점 재검증이 잡는다."""
        product = make_product(
            sess, grantable=True, product_type=ProductType.IAP, name="cash"
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "현금 상품" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []

    def test_season_pass_sku_is_400(self, client, sess):
        product = make_product(
            sess, grantable=True, google_sku="g_pkg_couragepass01", name="cp"
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "시즌패스" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []


CRYSTAL = "FAV__CRYSTAL"


OTHER_AVATAR = "0x" + "ef" * 20


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
        self, client, sess, monkeypatch, alert
    ):
        """킬스위치는 게이트 뒤에 두지 않는다 — prod 여도 끄기는 통과.

        ⚠️ 지금 prod 전용 게이트는 없다(머니 가드와 함께 제거). stage 를 바꿔 두는 건
        "게이트가 다시 생기면 이 테스트가 잡는다"는 표식이다.
        """
        monkeypatch.setattr(admin.config, "stage", "production")
        product = make_product(sess, grantable=True, name="killswitch")

        resp = client.put(
            WHITELIST_URL, json={"product_id": product.id, "grantable": False}
        )

        assert resp.status_code == 200
        sess.refresh(product)
        assert product.point_shop_grantable is False
        assert alert.call_count == 0  # 끄기는 안전한 방향이라 알리지 않는다


    def test_unknown_product_is_404(self, client, sess):
        resp = client.put(WHITELIST_URL, json={"product_id": 999999, "grantable": True})

        assert resp.status_code == 404


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
        # 거절 사유는 남아 있는 검사 하나 — 시즌패스 SKU 는 무상 지급 대상이 아니다.
        bad = make_product(
            sess, grantable=False, google_sku="g_seasonpass_01", name="sp-csv-last"
        )

        resp = self._import(
            client,
            csv_row(ok, grantable="TRUE", name="csv-renamed"),
            csv_row(bad, grantable="TRUE"),
        )

        assert resp.status_code == 400
        sess.refresh(ok)
        assert ok.name == "csv-first-row"  # 이름 변경도 되돌아갔다
        assert ok.point_shop_grantable is False
        sess.refresh(bad)
        assert bad.point_shop_grantable is False


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


# ── (PLD-1562) 뽑기 지급 요청 ─────────────────────────────────────────────────
#
# 이 클래스가 존재하는 이유는 리뷰의 뮤테이션 테스트다: `create_grant` 의 뽑기 배선을
# 세 가지로 망가뜨려도(가드 인자 삭제 · 고정+풀 400 비활성화 · 동결 생략) 기존 281건이
# **전부 통과**했다. 순수 함수(`grant_units`·`draw_entry`) 테스트만으로는 "그 함수를
# 실제로 부르는가"가 하나도 안 잡힌다 — 민터 경로의 배선은 엔드포인트에서 못박아야 한다.
def make_gacha_product(sess, *, entries, name="gacha", with_item=False, **kwargs):
    """
    풀을 가진 상품. `entries` = [(이름, weight, 티커, amount), ...] 또는
    [(이름, weight, 티커, amount, slot_key), ...].
    티커가 `FAV__` 로 시작하면 FAV 칸으로 만든다(**테스트 편의일 뿐** — 실제 kind 는
    CSV/DB 의 명시 값이고, 코드가 접두어로 추론하지 않는다).

    slot_key 를 생략하면 티커를 쓴다. **명시할 수 있어야 하는 이유**: 상품표의 재료 티어는
    같은 아이템을 수량만 다르게 여러 칸 두므로(모래시계 8,000/25,000), 티커로 고정하면
    그 구성을 테스트로 표현조차 못 한다.
    """
    product = make_product(sess, with_item=with_item, name=name, **kwargs)
    for entry in entries:
        entry_name, weight, ticker, amount = entry[:4]
        slot_key = entry[4] if len(entry) > 4 else ticker
        is_fav = ticker.startswith("FAV__")
        sess.add(
            ProductGachaEntry(
                product_id=product.id,
                slot_key=slot_key,
                name=entry_name,
                weight=weight,
                kind="FAV" if is_fav else "ITEM",
                ticker=ticker,
                decimal_places=0,
                sheet_item_id=None if is_fav else 400000,
                amount=amount,
            )
        )
    sess.commit()
    sess.refresh(product)
    return product


class TestGachaGrant:
    def test_같은_아이템의_수량_2단계_칸이_지급까지_간다(self, client, sess):
        """
        상품표 v0.9 재료 티어의 실제 모양 — 같은 티커, 다른 수량, 다른 칸.

        추첨 후 `aggregate_claim` 이 **티커로 합산**하므로 claim 은 한 줄이 되고, 수량
        상한(`assert_gacha_entry_within_caps`)은 칸별 최대 수량으로 재므로 합산이 상한을
        넘지 않는다. 이 불변식이 깨지면 10연에서 상한을 조용히 넘는 지급이 생긴다.
        """
        product = make_gacha_product(
            sess,
            entries=[
                ("모래시계", 2100, "Item_NT_400000", 8000, "mat_hourglass_s"),
                ("모래시계", 600, "Item_NT_400000", 25000, "mat_hourglass_l"),
            ],
        )
        product.gacha_draw_count = 10
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 201
        result = resp.json()["drawResult"]
        assert result["drawCount"] == 10
        # 풀 스냅샷은 **두 칸 그대로** — 한 칸으로 합쳐지면 확률 공시가 틀린다.
        assert sorted(s["slotKey"] for s in result["pool"]) == [
            "mat_hourglass_l",
            "mat_hourglass_s",
        ]
        assert {s["amount"] for s in result["pool"]} == {8000, 25000}
        # claim 은 티커 단위라 한 줄로 합산된다.
        assert [c["ticker"] for c in result["claim"]] == ["Item_NT_400000"]
        assert result["claim"][0]["amount"] == sum(d["amount"] for d in result["draws"])

    def test_뽑기_요청은_결과를_동결해_돌려준다(self, client, sess):
        product = make_gacha_product(
            sess, entries=[("레어", 1, "Item_NT_400000", 3)]
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 201
        result = resp.json()["drawResult"]
        assert result is not None, "뽑기인데 결과가 비어 있으면 포탈이 받아 적을 게 없다"
        assert result["drawCount"] == 1
        assert result["draws"][0]["entryName"] == "레어"
        assert result["claim"] == [
            {"kind": "ITEM", "ticker": "Item_NT_400000", "decimalPlaces": 0, "amount": 3}
        ]
        # 풀 스냅샷 — 표를 나중에 바꿔도 "그때 확률"을 재현할 수 있어야 한다.
        assert result["totalWeight"] == 1
        assert [p["weight"] for p in result["pool"]] == [1]
        # 행에도 같은 값이 남아야 한다(워커가 읽는 건 응답이 아니라 이 행이다).
        row = rows_of(sess)[0]
        assert row.gacha_result == result
        # 단연은 FK 를 채운다(조회 편의). 10연은 대표 칸을 박으면 나머지가 조인에서
        #   사라져 집계가 거짓말을 하므로 비운다 — 아래 10연 테스트가 그걸 못박는다.
        assert row.gacha_entry_id == result["draws"][0]["entryId"]

    def test_재요청은_같은_결과다_재추첨하지_않는다(self, client, sess):
        # 불변식 ①. 균등 2칸 풀이라, 재추첨이 일어나면 절반 확률로 값이 갈린다 —
        #   그걸 노리는 게 아니라 **행이 하나뿐**임을 보는 것이다(200 + 기존 행).
        product = make_gacha_product(
            sess,
            entries=[("A", 1, "Item_NT_400001", 1), ("B", 1, "Item_NT_400002", 1)],
        )

        first = client.post(GRANT_URL, json=payload(product))
        second = client.post(GRANT_URL, json=payload(product))

        assert first.status_code == 201
        assert second.status_code == 200, "재요청은 새 행을 만들지 않는다"
        assert second.json()["drawResult"] == first.json()["drawResult"]
        assert len(rows_of(sess)) == 1


    def test_고정_구성품과_풀을_동시에_가지면_400(self, client, sess):
        # "둘 다 주나 하나만 주나"가 정의되지 않는다. 지급은 되돌릴 수 없다.
        product = make_gacha_product(
            sess,
            entries=[("레어", 1, "Item_NT_400000", 1)],
            name="gacha-mixed",
            with_item=True,
        )

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "gacha pool" in json.dumps(resp.json(), ensure_ascii=False)
        assert rows_of(sess) == []

    def test_고정_상품은_결과가_없다(self, client, sess):
        product = make_product(sess, name="fixed-no-draw")
        resp = client.post(GRANT_URL, json=payload(product))
        assert resp.status_code == 201
        assert resp.json()["drawResult"] is None
        assert rows_of(sess)[0].gacha_entry_id is None


    def test_10연은_한_요청에_10회_지급한다(self, client, sess):
        product = make_gacha_product(
            sess,
            entries=[("Hourglass", 1, "Item_NT_400000", 3)],
            name="gacha-10x",
        )
        product.gacha_draw_count = 10
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 201
        result = resp.json()["drawResult"]
        assert result["drawCount"] == 10
        assert len(result["draws"]) == 10, "회차별 원본이 남아야 한다"
        # 같은 칸 10회 → claim 은 합산 1줄(tx 에 같은 통화가 10줄 들어가지 않게).
        assert result["claim"] == [
            {"kind": "ITEM", "ticker": "Item_NT_400000", "decimalPlaces": 0, "amount": 30}
        ]
        # 아웃박스 행은 여전히 1건 = 온체인 tx 1건이다.
        rows = rows_of(sess)
        assert len(rows) == 1
        # 10연은 대표 칸 FK 를 박지 않는다(나머지 9회가 조인에서 사라진다).
        assert rows[0].gacha_entry_id is None


    def test_10연_재요청도_같은_결과다(self, client, sess):
        product = make_gacha_product(
            sess,
            entries=[("A", 1, "Item_NT_400001", 1), ("B", 1, "Item_NT_400002", 1)],
            name="gacha-10x-idem",
        )
        product.gacha_draw_count = 10
        sess.commit()

        first = client.post(GRANT_URL, json=payload(product))
        second = client.post(GRANT_URL, json=payload(product))

        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["drawResult"] == first.json()["drawResult"]
        assert len(rows_of(sess)) == 1


class TestCsvGrantableColumn:
    """
    `point_shop_grantable` 셀 파서. **3상태**(True/False/변경 없음)이고, 토큰 집합이 좁아지면
    시트에 이미 쓰인 값이 임포트를 통째로 400 으로 세운다 — 머니 플래그 옆의 파서라
    여기서 못박는다(가드 제거 때 실제로 한 번 좁혔다가 되돌렸다).
    """

    @pytest.mark.parametrize("cell", ["TRUE", "true", "T", "Y", "YES", "1", " true "])
    def test_true_토큰(self, cell):
        assert grant_guard.parse_point_shop_grantable(cell) is True

    @pytest.mark.parametrize(
        "cell", ["FALSE", "false", "F", "N", "NO", "0", "X", "-", " x "]
    )
    def test_false_토큰(self, cell):
        assert grant_guard.parse_point_shop_grantable(cell) is False

    @pytest.mark.parametrize("cell", [None, "", "   "])
    def test_빈칸은_변경_없음이다(self, cell):
        # 2상태로 읽으면 이 컬럼 없는 옛 시트 재임포트가 전 상품을 꺼 버린다.
        assert grant_guard.parse_point_shop_grantable(cell) is None

    @pytest.mark.parametrize("cell", ["O", "maybe", "2", "ON"])
    def test_모르는_토큰은_거절(self, cell):
        # "모르는 값은 False" 도 위험하다 — 운영자가 켠 줄 알고 방치한다.
        #   `O` 를 true 로 받지 않는 것도 같은 이유(숫자 0 오타와 비대칭이 된다).
        with pytest.raises(ValueError, match="point_shop_grantable"):
            grant_guard.parse_point_shop_grantable(cell)

    def test_미지_상품유형은_차단이_기본이다(self):
        """ProductType 에 새 유형이 추가돼도 기본이 차단 — deny-by-default."""
        with pytest.raises(HTTPException) as e:
            grant_guard.validate_point_shop_grantable_eligible(1, "NEW_TYPE_2027", None)
        assert e.value.status_code == 400
        assert "알 수 없는 상품유형" in e.value.detail


class TestGachaPoolErrorPath:
    def test_자릿수가_범위를_넘는_칸은_400_이고_행을_안_남긴다(self, client, sess, worker):
        """
        `claim_from_result` 가 **유일한 자릿수 방어선**이다 — 실발행량이
        `amount × 10**decimalPlaces` 라 자릿수가 곧 배율인데, DB CHECK 는 `>= 0` 만 본다.

        순수 함수 테스트(test_gacha.py)만으로는 "그 검증이 요청 경로에 실제로 이어져 있는가"가
        안 잡힌다 — 이 파일이 이미 한 번 겪은 함정이라 엔드포인트에서 못박는다.
        """
        product = make_gacha_product(
            sess, entries=[("룬", 1, "FAV__RUNESTONE_HP", 1)], name="bad-places"
        )
        entry = product.gacha_entry_list[0]
        # 룬스톤의 진짜 자릿수는 **0** 이다. 19 면 10^19 배로 나간다.
        #   이제 CSV 임포트가 등록 시점에 막지만, 직접 INSERT 는 그걸 우회하므로
        #   엔드포인트의 이중 방어가 여전히 필요하다 — 이 테스트가 그 자리를 지킨다.
        entry.decimal_places = 19
        sess.commit()

        resp = client.post(GRANT_URL, json=payload(product))

        assert resp.status_code == 400
        assert "gacha pool" in json.dumps(resp.json())
        assert rows_of(sess) == []
        assert worker.call_count == 0
