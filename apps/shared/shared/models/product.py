from typing import Any, List

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, relationship

from shared.consts import AVATAR_BOUND_TICKER
from shared.enums import ProductAssetUISize, ProductRarity, ProductType, Store
from shared.models.base import AutoIdMixin, Base, TimeStampMixin

category_product_table = Table(
    "category_product",
    Base.metadata,
    Column("category_id", ForeignKey("category.id")),
    Column("product_id", ForeignKey("product.id")),
)


#: 포인트샵 결제 가능 포인트 종류(product.point_payable_kinds).
#:   ANY = 무상 포인트(PP_S)로도 결제 가능 / NCG = 현금화 가능 포인트로만.
PAYABLE_ANY = "ANY"
PAYABLE_NCG = "NCG"

class Category(AutoIdMixin, TimeStampMixin, Base):
    """
    Category is opened when all following conditions are met:

    - `active` is `True`
    - Current timestamp >= `open_timestamp`
    - Current timestamp < `close_timestamp`
    """

    __tablename__ = "category"
    name = Column(Text, nullable=False)
    order = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=False)
    open_timestamp = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Open timestamp of this product. If null, it's already opened.",
    )
    close_timestamp = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Close timestamp of this product. If null, it'll be opened forever.",
    )
    # FIXME: Update to nullable=False
    l10n_key = Column(Text, doc="L10N Key")

    product_list: Mapped[List["Product"]] = relationship(
        "Product", secondary=category_product_table, order_by="Product.order"
    )

    @property
    def path(self):
        return f"shop/images/category/Icon_Shop_{self.l10n_key.split('_')[-1]}.png"


