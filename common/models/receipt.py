import uuid

from sqlalchemy import Column, Text, UUID
from sqlalchemy.dialects.postgresql import ENUM, JSONB

from common.enums import ReceiptStatus, Store, TxStatus
from common.models.base import AutoIdMixin, Base, TimeStampMixin


class Receipt(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "receipt"
    store = Column(ENUM(Store, create_type=False), nullable=False, index=True, doc="Purchased Store Type")
    # id = Column(Text, nullable=False, doc="Play store / Appstore IAP receipt id")
    uuid = Column(UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4, doc="Internal uuid for management")
    data = Column(JSONB, nullable=False, doc="Full IAP receipt data")
    status = Column(
        ENUM(ReceiptStatus, create_type=False), nullable=False, default=ReceiptStatus.INIT,
        doc="IAP receipt validation status"
    )
    # agentAddress = Column(Text, doc="9c agent address where to get FAVs")
    inventoryAddress = Column(Text, doc="9c avatar's inventory address where to get items")
    tx_id = Column(Text, nullable=True, index=True, doc="Product delivering 9c transaction ID")
    tx_status = Column(ENUM(TxStatus, create_type=False), nullable=True, doc="Transaction status")
