from sqlalchemy import BigInteger, Column, Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import backref, relationship

from common.enums import Currency, GarageActionType, TxStatus
from common.models.base import AutoIdMixin, Base, TimeStampMixin


class GarageFavStatus(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "garage_fav_status"

    address = Column(
        Text, nullable=False,
        doc="Garage address of this FAV. Check balance of this address to get real value in chain"
    )
    ticker = Column(Enum(Currency), nullable=False, index=True)
    amount = Column(Numeric, nullable=False, default='0')


class GarageItemStatus(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "garage_item_status"

    address = Column(Text, nullable=False, doc="Garage address of one item. Each item has it's own garage address.")
    item_id = Column(Integer)
    fungible_id = Column(Text, nullable=False, index=True)
    amount = Column(Integer, nullable=False, default=0)


class GarageActionHistory(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "garage_action_history"
    block_index = Column(BigInteger, nullable=False)
    block_hash = Column(Text, nullable=False)
    tx_hash = Column(Text, nullable=False)
    tx_status = Column(Enum(TxStatus))
    action_type = Column(Enum(GarageActionType), nullable=False, index=True)
    signer = Column(Text, nullable=False, index=True)


class GarageFavHistory(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "garage_fav_history"
    action_id = Column(Integer, ForeignKey("garage_action_history.id"), nullable=False)
    action = relationship("GarageActionHistory", foreign_keys=[action_id], backref=backref("fav_list"))
    origin = Column(Text, nullable=False)  # Can be agent address | avatar address | garage address | inventory address
    destination = Column(
        Text, nullable=False
    )  # Can be agent address | avatar address | garage address | inventory address
    ticker = Column(Enum(Currency), nullable=False, index=True)
    amount = Column(Numeric, nullable=False, default='0')


class GarageItemHistory(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "garage_item_history"
    action_id = Column(Integer, ForeignKey("garage_action_history.id"), nullable=False)
    action = relationship("GarageActionHistory", foreign_keys=[action_id], backref=backref("item_list"))
    origin = Column(Text, nullable=False)  # Can be agent address | avatar address | garage address | inventory address
    destination = Column(
        Text, nullable=False
    )  # Can be agent address | avatar address | garage address | inventory address
    item_id = Column(Integer)
    fungible_id = Column(Text, nullable=False, index=True)
    amount = Column(Integer, nullable=False, default=0)
