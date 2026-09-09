"""
(PLD-1575) 상품 조회의 카탈로그 분리 — 현금(기본) vs 포탈 포인트샵.

지키려는 것은 두 방향이다.
  · **누출 금지**: 포인트 전용 상품(`point_shop_grantable=true`)이 파라미터 없는 기본 호출
    (= 게임 클라·현금 웹샵)에 절대 실리지 않는다. 그 상품은 현금 `price_list` 가 비어 있어
    기존 클라가 0원으로 그리거나 깨진다.
  · **포탈이 계속 그릴 수 있다**: `catalog=point` 로 부르면 같은 스키마로 포인트 상품만 온다
    (포탈은 표시 정보를 이 응답에서 합성한다 — 제외만 하면 카탈로그를 못 그린다).
그리고 기존 필터(상품 active·기간·카테고리 active·구매 이력·복권 티켓)가 **두 모드 모두에서**
그대로 살아 있는지까지 본다 — 회귀가 생기는 자리는 필터 순서를 건드릴 때다.

**실 앱(`main.app`)을 그대로 띄운다** — 검증하려는 게 쿼리 파라미터 계약(경로·기본값·잘못된
값의 상태코드)과 `response_model` 직렬화라서, 함수 직접 호출로는 그 절반이 안 보인다.
(필수 env 는 `tests/conftest.py` 가 미리 채운다.)

DB 는 in-memory SQLite, 이 경로가 실제로 건드리는 테이블만 만든다. `receipt` 는 PG 전용
JSONB + `func.timezone('Asia/Seoul', ...)` PG 함수를 써서 SQLite 에 만들 수 없다 →
구매 이력은 `get_purchase_history` 를 대역으로 갈아 끼운다(테스트 대상이 아니다).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from shared.enums import ProductAssetUISize, ProductRarity, ProductType
from shared.models.base import Base
from shared.models.product import (
    Category,
    FungibleAssetProduct,
    FungibleItemProduct,
    Product,
)
from shared.models.product_voucher_grant import ProductVoucherGrant
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main  # 실 FastAPI 앱(라우터 prefix·에러 핸들러 포함)
from app.api import product as product_api
from app.dependencies import session as session_dep
from app.utils import verify_token

PRODUCT_URL = "/api/product"
ADMIN_PRODUCTS_URL = "/api/admin/products"
AGENT = "0x" + "cd" * 20
ODIN = "0x000000000000"
THOR = "0x000000000003"

_TABLES = (
    "category",
    "category_product",
    "product",
    "fungible_asset_product",
    "fungible_item_product",
    "price",
    "product_voucher_grant",
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
    # `expire_on_commit=False`: SQLite 의 DATETIME 은 tzinfo 를 버리므로 commit 후 재로드하면
    #   open/close_timestamp 가 naive 로 돌아온다 → 엔드포인트의 `> datetime.now(timezone.utc)`
    #   비교가 TypeError. 만료를 끄면 파이썬에서 넣은 aware 값이 유지돼 PG(timestamptz) 와 같은
    #   모양이 된다.
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def purchase_history(monkeypatch):
    """
    구매 이력 대역. `history(product_id, daily=…, weekly=…, account=…)` 로 카운트를 심는다.

    `product.py` 가 `from app.utils import get_purchase_history` 로 가져갔으므로 **그 모듈의
    이름**을 갈아 끼워야 한다(원본 모듈만 패치하면 엔드포인트는 여전히 원본을 부른다).
    """
    counts = {
        "daily": defaultdict(int),
        "weekly": defaultdict(int),
        "account": defaultdict(int),
    }
    monkeypatch.setattr(
        product_api,
        "get_purchase_history",
        lambda sess, planet_id, agent_addr: counts,
    )

    def _set(product_id: int, **kwargs):
        for scope, value in kwargs.items():
            counts[scope][product_id] = value

    return _set


@pytest.fixture
def client(sess):
    main.app.dependency_overrides[session_dep] = lambda: sess
    main.app.dependency_overrides[verify_token] = lambda: None
    with TestClient(main.app) as test_client:
        # admin 라우터의 `Security(HTTPBearer())` 는 헤더 자체가 없으면 403 이다
        #   (검증은 override 로 통과시키지만 헤더 존재는 따로 요구한다).
        #   유저용 `/api/product` 는 이 헤더를 무시한다.
        test_client.headers.update({"Authorization": "Bearer test"})
        yield test_client
    main.app.dependency_overrides.clear()


def make_product(
    sess,
    name: str,
    *,
    point_shop_grantable: bool = False,
    product_type=None,
    active: bool = True,
    open_timestamp=None,
    close_timestamp=None,
    with_components: bool = False,
) -> Product:
    if product_type is None:
        # 포인트 상품은 현금 유형(IAP)일 수 없다 — 화이트리스트를 켜는 시점에 400 으로 막힌다
        #   (`validate_point_shop_grantable_eligible`). 실제 등록 모양을 그대로 쓴다.
        product_type = ProductType.FREE if point_shop_grantable else ProductType.IAP
    product = Product(
        name=name,
        order=1,
        google_sku=f"sku_{name}",
        apple_sku=f"sku_{name}",
        apple_sku_k=f"sku_{name}_k",
        product_type=product_type,
        active=active,
        point_shop_grantable=point_shop_grantable,
        rarity=ProductRarity.NORMAL,
        size=ProductAssetUISize.ONE_BY_ONE,
        path=f"{name}.png",
        l10n_key=f"L10N_{name}",
        mileage=10,
        discount=0,
        open_timestamp=open_timestamp,
        close_timestamp=close_timestamp,
    )
    sess.add(product)
    sess.commit()
    if with_components:
        # Thor 2배의 대상이 되는 구성품(아이템 1종 + FAV 1종). 2배 여부를 보려면 필요하다.
        sess.add(
            FungibleItemProduct(
                product_id=product.id,
                sheet_item_id=300010,
                name="AP Potion",
                fungible_item_id="Item_NT_500000",
                amount=5,
            )
        )
        sess.add(
            FungibleAssetProduct(
                product_id=product.id,
                ticker="FAV__CRYSTAL",
                decimal_places=18,
                amount=100,
            )
        )
        sess.commit()
        # ⚠️ 여기서 `sess.refresh(product)` 를 부르면 안 된다. sess 픽스처의
        #    expire_on_commit=False 를 **이 객체에 대해서만** 되돌려서, SQLite 재로드 때
        #    tzinfo 가 날아간다 → open_timestamp 를 함께 쓰는 테스트가 헬퍼가 아니라
        #    product.py 의 비교식에서 "can't compare offset-naive and offset-aware" 로 터진다.
        #    구성품은 엔드포인트가 joinedload 로 다시 긁어오므로 refresh 가 필요하지도 않다.
    return product


def add_category(sess, name: str, products, *, active: bool = True) -> Category:
    category = Category(name=name, order=1, active=active, l10n_key=f"CAT_{name}")
    category.product_list = list(products)
    sess.add(category)
    sess.commit()
    return category


def fetch_names(client, **params) -> list:
    """응답 카테고리를 평탄화해 상품 이름만. (포탈이 하는 것과 같은 평탄화.)"""
    response = client.get(PRODUCT_URL, params={"agent_addr": AGENT, **params})
    assert response.status_code == 200, response.text
    return sorted(
        product["name"]
        for category in response.json()
        for product in category["product_list"]
    )


def fetch_products(client, **params) -> dict:
    response = client.get(PRODUCT_URL, params={"agent_addr": AGENT, **params})
    assert response.status_code == 200, response.text
    return {
        product["name"]: product
        for category in response.json()
        for product in category["product_list"]
    }


class TestCatalogSplit:
    def test_default_call_hides_point_products(self, client, sess, purchase_history):
        """
        ① 파라미터 없는 호출(= 지금 게임 클라·현금 웹샵이 보내는 그 요청)에 포인트 상품이 없다.
        """
        cash = make_product(sess, "cash1")
        point = make_product(sess, "point1", point_shop_grantable=True)
        add_category(sess, "c1", [cash, point])

        assert fetch_names(client, planet_id=ODIN) == ["cash1"]

    def test_explicit_cash_is_the_same_as_default(self, client, sess, purchase_history):
        """`catalog=cash` 는 기본값의 명시형 — 기본과 결과가 같아야 한다."""
        cash = make_product(sess, "cash1")
        point = make_product(sess, "point1", point_shop_grantable=True)
        add_category(sess, "c1", [cash, point])

        assert fetch_names(client, planet_id=ODIN, catalog="cash") == fetch_names(
            client, planet_id=ODIN
        )

    def test_point_catalog_returns_only_point_products(
        self, client, sess, purchase_history
    ):
        """② `catalog=point` 는 포인트 상품만. 두 카탈로그는 겹치지 않는다."""
        cash = make_product(sess, "cash1")
        point_free = make_product(sess, "point1", point_shop_grantable=True)
        point_mileage = make_product(
            sess,
            "point2",
            point_shop_grantable=True,
            product_type=ProductType.MILEAGE,
        )
        add_category(sess, "c1", [cash, point_free, point_mileage])

        assert fetch_names(client, planet_id=ODIN, catalog="point") == [
            "point1",
            "point2",
        ]

    def test_two_catalogs_partition_the_products(self, client, sess, purchase_history):
        """합집합 = 전 상품, 교집합 = 공집합(분할). 한쪽에 두 번 실리는 상품이 없어야 한다."""
        products = [make_product(sess, f"cash{i}") for i in range(3)] + [
            make_product(sess, f"point{i}", point_shop_grantable=True) for i in range(2)
        ]
        add_category(sess, "c1", products)

        cash_names = fetch_names(client, planet_id=ODIN)
        point_names = fetch_names(client, planet_id=ODIN, catalog="point")

        assert set(cash_names) & set(point_names) == set()
        assert sorted(cash_names + point_names) == sorted(p.name for p in products)

    def test_point_product_response_reuses_user_schema(
        self, client, sess, purchase_history
    ):
        """
        포탈이 표시 정보를 합성하는 필드가 그대로 온다 — 응답 스키마를 새로 만들지 않았다는 것.
        (9c-portal `listShopSkus.ts` 가 읽는 키: id·name·l10n_key·path·bg_path·rarity·
         fav_list·fungible_item_list.)
        """
        point = make_product(sess, "point1", point_shop_grantable=True)
        add_category(sess, "c1", [point])

        product = fetch_products(client, planet_id=ODIN, catalog="point")["point1"]

        for key in (
            "id",
            "name",
            "l10n_key",
            "path",
            "bg_path",
            "rarity",
            "fav_list",
            "fungible_item_list",
            "price_list",
        ):
            assert key in product, key
        assert product["id"] == point.id

    def test_unknown_catalog_value_is_rejected(self, client, sess, purchase_history):
        """
        오타는 조용히 현금 목록으로 떨어지지 않고 400 이다(main.py 가 422→400 으로 바꾼다).
        ⚠️ 이건 **값**이 틀린 경우다. 파라미터를 아예 모르는 옛 서버는 무시하므로 배포 순서
           의존이 없다는 점은 `ProductCatalog` docstring 참고.
        """
        add_category(sess, "c1", [make_product(sess, "cash1")])

        response = client.get(
            PRODUCT_URL,
            params={"agent_addr": AGENT, "planet_id": ODIN, "catalog": "bogus"},
        )

        assert response.status_code == 400

    def test_point_flag_is_not_exposed_to_users(self, client, sess, purchase_history):
        """⑤ 뒷면 — 유저용 응답에는 내부 플래그가 실리지 않는다(두 카탈로그 모두)."""
        cash = make_product(sess, "cash1")
        point = make_product(sess, "point1", point_shop_grantable=True)
        add_category(sess, "c1", [cash, point])

        for catalog in ("cash", "point"):
            products = fetch_products(client, planet_id=ODIN, catalog=catalog)
            assert products
            for product in products.values():
                assert "point_shop_grantable" not in product


class TestExistingFiltersKeptInBothCatalogs:
    """③ 기존 필터는 카탈로그와 무관하게 유지된다."""

    @pytest.fixture(autouse=True)
    def _history(self, purchase_history):
        pass

    @pytest.mark.parametrize(
        ("catalog", "grantable"), [("cash", False), ("point", True)]
    )
    def test_inactive_product_hidden(self, client, sess, catalog, grantable):
        visible = make_product(sess, "visible", point_shop_grantable=grantable)
        hidden = make_product(
            sess, "hidden", point_shop_grantable=grantable, active=False
        )
        add_category(sess, "c1", [visible, hidden])

        assert fetch_names(client, planet_id=ODIN, catalog=catalog) == ["visible"]

    @pytest.mark.parametrize(
        ("catalog", "grantable"), [("cash", False), ("point", True)]
    )
    def test_out_of_window_products_hidden(self, client, sess, catalog, grantable):
        now = datetime.now(timezone.utc)
        visible = make_product(
            sess,
            "visible",
            point_shop_grantable=grantable,
            open_timestamp=now - timedelta(days=1),
            close_timestamp=now + timedelta(days=1),
        )
        not_yet = make_product(
            sess,
            "not_yet",
            point_shop_grantable=grantable,
            open_timestamp=now + timedelta(days=1),
        )
        closed = make_product(
            sess,
            "closed",
            point_shop_grantable=grantable,
            close_timestamp=now - timedelta(days=1),
        )
        add_category(sess, "c1", [visible, not_yet, closed])

        assert fetch_names(client, planet_id=ODIN, catalog=catalog) == ["visible"]

    @pytest.mark.parametrize(
        ("catalog", "grantable"), [("cash", False), ("point", True)]
    )
    def test_inactive_category_hidden(self, client, sess, catalog, grantable):
        add_category(
            sess,
            "off",
            [make_product(sess, "hidden", point_shop_grantable=grantable)],
            active=False,
        )
        add_category(
            sess, "on", [make_product(sess, "visible", point_shop_grantable=grantable)]
        )

        assert fetch_names(client, planet_id=ODIN, catalog=catalog) == ["visible"]

    def test_apple_sku_k_swap_kept(self, client, sess):
        """패키지별 apple_sku 교체(9c-K)가 살아 있다."""
        add_category(sess, "c1", [make_product(sess, "cash1")])

        response = client.get(
            PRODUCT_URL,
            params={"agent_addr": AGENT, "planet_id": ODIN},
            headers={"x-iap-packagename": "com.planetariumlabs.ninechroniclesmobilek"},
        )

        assert response.status_code == 200, response.text
        product = response.json()[0]["product_list"][0]
        assert product["apple_sku"] == "sku_cash1_k"

    def test_thor_doubling_kept_for_cash(self, client, sess):
        """Thor 결제 프로모션 2배(mileage·구성품·에셋 경로)는 현금 카탈로그에서 그대로."""
        add_category(sess, "c1", [make_product(sess, "cash1", with_components=True)])

        product = fetch_products(client, planet_id=THOR)["cash1"]

        assert product["mileage"] == 20
        assert product["path"].endswith("_THOR.png")
        assert product["popup_path_key"].endswith("_THOR")
        assert [item["amount"] for item in product["fungible_item_list"]] == [10]
        assert [fav["amount"] for fav in product["fav_list"]] == [200.0]

    def test_thor_doubling_not_applied_to_point_catalog(self, client, sess):
        """
        포인트 카탈로그에는 Thor 2배를 걸지 않는다 — **표시 = 지급** 불변식.

        2배는 THOR **결제** 프로모션이고(`shared/utils/grant.py` `THOR_PROMO_MULTIPLIER`),
        포인트샵 지급 경로는 항상 1배다(`worker/app/tasks/grant_task.py` `GRANT_MULTIPLIER=1`).
        포탈은 이 응답의 `fav_list`/`fungible_item_list` 를 그대로 그리므로 여기서 부풀리면
        포인트를 차감한 유저에게 "200개 표시 → 100개 지급"이 된다.
        (복권 티켓이 Thor 2배 대상이 아닌 것과 같은 이유 — product.py 의 해당 주석 참고.)
        """
        add_category(
            sess,
            "c1",
            [
                make_product(
                    sess, "point1", point_shop_grantable=True, with_components=True
                )
            ],
        )

        product = fetch_products(client, planet_id=THOR, catalog="point")["point1"]

        assert product["mileage"] == 10
        assert product["path"] == "point1.png"
        assert product["popup_path_key"] == "L10N_point1_PATH"
        assert [item["amount"] for item in product["fungible_item_list"]] == [5]
        assert [fav["amount"] for fav in product["fav_list"]] == [100.0]


class TestPurchaseHistoryAndVoucherTickets:
    """④ 구매 이력·복권 티켓 부착이 깨지지 않는다."""

    def test_purchase_limit_marks_unbuyable(self, client, sess, purchase_history):
        product = make_product(sess, "cash1")
        product.account_limit = 1
        sess.commit()
        add_category(sess, "c1", [product])
        purchase_history(product.id, account=1)

        dumped = fetch_products(client, planet_id=ODIN)["cash1"]

        assert dumped["purchase_count"] == 1
        assert dumped["buyable"] is False

    def test_purchase_limit_below_cap_stays_buyable(
        self, client, sess, purchase_history
    ):
        product = make_product(sess, "cash1")
        product.daily_limit = 3
        sess.commit()
        add_category(sess, "c1", [product])
        purchase_history(product.id, daily=1)

        dumped = fetch_products(client, planet_id=ODIN)["cash1"]

        assert dumped["purchase_count"] == 1
        assert dumped["buyable"] is True

    def test_voucher_tickets_still_attached(self, client, sess, purchase_history):
        """
        현금 카탈로그의 복권 티켓은 그대로 붙는다.
        (포인트 상품에는 애초에 붙지 않는다 — 티켓 발급은 `ProductType.IAP` 전용이고 포인트
         상품은 FREE/MILEAGE 다. 아래 `test_point_catalog_has_no_tickets` 가 그걸 못박는다.)
        """
        product = make_product(sess, "cash1")
        add_category(sess, "c1", [product])
        sess.add(
            ProductVoucherGrant(
                product_id=product.id, ticket_type="STANDARD", count=2, active=True
            )
        )
        sess.commit()

        dumped = fetch_products(client, planet_id=ODIN)["cash1"]

        assert dumped["voucher_ticket_list"] == [
            {"ticket_type": "STANDARD", "count": 2}
        ]

    def test_point_catalog_has_no_tickets(self, client, sess, purchase_history):
        point = make_product(sess, "point1", point_shop_grantable=True)
        add_category(sess, "c1", [point])
        sess.add(
            ProductVoucherGrant(
                product_id=point.id, ticket_type="STANDARD", count=2, active=True
            )
        )
        sess.commit()

        dumped = fetch_products(client, planet_id=ODIN, catalog="point")["point1"]

        assert dumped["voucher_ticket_list"] == []

    @pytest.mark.parametrize("catalog", ["cash", "point"])
    def test_single_voucher_query_regardless_of_catalog(
        self, client, sess, engine, purchase_history, count_select, catalog
    ):
        """
        N+1 금지 구조(`voucher_targets` 를 모아 마지막에 한 번)가 카탈로그 필터를 넣어도 유지된다.
        상품이 여러 개여도 `product_voucher_grant` 조회는 1회.
        """
        products = [make_product(sess, f"cash{i}") for i in range(6)] + [
            make_product(sess, f"point{i}", point_shop_grantable=True) for i in range(6)
        ]
        add_category(sess, "c1", products[:6])
        add_category(sess, "c2", products[6:])

        with count_select(engine, table="product_voucher_grant") as counter:
            names = fetch_names(client, planet_id=ODIN, catalog=catalog)

        assert counter["n"] == 1
        assert len(names) == 6


class TestAdminProductList:
    """⑤ 백오피스 상품 목록은 플래그를 싣는다."""

    def test_flag_is_exposed(self, client, sess):
        cash = make_product(sess, "cash1")
        point = make_product(sess, "point1", point_shop_grantable=True)

        response = client.get(ADMIN_PRODUCTS_URL)

        assert response.status_code == 200, response.text
        body = response.json()
        by_name = {item["name"]: item for item in body["items"]}
        # 필터링하지 않는다 — 백오피스는 두 카탈로그를 다 봐야 한다.
        assert body["total"] == 2
        assert by_name["cash1"]["point_shop_grantable"] is False
        assert by_name["point1"]["point_shop_grantable"] is True
        assert by_name[point.name]["id"] == point.id
        assert by_name[cash.name]["id"] == cash.id

    def test_keeps_existing_product_fields(self, client, sess):
        """스키마를 서브클래스로 바꿨으니 기존 필드가 그대로인지 확인."""
        product = make_product(sess, "cash1")

        response = client.get(ADMIN_PRODUCTS_URL)

        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["name"] == product.name
        assert item["google_sku"] == product.google_sku
        assert item["product_type"] == ProductType.IAP.value
        assert item["mileage"] == product.mileage
        assert item["rarity"] == ProductRarity.NORMAL.value
        assert item["active"] is True
