from enum import IntEnum

import sqlalchemy as sa
from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB

from common.models.base import AutoIdMixin, Base, EnumType, TimeStampMixin
from common.enums import Store, TxStatus


class ReceiptStatus(IntEnum):
    INIT = 0
    VALIDATION_REQUEST = 1
    VALID = 10
    INVALID = 91
    UNKNOWN = 99


class Receipt(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "receipt"
    store = Column(sa.Enum(Store), nullable=False, index=True, doc="Purchased Store Type")
    receipt_id = Column(Text, nullable=False, index=True, doc="Play store / Appstore IAP receipt id")
    receipt_data = Column(JSONB, nullable=False, doc="Full IAP receipt data")
    status = Column(
        EnumType(ReceiptStatus), nullable=False, default=ReceiptStatus.INIT,
        doc="IAP receipt validation status"
    )
    tx_id = Column(Text, nullable=True, index=True, doc="Product giving 9c transaction ID")
    tx_status = Column(EnumType(TxStatus), nullable=True, doc="Transaction status")