class Product(AutoIdMixin, TimeStampMixin, Base):
    """
    Product is opened only when all following conditions are met:

    - All conditions in `Category` (in parent) are True
    - `active` is `True`
    - Current timestamp >= `open_timestamp`
    - Current timestamp < `close_timestamp`
    """

    __tablename__ = "product"
    name = Column(Text, nullable=False)
    order = Column(
        Integer,
        nullable=False,
        default=-1,
        doc="Display order in client. Ascending sort.",
    )
    google_sku = Column(Text, doc="SKU ID of google play store")
    apple_sku = Column(Text, doc="SKU ID of apple appstore")
    apple_sku_k = Column(Text, doc="SKU ID of apple appstore for 9c-K")
    product_type = Column(ENUM(ProductType), default=ProductType.IAP, nullable=False)
    required_level = Column(
        Integer,
        nullable=True,
        default=None,
        doc="Required avatar level to purchase this product",
    )
    daily_limit = Column(Integer, nullable=True, doc="Purchase limit in 24 hours")
    weekly_limit = Column(
        Integer, nullable=True, doc="Purchase limit in 7 days (24 * 7 hours)"
    )
    account_limit = Column(
        Integer, nullable=True, doc="Purchase limit for each account (in lifetime)"
    )
    active = Column(
        Boolean, nullable=False, default=False, doc="Is this product active?"
    )
    discount = Column(
        Numeric,
        nullable=False,
        default=0,
        doc="Discount by percent. (Use 30 for 30% discount)",
    )
    open_timestamp = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Open timestamp of this product. If null, it's already opened.",
    )
    close_timestamp = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Close timestamp of this product. If null, it'll be opened forever.",
    )
    mileage = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="Mileage to buyer for purchacing this product",
    )
    mileage_price = Column(
        Integer,
        nullable=True,
        doc="Mileage price to buy this product. Only meaningful for `MILEAGE` type product.",
    )
    point_price = Column(
        Integer,
        nullable=True,
        doc=(
            "(PLD-1561) 포탈 포인트샵 판매가(표시 포인트, 양의 정수). `mileage_price` 와 같은 축이다"
            " — 비현금 화폐로 이 상품을 살 때의 값. NULL = 포인트로 팔지 않는다."
            " 원래는 포탈이 `shop_sku.price_points` 로 따로 들고 있었는데, 그건 IAP 가 이미 가진"
            " 축(가격·기간·한도)을 다시 만든 테이블이었다. 상품 정의는 IAP 소유라는 원칙에 맞춰"
            " 여기로 옮겼다 — 그 덕에 상품 등록·수정이 기존 CSV import·백오피스 CRUD 로 된다"
            " (포탈에는 SKU 등록 경로가 아예 없었다)."
            " ⚠️ 포인트 차감·환급은 여전히 **포탈**이 한다(포인트 원장은 포탈 소유). IAP 는 값만 안다."
            " ⚠️ 뽑기(PLD-1562)의 풀·확률도 상품 정의라 IAP 에 둔다 — 상금표는 **지급하는 쪽**에"
            "    둔다는 원칙이다(복권 상금은 NCG 라 포탈이 지급하므로 표가 포탈에 있다)."
        ),
    )
    point_payable_kinds = Column(
        Text,
        CheckConstraint(f"point_payable_kinds in ('{PAYABLE_ANY}', '{PAYABLE_NCG}')"),
        nullable=False,
        server_default=PAYABLE_ANY,
        doc=(
            "이 상품을 **어떤 포인트로 살 수 있는가**."
            " 'ANY' = 무상 포인트(PP_S)도 가능 / 'NCG' = 현금화 가능 포인트로만."
            " 기획 문서의 'PP-X 전용'(가챠·확정교환)이 'NCG', 'PP-S·PP-X 모두'(주간·아카이브)가"
            " 'ANY' 다(PP-X = 기존 포탈 포인트 = 우리 NCG)."
            " ⚠️ 이건 **확률보다 강한 가드**다 — 가챠를 NCG 전용으로 두면 체크인 적립만 하는"
            "    층(봇 주 서식지)이 가챠에 아예 못 닿는다. 무상 포인트로 살 수 있게 두는 순간"
            "    그 방어가 통째로 사라진다."
            " ⚠️ 'PP_S 전용' 값은 **두지 않는다**. 필요한 적이 없고, 있으면 '현금화 가능 포인트를"
            "    가진 유저가 못 사는 상품'이라는 설정 실수의 자리만 생긴다."
            " ⚠️ 강제는 **포탈**이 한다(차감이 포탈 원장이라). IAP 는 값만 안다 — point_price 와 같다."
        ),
    )
    point_shop_grantable = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc=(
            "(PLD-1575) 영수증 없는 지급 API(POST /api/admin/grant, 포탈 포인트샵)로 지급할 수 있는"
            " 상품인가. **기본 False = 화이트리스트 밖**이라 상품이 새로 생겨도 지급되지 않는다."
            " 그 엔드포인트는 잔액 없이 발행되는 grant_items force-grant 라, 이 플래그가"
            " '무엇을 발행할 수 있나'의 유일한 목록이다(app/grant_guard.py). 현금 상품(IAP)·"
            " 시즌패스 SKU 에는 켤 수 없고, 켜는 경로는 상품 CSV import 와 백오피스 CRUD 둘 다."
        ),
    )

    # For Assets
    rarity = Column(
        ENUM(ProductRarity, create_type=False),
        nullable=False,
        default=ProductRarity.NORMAL,
        doc="Rarity of this product. This is for UI bg color.",
    )
    size = Column(
        ENUM(ProductAssetUISize, create_type=False),
        nullable=False,
        doc="UI size ratio of this product in client",
    )
    path = Column(Text, nullable=False, doc="Full asset path")
    bg_path = Column(Text, nullable=True, doc="Product bg image in list")
    popup_path_key = Column(
        Text, nullable=True, doc="Product detail popup path key with L10N"
    )
    l10n_key = Column(Text, nullable=False, doc="L10N Key")

    fav_list: Mapped[List["FungibleAssetProduct"]] = relationship(
        back_populates="product"
    )
    fungible_item_list: Mapped[List["FungibleItemProduct"]] = relationship(
        back_populates="product"
    )
    price_list: Mapped[List["Price"]] = relationship(back_populates="product")
    gacha_entry_list: Mapped[List["ProductGachaEntry"]] = relationship(
        back_populates="product"
    )

    gacha_draw_count = Column(
        Integer,
        CheckConstraint("gacha_draw_count between 1 and 100"),
        nullable=False,
        server_default="1",
        doc=(
            "한 번 구매가 돌리는 추첨 횟수. 1=단연, 10=10연."
            " **10연은 별도 SKU 다**(가격이 다르므로) — 이 상품은 자기 풀을 갖는다."
            " 상한 100: 추첨이 전역 advisory lock 안에서 돌아 큰 값이 지급 처리량을 막는다"
        ),
    )

    @property
    def is_gacha(self) -> bool:
        """
        뽑기 상품인가 = **자기 안에 풀을 들고 있는가**.

        별도 상품 유형(enum)을 두지 않는다. 뽑기는 도메인상 SKU 하나이고 그 안에 드롭
        테이블이 있는 것이지, "뽑기용 유령 상품"을 따로 만들어 숨기는 구조가 아니다.
        판정을 파생값으로 두면 플래그와 실데이터가 어긋날 자리 자체가 없다.

        ⚠️ 이 관계가 **로드돼 있어야** 한다(`selectinload(Product.gacha_entry_list)`).
           lazy 로 두면 세션 밖에서 DetachedInstanceError 가 나고, 그건 "뽑기가 아니다"로
           오독될 수 있는 자리가 아니라 예외라 차라리 낫지만, 호출부가 전부 로드한다.
        """
        return bool(self.gacha_entry_list)


