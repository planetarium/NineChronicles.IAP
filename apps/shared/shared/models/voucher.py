import uuid

from sqlalchemy import UUID, Column, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.orm import Mapped, backref, relationship

from shared.enums import PlanetID
from shared.models.base import AutoIdMixin, Base, TimeStampMixin
from shared.models.product import Product
from shared.models.receipt import Receipt


class VoucherRequest(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "voucher_request"
    receipt_id = Column(Integer, ForeignKey("receipt.id"), nullable=False, unique=True)
    receipt: Mapped["Receipt"] = relationship(
        "Receipt",
        foreign_keys=[receipt_id],
        uselist=False,
        backref=backref("voucher_request"),
    )

    # Copy all required data to view all info solely with this table
    uuid = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        default=uuid.uuid4,
        doc="Internal uuid for management",
    )
    agent_addr = Column(Text, nullable=False)
    avatar_addr = Column(Text, nullable=False)
    planet_id = Column(
        LargeBinary(length=12),
        nullable=False,
        default=PlanetID.ODIN.value,
        doc="An identifier of planets",
    )
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship(
        "Product", foreign_keys=[product_id], uselist=False
    )
    product_name = Column(Text, nullable=False)

    # Voucher request result
    status = Column(Integer, nullable=True)
    message = Column(Text, nullable=True)
