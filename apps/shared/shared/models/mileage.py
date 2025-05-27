from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)

from shared.enums import PlanetID
from shared.models.base import AutoIdMixin, Base, TimeStampMixin


class Mileage(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "mileage"
    agent_addr = Column(Text, nullable=False)
    mileage = Column(Integer, nullable=False, default=0, doc="Current mileage balance")

    __table_args__ = (
        Index("ix_mileage_agent_planet", agent_addr),
        UniqueConstraint("agent_addr", name="unique_agent"),
    )


class MileageHistory(Base):
    __tablename__ = "mileage_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_addr = Column(Text, nullable=False)
    planet_id = Column(
        LargeBinary(length=12),
        nullable=True,
        default=PlanetID.ODIN.value,
        doc="An identifier of planets",
    )
    mileage = Column(Integer, nullable=False, default=0, doc="Current mileage balance")
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
