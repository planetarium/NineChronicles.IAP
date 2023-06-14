from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB

from common.enums import ReceiptStatus, Store, TxStatus
from common.models.base import AutoIdMixin, Base, TimeStampMixin


class Receipt(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "receipt"
    store = Column(ENUM(Store, create_type=False), nullable=False, index=True, doc="Purchased Store Type")
    # id = Column(Text, nullable=False, doc="Play store / Appstore IAP receipt id")
    data = Column(JSONB, nullable=False, doc="Full IAP receipt data")
    status = Column(
        ENUM(ReceiptStatus, create_type=False), nullable=False, default=ReceiptStatus.INIT,
        doc="IAP receipt validation status"
    )
    address = Column(Text, nullable=False, index=True, doc="9c Address where to send product")
    tx_id = Column(Text, nullable=True, index=True, doc="Product delivering 9c transaction ID")
    tx_status = Column(ENUM(TxStatus, create_type=False), nullable=True, doc="Transaction status")
