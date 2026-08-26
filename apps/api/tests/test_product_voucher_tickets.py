"""
(PLD-1472) 상품 조회 응답의 복권 티켓 노출 — 필터·정렬·하위호환 기본값·N+1.

두 층으로 본다.
  1. `app.voucher_display` — "모아서 한 번에 붙인다"는 로직 자체(필터·정렬·쿼리 수).
  2. 엔드포인트(`app/api/product.py`) — 그 함수를 **루프 밖에서 한 번** 부르는지. N+1 회귀는 정확히
     호출 위치를 옮길 때 생기므로 여기까지 못박아야 의미가 있다.

2번은 모듈을 그냥 임포트할 수 없어 우회가 필요하다(`product_api` 픽스처 주석 참고).

DB 는 in-memory SQLite. 이 경로가 실제로 건드리는 테이블만 만든다 — 나머지 모델은 무관하고
일부는 PG 전용 타입이라 굳이 만들 이유가 없다.
"""
import importlib.util
import sys
import types
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import pytest
from shared.enums import ProductAssetUISize, ProductRarity, ProductType
from shared.models.base import Base
from shared.models.product import Category, Product
from shared.models.product_voucher_grant import ProductVoucherGrant
from shared.schemas.product import SimpleProductSchema
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.voucher_display import active_tickets_by_product, attach_voucher_tickets

PRODUCT_API_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "product.py"

# ProductSchema 가 실제로 읽는 관계까지 포함한 최소 집합.
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
    # StaticPool + check_same_thread=False: TestClient 는 sync 엔드포인트를 워커 스레드에서 돌리는데
    # sqlite 커넥션은 기본적으로 생성 스레드에 묶인다. 단일 커넥션을 공유해 그 제약을 푼다.
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


@pytest.fixture(scope="module")
def product_api():
    """
    엔드포인트 모듈을 **부모 패키지를 우회**해 로드한다.

    `import app.api.product` 는 `app/api/__init__.py` 를 실행해 admin/purchase 까지 끌어오고 그
    과정에서 `app.config.Settings()` 가 평가된다. 개발자 로컬 `.env` 에 현재 Settings 가
    금지(extra_forbidden)하는 옛 키가 남아 있으면 임포트 자체가 실패한다 — 환경에 따라 되기도
    안 되기도 하는 테스트가 된다(`test_voucher_validation.py` 가 CSV 경로 테스트를 포기한 이유).

    그래서 config/DB/유틸만 스텁으로 갈아끼우고 product.py 파일 하나만 별도 이름으로 로드한다.
    진짜 `app` 패키지는 건드리지 않고, 갈아끼운 키는 끝나면 되돌린다 — 같은 세션의
    `test_voucher_validation.py` 가 `from app import voucher_validation` 을 쓰기 때문이다.
    """
    config_stub = types.ModuleType("app.config")
    config_stub.config = types.SimpleNamespace(stage="mainnet")

    dependencies_stub = types.ModuleType("app.dependencies")
    dependencies_stub.session = lambda: None  # Depends() 자리만 채우면 된다(직접 호출하므로)

    utils_stub = types.ModuleType("app.utils")
    utils_stub.get_purchase_history = lambda sess, planet_id, agent_addr: {
        "daily": defaultdict(int),
        "weekly": defaultdict(int),
        "account": defaultdict(int),
    }

    stubs = {
        "app.config": config_stub,
        "app.dependencies": dependencies_stub,
        "app.utils": utils_stub,
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "product_api_under_test", PRODUCT_API_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def make_product(sess, name: str, product_type=ProductType.IAP) -> Product:
    product = Product(
        name=name,
        order=1,
        google_sku=f"sku_{name}",
        apple_sku=f"sku_{name}",
        apple_sku_k=f"sku_{name}_k",
        product_type=product_type,
        active=True,
        rarity=ProductRarity.NORMAL,
        size=ProductAssetUISize.ONE_BY_ONE,
        path=f"{name}.png",
        l10n_key=f"L10N_{name}",
        mileage=10,  # Thor 2배 대조군 — 티켓이 함께 부풀지 않는지 보려면 0 이면 안 된다
        discount=0,
    )
    sess.add(product)
    sess.commit()
    return product


def add_grant(sess, product: Product, ticket_type: str, count: int = 1, active=True):
    sess.add(
        ProductVoucherGrant(
            product_id=product.id, ticket_type=ticket_type, count=count, active=active
        )
    )
    sess.commit()


@contextmanager
def count_select(engine, table: str = ""):
    """
    블록 안에서 나간 SELECT 수. N+1 회귀를 숫자로 못박는 용도.

    `table` 을 주면 그 테이블을 건드린 SELECT 만 센다 — 엔드포인트에는 이 변경과 무관한 선행
    lazy load(예: `price_list`)가 있어서, 전체 수를 세면 이 PR 이 보증하려는 것과 다른 걸 재게 된다.
    """
    counter = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        if table and table not in statement:
            return
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before)


