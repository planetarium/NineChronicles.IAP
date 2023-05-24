from sqlalchemy import Column, Integer, Text

from common.models.base import Base


class Item(Base):
    __tablename__ = "item"
    id = Column(Integer, nullable=False, index=True, primary_key=True, doc="Nine Chronicles Item ID")
    name = Column(Text, nullable=True, doc="Item Name")
