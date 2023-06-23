from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import backref, relationship

from common.enums import Currency, ProductType, Store
from common.models.base import AutoIdMixin, Base, TimeStampMixin


class Product(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "product"
    name = Column(Text, nullable=False)
    google_sku = Column(Text, doc="SKU ID of google play store")
    apple_sku = Column(Text, doc="SKU ID of apple appstore")
    product_type = Column(ENUM(ProductType), default=ProductType.SINGLE, nullable=False)
    daily_limit = Column(Integer, nullable=True, doc="Purchase limit in 24 hours")
    weekly_limit = Column(Integer, nullable=True, doc="Purchase limit in 7 days (24 * 7 hours)")
    display_order = Column(Integer, nullable=False, default=-1, doc="Display order in client. Ascending sort.")
    active = Column(Boolean, nullable=False, default=False, doc="Is this product active?")

    fav_list = relationship("FungibleAssetProduct", backref=backref("product"))


class FungibleAssetProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_asset_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    # product = relationship("Product", foreign_keys=[product_id], backref=backref("fav_list"))
    ticker = Column(ENUM(Currency, create_type=False), nullable=False)
    amount = Column(Numeric, CheckConstraint("amount > 0"), nullable=False)


class FungibleItemProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_item_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product = relationship("Product", foreign_keys=[product_id], backref=backref("item_list"))
    item_id = Column(Integer, nullable=False, doc="9c Item sheet ID e.g., 300010")
    name = Column(Text, nullable=False)
    fungible_id = Column(Text, nullable=False, doc="9c Fungible ID of item, which is derived from item info")
    amount = Column(Integer, CheckConstraint("amount > 0"), nullable=False)


class Price(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "price"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product = relationship("Product", foreign_keys=[product_id], backref=backref("price_list"))
    store = Column(ENUM(Store), nullable=False)
    currency = Column(Text, nullable=False)
    price = Column(Numeric, nullable=False)