class TestActiveTicketsByProduct:
    def test_only_active_mappings_are_exposed(self, sess):
        """active=false 는 placeholder(=킬스위치)라 발급되지 않는다 → 응답에도 없어야 한다."""
        product = make_product(sess, "p1")
        add_grant(sess, product, "STANDARD", 2, active=True)
        add_grant(sess, product, "PREMIUM", 5, active=False)

        tickets = active_tickets_by_product(sess, [product.id])[product.id]

        assert [(t.ticket_type, t.count) for t in tickets] == [("STANDARD", 2)]

    def test_multiple_types_sorted_by_ticket_type(self, sess):
        """여러 종류는 ticket_type 오름차순 고정 — 삽입 순서/DB 반환 순서에 흔들리지 않게."""
        product = make_product(sess, "p1")
        for ticket_type in ("STANDARD", "GOLD", "PREMIUM"):  # 일부러 역순 섞어 삽입
            add_grant(sess, product, ticket_type, 1)

        tickets = active_tickets_by_product(sess, [product.id])[product.id]

        assert [t.ticket_type for t in tickets] == ["GOLD", "PREMIUM", "STANDARD"]

    def test_product_without_mapping_is_absent(self, sess):
        """매핑 없는 상품은 키 자체가 없다(= 호출부에서 스키마 기본값 [] 유지)."""
        product = make_product(sess, "p1")

        assert active_tickets_by_product(sess, [product.id]) == {}

    def test_all_inactive_mappings_is_absent(self, sess):
        """전부 비활성이면 '매핑 없음'과 같게 보여야 한다(메인넷 킬스위치 상태)."""
        product = make_product(sess, "p1")
        add_grant(sess, product, "STANDARD", 2, active=False)

        assert active_tickets_by_product(sess, [product.id]) == {}

    @pytest.mark.parametrize("bad_count", [0, -1])
    def test_non_positive_count_excluded(self, sess, bad_count):
        """count<=0 은 워커가 발급을 건너뛴다 → 표시도 하지 않는다(없는 티켓 광고 금지)."""
        product = make_product(sess, "p1")
        add_grant(sess, product, "STANDARD", bad_count)
        add_grant(sess, product, "PREMIUM", 2)

        tickets = active_tickets_by_product(sess, [product.id])[product.id]

        assert [t.ticket_type for t in tickets] == ["PREMIUM"]

    def test_grouping_and_sort_across_products(self, sess):
        """여러 상품이 섞여 와도 상품별로 갈리고, 각 그룹 안에서 정렬이 유지돼야 한다."""
        first = make_product(sess, "p1")
        second = make_product(sess, "p2")
        add_grant(sess, first, "STANDARD", 1)
        add_grant(sess, second, "STANDARD", 4)
        add_grant(sess, first, "GOLD", 2)
        add_grant(sess, second, "GOLD", 3)

        ticket_map = active_tickets_by_product(sess, [first.id, second.id])

        assert [(t.ticket_type, t.count) for t in ticket_map[first.id]] == [
            ("GOLD", 2),
            ("STANDARD", 1),
        ]
        assert [(t.ticket_type, t.count) for t in ticket_map[second.id]] == [
            ("GOLD", 3),
            ("STANDARD", 4),
        ]

    @pytest.mark.parametrize("product_type", [ProductType.FREE, ProductType.MILEAGE])
    def test_non_iap_product_excluded(self, sess, product_type):
        """(C6) 결제 상품만 발급 대상 — 워커가 안 주는 걸 클라에 보여주면 안 된다."""
        product = make_product(sess, "p1", product_type=product_type)
        add_grant(sess, product, "STANDARD", 2)

        assert active_tickets_by_product(sess, [product.id]) == {}

    def test_empty_input_does_not_query(self, sess, engine):
        with count_select(engine) as counter:
            assert active_tickets_by_product(sess, []) == {}
        assert counter["n"] == 0

    def test_other_products_mappings_do_not_leak(self, sess):
        first = make_product(sess, "p1")
        second = make_product(sess, "p2")
        add_grant(sess, first, "STANDARD", 1)
        add_grant(sess, second, "PREMIUM", 3)

        ticket_map = active_tickets_by_product(sess, [first.id])

        assert list(ticket_map) == [first.id]


