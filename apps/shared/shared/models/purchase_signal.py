import uuid

from sqlalchemy import UUID, Column, DateTime, ForeignKey, Integer, Text

from shared.enums import PurchaseSignalStatus
from shared.models.base import AutoIdMixin, Base, EnumType, TimeStampMixin


class PurchaseSignal(AutoIdMixin, TimeStampMixin, Base):
    """클라이언트가 결제 성공 직후 보내온 신호.

    `/api/purchase/log`는 원래 로그만 찍고 버리던 엔드포인트인데, 그 한 줄에
    결제를 완결하는 데 필요한 값(planet/agent/avatar/sku/purchaseToken)이 전부
    들어 있다. 클라이언트가 그 다음 단계인 `/api/purchase/request`를 보내지
    못하면 영수증이 아예 생기지 않고, 스토어는 미확인 결제를 자동 환불한다.
    그 구간을 서버가 사후에 메우기 위해 신호를 남긴다.

    영수증(`Receipt`)이 "검증된 결제"라면 이 테이블은 "결제가 있었다는 주장"이다.
    둘을 섞지 않기 위해 별도 테이블로 둔다.
    """

    __tablename__ = "purchase_signal"

    uuid = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        default=uuid.uuid4,
        doc="Internal uuid for management",
    )
    purchase_token = Column(
        Text,
        nullable=False,
        unique=True,
        doc="Store purchase token. Google: purchaseToken, Apple: transaction ID",
    )
    sku = Column(Text, nullable=False, doc="Store SKU the client reported")
    planet_id = Column(Text, nullable=True, doc="Planet ID as the client sent it")
    agent_addr = Column(Text, nullable=True)
    avatar_addr = Column(
        Text, nullable=True, doc="Empty when the client had no avatar loaded yet"
    )
    status = Column(
        EnumType(PurchaseSignalStatus),
        nullable=False,
        index=True,
        default=PurchaseSignalStatus.RECEIVED,
    )
    receipt_id = Column(Integer, ForeignKey("receipt.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    msg = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<PurchaseSignal {self.sku} :: {self.purchase_token[:16]}... "
            f":: {self.status.name if self.status is not None else None}>"
        )
