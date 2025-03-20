from typing import List, Any, Dict

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, Text, DateTime, Table
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship, Mapped

from common.consts import AVATAR_BOUND_TICKER
from common.enums import Store, ProductAssetUISize, ProductRarity, ProductType
from common.models.base import AutoIdMixin, Base, TimeStampMixin
from iap.settings import CDN_HOST

# 카테고리-제품 다대다 관계를 위한 테이블 정의
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
    open_timestamp = Column(DateTime, nullable=True,
                            doc="Open timestamp of this product. If null, it's already opened.")
    close_timestamp = Column(DateTime, nullable=True,
                             doc="Close timestamp of this product. If null, it'll be opened forever.")
    # FIXME: Update to nullable=False
    l10n_key = Column(Text, doc="L10N Key")

    product_list: Mapped[List["Product"]] = relationship("Product", secondary=category_product_table, order_by="Product.order")

    @property
    def path(self):
        return f"shop/images/category/Icon_Shop_{self.l10n_key.split('_')[-1]}.png"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "active": self.active,
            "l10n_key": self.l10n_key,
            "path": self.path,
            "product_list": [product.to_dict() for product in self.product_list],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "open_timestamp": self.open_timestamp.isoformat() if self.open_timestamp else None,
            "close_timestamp": self.close_timestamp.isoformat() if self.close_timestamp else None
        }


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
    order = Column(Integer, nullable=False, default=-1, doc="Display order in client. Ascending sort.")
    google_sku = Column(Text, doc="SKU ID of google play store")
    apple_sku = Column(Text, doc="SKU ID of apple appstore")
    apple_sku_k = Column(Text, doc="SKU ID of apple appstore for 9c-K")
    product_type = Column(ENUM(ProductType), default=ProductType.IAP, nullable=False)
    required_level = Column(Integer, nullable=True, default=None, doc="Required avatar level to purchase this product")
    daily_limit = Column(Integer, nullable=True, doc="Purchase limit in 24 hours")
    weekly_limit = Column(Integer, nullable=True, doc="Purchase limit in 7 days (24 * 7 hours)")
    account_limit = Column(Integer, nullable=True, doc="Purchase limit for each account (in lifetime)")
    active = Column(Boolean, nullable=False, default=False, doc="Is this product active?")
    discount = Column(Numeric, nullable=False, default=0, doc="Discount by percent. (Use 30 for 30% discount)")
    open_timestamp = Column(DateTime, nullable=True,
                            doc="Open timestamp of this product. If null, it's already opened.")
    close_timestamp = Column(DateTime, nullable=True,
                             doc="Close timestamp of this product. If null, it'll be opened forever.")
    mileage = Column(Integer, nullable=False, default=0, server_default='0', doc="Mileage to buyer for purchacing this product")
    mileage_price = Column(Integer, nullable=True, doc="Mileage price to buy this product. Only meaningful for `MILEAGE` type product.")

    # For Assets
    rarity = Column(ENUM(ProductRarity, create_type=False), nullable=False, default=ProductRarity.NORMAL,
                    doc="Rarity of this product. This is for UI bg color.")
    size = Column(ENUM(ProductAssetUISize, create_type=False), nullable=False,
                  doc="UI size ratio of this product in client")
    # 사용 안함
    path = Column(Text, nullable=False, doc="Full asset path")
    # 값을 직접 넣으면 안됨. ProductSchema에서 설정되는 값을 사용.
    bg_path = Column(Text, nullable=True, doc="Product bg image in list")
    # 사용 안함
    popup_path_key = Column(Text, nullable=True, doc="Product detail popup path key with L10N")
    l10n_key = Column(Text, nullable=False, doc="L10N Key")

    fav_list: Mapped[List["FungibleAssetProduct"]] = relationship(back_populates="product")
    fungible_item_list: Mapped[List["FungibleItemProduct"]] = relationship(back_populates="product")
    price_list: Mapped[List["Price"]] = relationship(back_populates="product")
    category_list = relationship("Category", secondary=category_product_table, back_populates="product_list")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "google_sku": self.google_sku,
            "apple_sku": self.apple_sku,
            "apple_sku_k": self.apple_sku_k,
            "product_type": self.product_type.value,
            "required_level": self.required_level,
            "daily_limit": self.daily_limit,
            "weekly_limit": self.weekly_limit,
            "account_limit": self.account_limit,
            "active": self.active,
            "discount": float(self.discount),
            "open_timestamp": self.open_timestamp.isoformat() if self.open_timestamp else None,
            "close_timestamp": self.close_timestamp.isoformat() if self.close_timestamp else None,
            "mileage": self.mileage,
            "mileage_price": self.mileage_price,
            "rarity": self.rarity.value,
            "size": self.size.value if self.size else None,
            "path": self.path,
            "bg_path": self.bg_path or f"shop/images/product/list/bg_{self.rarity.value}_{self.size.value}.png",
            "popup_path_key": self.popup_path_key or f"{self.l10n_key}_PATH",
            "l10n_key": self.l10n_key,
            "fav_list": [{"ticker": fav.ticker.split("__")[-1], "amount": float(fav.amount)} for fav in self.fav_list],
            "fungible_item_list": [{"sheet_item_id": item.sheet_item_id, "fungible_item_id": item.fungible_item_id, "amount": item.amount, "name": item.name} for item in self.fungible_item_list],
            "category_list": [{"id": category.id, "name": category.name} for category in self.category_list],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "detail_image_path": f"{CDN_HOST}/{self.get_detail_image_s3_path()}" if self.path else None,
            "list_image_path": f"{CDN_HOST}/{self.get_list_image_s3_path()}" if self.path else None,
        }

    def get_detail_image_s3_path(self) -> str:
        """상품 상세 이미지의 S3 경로를 반환합니다."""
        return f"shop/images/product/detail/{self.get_image_name()}"

    def get_list_image_s3_path(self) -> str:
        """상품 목록 이미지의 S3 경로를 반환합니다."""
        return f"shop/images/product/list/{self.get_image_name()}"

    def get_image_name(self) -> str:
        return f"{self.google_sku.split('_')[-1]}.png"

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
            }
        }


# TODO: Create Item Table

class FungibleItemProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_item_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="fungible_item_list")
    sheet_item_id = Column(Integer, nullable=False, doc="9c Item sheet ID e.g., 300010")
    name = Column(Text, nullable=False)
    fungible_item_id = Column(Text, nullable=False, doc="9c Fungible ID of item, which is derived from item info")
    amount = Column(Integer, CheckConstraint("amount > 0"), nullable=False)


class Price(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "price"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="price_list")
    store = Column(ENUM(Store), nullable=False)
    currency = Column(Text, nullable=False)
    price = Column(Numeric, nullable=False)
    discount = Column(Numeric, nullable=False, default=0, doc="Discount by percent. (Use 30 for 30% discount)")
    regular_price = Column(Numeric, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=False)
