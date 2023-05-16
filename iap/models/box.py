from enum import IntEnum

from sqlalchemy import Column, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from iap.models.base import AutoIdMixin, Base


class BoxStatus(IntEnum):
    CREATED = 1
    MESSAGE_SENT = 2
    TX_CREATED = 3
    TX_STAGED = 4
    SUCCESS = 10
    FAIL = 90
    ERROR = 99


class BoxItem(AutoIdMixin, Base):
    __tablename__ = "box_item"
    box_id = Column(Integer, ForeignKey("box.id"), primary_key=True)
    item_id = Column(Integer, ForeignKey("item.id"))
    item = relationship("Item", foreign_keys=[item_id], lazy="eager")
    count = Column(Integer, nullable=False, doc="Packed item count in this box")


class Box(AutoIdMixin, Base):
    __tablename__ = "box"
    name = Column(Text, nullable=False, doc="Box Name for Manager")
    item_list = relationship(BoxItem, lazy="eager")
    price = Column(Float, nullable=False, doc="NCG price to pack this box")
    status = Column(Enum(BoxStatus), nullable=False, default=BoxStatus.CREATED, doc="Status of this box")
    # DISCUSS: Are they needed?
    # seller_address = Column(Text, nullable=False, doc="Seller's 9c agent address")
    # box_address = Column(Text, nullable=False, doc="9c box address")

# DISCUSS: Is this needed?
# class BoxHistory(AutoIdMixin, TimeStampMixin, Base):
#     __tablename__ = "box_history"
#     seller_address = Column(Text, nullable=False)
#     box_address = Column(Text, nullable=False)
#     tx_id = Column(Text, nullable=True, index=True)
#     tx_status = Column(Enum(TxStatus), nullable=False, index=True)
#     block_index = Column(BigInteger, nullable=True, doc="Block index this tx included")
