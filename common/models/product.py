from typing import List

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, Text, DateTime, Table
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship, Mapped

from common.enums import Currency, Store, ProductAssetUISize, ProductRarity
from common.models.base import AutoIdMixin, Base, TimeStampMixin

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

    product_list: Mapped[List["Product"]] = relationship("Product", secondary=category_product_table)

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
    # FIXME: Update to nullable=False
    # category_id = Column(Integer, ForeignKey("category.id"))
    # category: Mapped["Category"] = relationship("Category", foreign_keys=[category_id])
    name = Column(Text, nullable=False)
    order = Column(Integer, nullable=False, default=-1, doc="Display order in client. Ascending sort.")
    google_sku = Column(Text, doc="SKU ID of google play store")
    apple_sku = Column(Text, doc="SKU ID of apple appstore")
    # product_type = Column(ENUM(ProductType), default=ProductType.SINGLE, nullable=False)
    daily_limit = Column(Integer, nullable=True, doc="Purchase limit in 24 hours")
    weekly_limit = Column(Integer, nullable=True, doc="Purchase limit in 7 days (24 * 7 hours)")
    account_limit = Column(Integer, nullable=True, doc="Purchase limit for each account (in lifetime)")
    active = Column(Boolean, nullable=False, default=False, doc="Is this product active?")
    discount = Column(Numeric, nullable=False, default=0, doc="Discount by percent. (Use 30 for 30% discount)")
    open_timestamp = Column(DateTime, nullable=True,
                            doc="Open timestamp of this product. If null, it's already opened.")
    close_timestamp = Column(DateTime, nullable=True,
                             doc="Close timestamp of this product. If null, it'll be opened forever.")

    # For Assets
    rarity = Column(ENUM(ProductRarity, create_type=False), nullable=False, default=ProductRarity.NORMAL,
                    doc="Rarity of this product. This is for UI bg color.")
    # FIXME: Update to nullable=False
    size = Column(ENUM(ProductAssetUISize, create_type=False), doc="UI size ratio of this product in client")
    # FIXME: Update to nullable=False
    path = Column(Text, doc="Full asset path")
    # FIXME: Update to nullable=False
    bg_path = Column(Text, doc="Product bg image in list")
    popup_path_key = Column(Text, nullable=True, doc="Product detail popup path key with L10N")
    # FIXME: Update to nullable=False
    l10n_key = Column(Text, doc="L10N Key")

    fav_list: Mapped[List["FungibleAssetProduct"]] = relationship(back_populates="product")
    fungible_item_list: Mapped[List["FungibleItemProduct"]] = relationship(back_populates="product")
    price_list: Mapped[List["Price"]] = relationship(back_populates="product")


class FungibleAssetProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_asset_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(back_populates="fav_list")
    ticker = Column(ENUM(Currency, create_type=False), nullable=False)
    amount = Column(Numeric, CheckConstraint("amount > 0"), nullable=False)


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