#: 뽑기 칸의 상금 종류. 지급 tx 의 분기가 이 값으로 갈린다(모델 주석 참고).
GACHA_KIND_ITEM = "ITEM"
GACHA_KIND_FAV = "FAV"


class ProductGachaEntry(AutoIdMixin, TimeStampMixin, Base):
    """
    (PLD-1562) 뽑기 풀의 한 칸 — **뽑기 상품이 자기 안에 든다**.

    ## 왜 상금표가 IAP 에 있는가
    상금표는 **지급하는 쪽**에 둔다. 복권(PLD-1458)의 상금은 NCG 라 포탈이 자기 원장에서
    크레딧하므로 표가 포탈에 있고, 뽑기의 상금은 온체인 아이템이라 IAP 가 `grant_items` 로
    지급하므로 표가 여기 있다. 두 관례가 갈리는 게 아니라 같은 원칙의 두 사례다.

    ## 왜 "뽑기용 상품"을 따로 만들지 않는가
    풀 멤버마다 Product 행을 만들면 50종 뽑기가 상품 50개가 되고, 그것들이 목록에 뜨면
    안 되니 "숨김" 플래그를 또 만들어야 한다. 애초에 유령 상품을 만들지 않으면 숨길 일도
    없다. 그래서 풀은 상품의 **자식 행**이다.

    ## 재추첨 불가가 어디서 강제되는가
    여기가 아니라 `grant_outbox` 다. 추첨은 아웃박스 행을 만들 때 1회 일어나고 결과가
    그 행에 **동결**된다(`gacha_result`). `external_ref` UNIQUE 가 "1 주문 = 1 행" 이므로
    같은 주문의 재요청은 같은 행 = 같은 결과다. 앱 규약이 아니라 DB 제약이 막는다.

    ⚠️ 그래서 이 표를 나중에 고쳐도 **이미 뽑힌 주문의 결과는 바뀌지 않는다**. 워커는 이
       테이블을 읽지 않고 아웃박스에 동결된 값으로 지급한다(그렇게 하지 않으면 운영이
       표를 고치는 것이 곧 뒷문 재추첨이 된다).

    ## 한 칸이 담는 것
    **아이템 또는 FAV 1종 × 수량.** 고정 상품이 줄 수 있는 것과 같은 범위다 — 뽑기라고
    상금 종류가 좁을 이유가 없다(룬스톤·소울스톤·크리스탈이 전부 FAV 축이다).

    온체인에서는 둘 다 `FungibleAssetValue`(티커 + 자릿수 + 수량)라 `ticker` 한 컬럼으로
    충분하다. 그런데 **`kind` 를 따로 둔다** — 지급 tx 를 만드는 분기가 이 값으로 갈리는데
    (FAV 는 `MintAsset`, 아이템은 인벤토리 민팅) 티커 접두어(`FAV__` / `Item_`)로 추론하면
    그 분기가 문자열 관례에 걸리고, 새 접두어 하나에 조용히 어긋난다. 자릿수(`decimal_places`)
    의 의미도 축마다 달라서, 어느 쪽인지가 데이터에 명시돼 있어야 한다.

    번들(한 칸이 여러 종)은 아직 아니다 — `gacha_result.claim` 이 이미 리스트라 스키마
    변경 없이 확장된다.

    ## 10연과 풀
    추첨 횟수는 **상품**(`Product.gacha_draw_count`)이 갖는다. 풀은 여전히 상품당이므로
    "같은 표의 1연/10연" 은 상품 2개 + 풀 2벌이다. 중복처럼 보이지만 IAP 가 원래 그렇게
    생겼다 — 고정 상품도 같은 구성품을 SKU 마다 따로 든다(`fungible_item_product`).
    풀을 공유하는 포인터를 두면 "어느 상품의 표인가" 가 한 겹 더 생기고, 그 간접이
    확률 공시·감사에서 그대로 비용이 된다. 운영은 같은 CSV 를 product_id 만 바꿔 두 번
    올린다(표가 갈리면 1연과 10연의 확률이 달라지므로 **같이 올리는 게 규약**이다).
    """

    __tablename__ = "product_gacha_entry"

    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="gacha_entry_list")
    slot_key = Column(
        Text,
        nullable=False,
        doc=(
            "칸의 정체성. **표의 몇 번째 칸인가**이지 '무엇이 나오는가' 가 아니다."
            " upsert 키이자 UNIQUE 축이라, 같은 아이템을 수량만 다르게 여러 칸 둘 수 있다"
            " (상품표 v0.9 의 재료 티어가 티커 5종 × 수량 2단계 = 9칸이다)."
            " 화면에 나가지 않는 운영 식별자다 — 유저가 보는 문자열은 `name` 쪽"
        ),
    )
    name = Column(
        Text,
        nullable=False,
        doc=(
            "칸 이름. ⚠️ **무인증 공개 API 에 그대로 나간다**"
            "(GET /api/product 의 gacha_pool, 확률 공시). 내부 메모·티켓 번호를 적지 말 것"
            " — 유저가 보는 문자열이다"
        ),
    )
    weight = Column(
        Integer,
        CheckConstraint("weight > 0"),
        nullable=False,
        doc=(
            "가중치. 확률 = weight / Σweight. 0·음수는 제약으로 막는다 —"
            " 0 을 허용하면 '넣었는데 절대 안 나오는 칸'이 조용히 생긴다"
        ),
    )
    kind = Column(
        Text,
        nullable=False,
        # server_default 를 두지 않는다 — 빠뜨린 INSERT 가 조용히 ITEM 이 되면 FAV 칸이
        # 아이템으로 지급을 시도해 tx 가 깨진다. 시끄럽게 죽는 게 맞다.
        doc=(
            "'ITEM' | 'FAV'. **지급 tx 의 분기가 이 값으로 갈린다** —"
            " FAV 는 MintAsset, 아이템은 인벤토리 민팅이다."
            " 티커 접두어로 추론하지 않는다(접두어 관례 하나에 분기가 어긋난다)"
        ),
    )
    ticker = Column(
        Text,
        nullable=False,
        doc=(
            "온체인 티커. 아이템은 `Item_NT_400000`, FAV 는 `FAV__RUNESTONE_HP` 처럼"
            " 저장된 값을 그대로 쓴다(런타임 변환 아님 — build_claim_data 와 같은 규약)"
        ),
    )
    decimal_places = Column(
        Integer,
        CheckConstraint("decimal_places >= 0"),
        nullable=False,
        server_default="0",
        doc="FAV 자릿수. 아이템은 항상 0(아이템엔 소수 자릿수가 없다)",
    )
    sheet_item_id = Column(
        Integer,
        nullable=True,
        doc="9c Item sheet ID e.g., 400000. **아이템 아이콘 표시용**이라 FAV 는 NULL",
    )
    amount = Column(Integer, CheckConstraint("amount > 0"), nullable=False)

    __table_args__ = (
        # 풀 조회는 항상 상품 단위다(`WHERE product_id = ?`).
        Index("ix_product_gacha_entry_product_id", "product_id"),
        # 같은 상품 안에 같은 **칸**이 둘이면 운영 실수(CSV 재임포트의 중복 삽입)다.
        #   ⚠️ 축이 `ticker` 였다가 `slot_key` 로 옮겨왔다(마이그레이션 b2d94f6c15a8).
        #   티커를 축으로 두면 "같은 아이템의 수량 2단계"(상품표 재료 티어)가 표현 불가고,
        #   두 번째 행이 첫 번째를 **조용히 덮어써** 9칸 표가 5칸이 된다 — 임포트는 성공하고
        #   확률만 기획과 달라지는, 가장 늦게 발견되는 종류의 사고다.
        UniqueConstraint(
            "product_id", "slot_key", name="uq_product_gacha_entry_slot"
        ),
        CheckConstraint(
            f"kind in ('{GACHA_KIND_ITEM}', '{GACHA_KIND_FAV}')",
            name="ck_product_gacha_entry_kind",
        ),
        # 아이템은 아이콘 sheet id 가 있어야 하고, FAV 는 없어야 한다. 섞이면 화면이
        # 없는 아이콘을 그리거나(FAV 에 sheet id) 빈 칸이 된다(아이템에 NULL).
        CheckConstraint(
            f"(kind = '{GACHA_KIND_ITEM}') = (sheet_item_id IS NOT NULL)",
            name="ck_product_gacha_entry_sheet_id",
        ),
    )


class FungibleAssetProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_asset_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="fav_list")
    ticker = Column(Text, nullable=False)
    decimal_places = Column(Integer, nullable=False)
    amount = Column(Numeric, CheckConstraint("amount > 0"), nullable=False)

    def to_fav_data(self, agent_address: str, avatar_address: str) -> dict[str, Any]:
        if self.ticker in AVATAR_BOUND_TICKER:
            balance_address = avatar_address
        else:
            balance_address = agent_address
        return {
            "balanceAddr": balance_address,
            "value": {
                "currencyTicker": self.ticker,
                "value": self.amount,
                "decimalPlaces": self.decimal_places,
            },
        }


# TODO: Create Item Table


class FungibleItemProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_item_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="fungible_item_list")
    sheet_item_id = Column(Integer, nullable=False, doc="9c Item sheet ID e.g., 300010")
    name = Column(Text, nullable=False)
    fungible_item_id = Column(
        Text,
        nullable=False,
        doc="9c Fungible ID of item, which is derived from item info",
    )
    amount = Column(Integer, CheckConstraint("amount > 0"), nullable=False)


class Price(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "price"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="price_list")
    store = Column(ENUM(Store), nullable=False)
    currency = Column(Text, nullable=False)
    price = Column(Numeric, nullable=False)
    discount = Column(
        Numeric,
        nullable=False,
        default=0,
        doc="Discount by percent. (Use 30 for 30% discount)",
    )
    regular_price = Column(Numeric, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=False)


