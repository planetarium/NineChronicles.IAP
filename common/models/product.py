from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import backref, relationship

from common.enums import Currency
from common.models.base import AutoIdMixin, Base, TimeStampMixin


class Product(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "product"
    name = Column(Text, nullable=False)
    google_sku = Column(Text, doc="SKU ID of google play store")
    apple_sku = Column(Text, doc="SKU ID of apple appstore")


class FungibleAssetProduct(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "fungible_asset_product"
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product = relationship("Product", foreign_keys=[product_id], backref=backref("fav_list"))
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