class TestAttachVoucherTickets:
    def _schema(self, product: Product) -> SimpleProductSchema:
        return SimpleProductSchema.model_validate(product)

    def test_attaches_tickets_to_matching_schema_only(self, sess):
        with_mapping = make_product(sess, "p1")
        without_mapping = make_product(sess, "p2")
        add_grant(sess, with_mapping, "STANDARD", 2)

        schemas = {p.id: self._schema(p) for p in (with_mapping, without_mapping)}
        attach_voucher_tickets(sess, schemas.items())

        assert [
            (t.ticket_type, t.count) for t in schemas[with_mapping.id].voucher_ticket_list
        ] == [("STANDARD", 2)]
        # 매핑 없는 상품은 기본값 그대로 — "매핑 없음"과 "필드 없음"이 같게 보인다(하위호환).
        assert schemas[without_mapping.id].voucher_ticket_list == []

    def test_same_product_in_two_categories_gets_own_list(self, sess):
        """상품↔카테고리가 다대다라 같은 상품이 서로 다른 스키마로 두 번 실릴 수 있다."""
        product = make_product(sess, "p1")
        add_grant(sess, product, "STANDARD", 2)
        first, second = self._schema(product), self._schema(product)

        attach_voucher_tickets(sess, [(product.id, first), (product.id, second)])

        assert first.voucher_ticket_list[0].ticket_type == "STANDARD"
        assert second.voucher_ticket_list[0].ticket_type == "STANDARD"
        assert first.voucher_ticket_list is not second.voucher_ticket_list

    def test_single_query_regardless_of_product_count(self, sess, engine):
        """
        N+1 금지. 상품 수를 늘려도 티켓 조회는 항상 SELECT 1회여야 한다
        (상품마다 조회하면 `GET /api/product/all` 이 그대로 수백 쿼리가 된다).
        """
        products = [make_product(sess, f"p{i}") for i in range(25)]
        for product in products:
            add_grant(sess, product, "STANDARD", 1)
            add_grant(sess, product, "PREMIUM", 2)
        schemas = [(p.id, self._schema(p)) for p in products]
        sess.expunge_all()  # 상품 로드로 인한 lazy load 를 이 측정에서 배제

        with count_select(engine) as counter:
            attach_voucher_tickets(sess, schemas)

        assert counter["n"] == 1
        assert all(len(schema.voucher_ticket_list) == 2 for _, schema in schemas)

    def test_empty_targets_does_not_query(self, sess, engine):
        with count_select(engine) as counter:
            attach_voucher_tickets(sess, [])
        assert counter["n"] == 0


