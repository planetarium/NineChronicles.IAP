import uuid

from sqlalchemy import Column, Text, Integer, UUID

from common.models.base import AutoIdMixin, TimeStampMixin, Base


class SignHistory(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "sign_history"
    uuid = Column(UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4,
                  doc="Internal uuid for management")
    request_type = Column(Text, nullable=False, index=True)
    data = Column(Text, doc="Request data. Have to be valid JSON")
    nonce = Column(Integer, nullable=False, doc="dedicated nonce for this request.")
    plain_value = Column(Text, doc="Hex. encoded plain value of transaction.")
    tx_id = Column(Text, doc="Created Tx. Hash")
