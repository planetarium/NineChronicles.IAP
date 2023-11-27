from typing import Any, Dict
import uuid

from sqlalchemy import Column, Text, UUID, DateTime, Integer, ForeignKey, LargeBinary
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import relationship, backref

from common.enums import ReceiptStatus, Store, TxStatus
from common.models.base import AutoIdMixin, Base, TimeStampMixin
from common.models.product import Product
from common.utils.receipt import PlanetID


class Receipt(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "receipt"
    store = Column(ENUM(Store, create_type=False), nullable=False, index=True, doc="Purchased Store Type")
    order_id = Column(Text, nullable=False, doc="Play store / Appstore IAP receipt id")
    uuid = Column(UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4,
                  doc="Internal uuid for management")
    data = Column(JSONB, nullable=False, doc="Full IAP receipt data")
    status = Column(
        ENUM(ReceiptStatus, create_type=False), nullable=False, default=ReceiptStatus.INIT,
        doc="IAP receipt validation status"
    )
    purchased_at = Column(DateTime(timezone=True), nullable=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=True)
    product = relationship(Product, foreign_keys=[product_id], backref=backref("purchase_list"))
    agent_addr = Column(Text, doc="9c agent address where to get FAVs")
    avatar_addr = Column(Text, doc="9c avatar's address where to get items")
    tx = Column(Text, nullable=True, doc="Signed Tx data to be sent.")
    nonce = Column(Integer, nullable=True, doc="Dedicated nonce for this tx.")
    tx_id = Column(Text, nullable=True, index=True, doc="Product delivering 9c transaction ID")
    tx_status = Column(ENUM(TxStatus, create_type=False), nullable=True, doc="Transaction status")
    bridged_tx_id = Column(Text, nullable=True, index=True, doc="Bridged Tx on another planet")
    bridged_tx_status = Column(ENUM(TxStatus, create_type=False), nullable=True,
                               doc="Transaction status on another planet")
    planet_id = Column(LargeBinary(length=12), nullable=False, default=PlanetID.ODIN.value,
                       doc="An identifier of planets")
    msg = Column(Text, nullable=True, doc="Any error message while doing action. Please append, Do not replace.")