class TestEndpoints:
    """엔드포인트가 티켓을 실제로 싣는지 + 조회를 루프 밖에서 한 번만 하는지."""

    AGENT = "0x0000000000000000000000000000000000000001"

    def _catalog(self, sess, product_count: int = 12, mapped: int = 6):
        products = [make_product(sess, f"p{i:02d}") for i in range(product_count)]
        for product in products[:mapped]:
            add_grant(sess, product, "STANDARD", 2)
            add_grant(sess, product, "GOLD", 1)
            add_grant(sess, product, "OFF", 9, active=False)
        category = Category(name="c1", order=1, active=True, l10n_key="CAT_TEST")
        category.product_list = products
        sess.add(category)
        sess.commit()
        return products

    def test_product_list_single_voucher_query(self, product_api, sess, engine):
        """
        상품이 12개여도 `product_voucher_grant` 조회는 1회. 상품 루프 안으로 옮기면 여기서 깨진다.
        (전체 SELECT 를 세지 않는 이유는 count_select 주석 참고 — price_list 선행 lazy load 가 있다.)
        """
        self._catalog(sess)

        with count_select(engine, table="product_voucher_grant") as counter:
            result = product_api.product_list(
                agent_addr=self.AGENT, planet_id="0x000000000000", sess=sess
            )

        assert counter["n"] == 1
        by_name = {p.name: p for p in result[0].product_list}
        assert [
            (t.ticket_type, t.count) for t in by_name["p00"].voucher_ticket_list
        ] == [("GOLD", 1), ("STANDARD", 2)]
        assert by_name["p11"].voucher_ticket_list == []

    def test_all_product_list_single_voucher_query(self, product_api, sess, engine):
        """`/all` 도 마찬가지. (`@cache` 데코레이터를 벗겨 본체를 직접 부른다.)"""
        self._catalog(sess)

        with count_select(engine, table="product_voucher_grant") as counter:
            result = product_api.all_product_list.__wrapped__(sess=sess)

        assert counter["n"] == 1
        dumped = {p.name: p.model_dump()["voucher_ticket_list"] for p in result}
        assert dumped["p00"] == [
            {"ticket_type": "GOLD", "count": 1},
            {"ticket_type": "STANDARD", "count": 2},
        ]
        assert dumped["p11"] == []

    def test_all_product_list_keeps_existing_fields(self, product_api, sess):
        """ORM 반환 → 스키마 명시 생성으로 바뀌었다. 기존 필드가 그대로인지 확인."""
        products = self._catalog(sess, product_count=1, mapped=0)

        result = product_api.all_product_list.__wrapped__(sess=sess)

        dumped = result[0].model_dump()
        assert dumped["name"] == products[0].name
        assert dumped["google_sku"] == products[0].google_sku
        assert dumped["product_type"] == ProductType.IAP
        assert dumped["mileage"] == products[0].mileage
        assert dumped["active"] is True

    def test_response_model_roundtrip_keeps_tickets(self, product_api, sess):
        """
        위 테스트들은 함수를 직접 불러 **스키마 객체**를 본다. 실제 응답은 FastAPI 가 한 번 더
        `response_model` 로 재검증·직렬화하므로, 클라가 실제로 받는 JSON 까지 확인한다.
        (`/all` 은 `@cache` 경로를 그대로 통과시키므로 캐시 인코딩까지 덤으로 덮인다.)
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi_cache import FastAPICache
        from fastapi_cache.backends.inmemory import InMemoryBackend

        self._catalog(sess, product_count=2, mapped=1)

        app = FastAPI()
        app.include_router(product_api.router)
        # Depends() 의 키는 product.py 가 임포트해 간 함수 객체 자체 = 여기선 스텁.
        app.dependency_overrides[product_api.session] = lambda: sess

        @app.on_event("startup")
        async def _init_cache():
            FastAPICache.init(InMemoryBackend())

        with TestClient(app) as client:
            categories = client.get(
                "/product", params={"agent_addr": self.AGENT, "planet_id": "0x000000000000"}
            ).json()
            all_products = client.get("/product/all").json()

        by_name = {p["name"]: p for p in categories[0]["product_list"]}
        assert by_name["p00"]["voucher_ticket_list"] == [
            {"ticket_type": "GOLD", "count": 1},
            {"ticket_type": "STANDARD", "count": 2},
        ]
        assert by_name["p01"]["voucher_ticket_list"] == []
        assert {p["name"]: p["voucher_ticket_list"] for p in all_products} == {
            "p00": [
                {"ticket_type": "GOLD", "count": 1},
                {"ticket_type": "STANDARD", "count": 2},
            ],
            "p01": [],
        }

    def test_thor_doubling_does_not_touch_tickets(self, product_api, sess):
        """Thor 는 mileage·아이템을 2배로 주지만 복권 티켓은 워커가 매핑 count 그대로 발급한다."""
        self._catalog(sess, product_count=1, mapped=1)

        result = product_api.product_list(
            agent_addr=self.AGENT, planet_id="0x000000000003", sess=sess
        )

        product_schema = result[0].product_list[0]
        assert product_schema.mileage == 20  # 2배 적용된 것 확인(대조군)
        assert [
            (t.ticket_type, t.count) for t in product_schema.voucher_ticket_list
        ] == [("GOLD", 1), ("STANDARD", 2)]


class TestSchemaBackwardCompatibility:
    def test_default_is_empty_list(self, sess):
        """ORM Product 에는 대응 속성이 없다 — 검증만으로는 항상 빈 리스트(구버전과 동일한 모양)."""
        product = make_product(sess, "p1")

        assert SimpleProductSchema.model_validate(product).voucher_ticket_list == []

    def test_default_list_is_not_shared_between_instances(self, sess):
        """기본값을 공유하면 한 상품에 붙인 티켓이 다른 상품에 새어 나간다."""
        product = make_product(sess, "p1")
        first = SimpleProductSchema.model_validate(product)
        second = SimpleProductSchema.model_validate(product)

        assert first.voucher_ticket_list is not second.voucher_ticket_list

    def test_serialized_field_is_snake_case(self, sess):
        product = make_product(sess, "p1")
        add_grant(sess, product, "STANDARD", 2)
        schema = SimpleProductSchema.model_validate(product)

        attach_voucher_tickets(sess, [(product.id, schema)])

        assert schema.model_dump()["voucher_ticket_list"] == [
            {"ticket_type": "STANDARD", "count": 2}
        ]