# ─────────────────────────────────────────────────────────────────────────────
# 시즌패스 판별 — **한 곳에만 둔다**
# ─────────────────────────────────────────────────────────────────────────────
#
# SKU 규칙: {store}_pkg_{passType}{seasonIndex}{suffix}
#   passType: seasonpass | couragepass | adventurebosspass | worldclearpass
#
# 왜 판별이 필요한가:
#   시즌패스는 구매 처리가 다른 분기로 간다(purchase.py) — send_product 큐에 넣지 않고
#   season_pass_host /api/user/upgrade 를 직접 호출한다. tx_status 를 세팅하는 건 그 워커뿐이라
#   **시즌패스 영수증의 tx_status 는 영구히 NULL** 이다.
#   바우처 발급(voucher_grant_task)이 enroll 조건에 tx_status == SUCCESS 를 걸고 있어
#   시즌패스가 구조적으로 전부 탈락했다(마일리지는 purchase.py 안에서 동기로 주므로 정상 지급됨 —
#   조건을 안 보기 때문이다).
#
# 왜 SKU 인가 — 다른 판별식은 검증 결과 전부 실패한다:
#   · "온체인 지급물 없음"  ✗ 시즌패스도 fungible_item_list 를 갖는다(claim_list 로 넘긴다)
#   · 카테고리             ✗ 3종 모두 NoShow 인데 거기 Planetarium A/B Pack 이 섞여 있다
#   · product_type         ✗ 전부 IAP 다
#
# ⚠️ 대소문자를 구분한다(파이썬 `in` / SQL `LIKE` 둘 다). purchase.py 의 분기와 **정확히 같은**
#    집합이어야 하기 때문이다 — 여기서만 관대해지면 tx 를 만드는 상품에까지 예외가 새어나간다.
SEASON_PASS_SKU_TOKEN = "pass"


def is_season_pass_product(product: "Product") -> bool:
    """이 상품이 시즌패스인가(= send_product 큐를 타지 않아 tx_status 가 NULL 로 남는가)."""
    return SEASON_PASS_SKU_TOKEN in (product.google_sku or "")


def season_pass_sku_filter():
    """`is_season_pass_product` 의 SQL 판(같은 토큰·같은 대소문자 규칙)."""
    return Product.google_sku.like(f"%{SEASON_PASS_SKU_TOKEN}%")
