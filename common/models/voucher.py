import uuid

from sqlalchemy import Column, Text, Integer, ForeignKey, UUID, LargeBinary
from sqlalchemy.orm import relationship, backref

from common.models.base import Base, TimeStampMixin, AutoIdMixin
from common.utils.receipt import PlanetID


class VoucherRequest(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "voucher_request"
    receipt_id = Column(Integer, ForeignKey("receipt.id"), nullable=False)
    receipt = relationship("Receipt", foreign_keys=[receipt_id], uselist=False, backref=backref("voucher_request"))

    # Copy all required data to view all info solely with this table
    uuid = Column(UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4,
                  doc="Internal uuid for management")
    agent_addr = Column(Text, nullable=False)
    avatar_addr = Column(Text, nullable=False)
    planet_id = Column(LargeBinary(length=12), nullable=False, default=PlanetID.ODIN.value,
                       doc="An identifier of planets")
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product = relationship("Product", foreign_keys=[product_id], uselist=False)
    product_name = Column(Text, nullable=False)

    # Voucher request result
    status = Column(Integer, nullable=True)
    message = Column(Text, nullable=True)
