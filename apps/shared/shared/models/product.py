from typing import Any, List

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Table,
    Text,
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
