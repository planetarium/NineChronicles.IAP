from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, relationship

from shared.models.base import AutoIdMixin, Base, TimeStampMixin
from shared.models.product import Product


class ProductVoucherGrant(AutoIdMixin, TimeStampMixin, Base):
    """
    (PLD-1472) 상품 → NCG Voucher(복권) 티켓 매핑.

    상품이 결제되면 어떤 `ticket_type`(포탈 prizeTables 키: STANDARD/PREMIUM/…)을 몇 장 발급할지.
    한 상품이 여러 종류를 줄 수 있어 (product_id, ticket_type) 별 1행. `active=false`면 발급 제외.
    (IAP는 발급 수량만 정하고, 상금표·확률·개봉은 포탈 voucher_policy가 권위.)
    """

    __tablename__ = "product_voucher_grant"

    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])
    ticket_type = Column(Text, nullable=False, doc="포탈 prizeTables 키")
    count = Column(Integer, nullable=False, default=1, server_default="1")
    active = Column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("product_id", "ticket_type", name="uq_product_voucher_grant"),
    )
