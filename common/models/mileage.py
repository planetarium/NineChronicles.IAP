from sqlalchemy import Text, Column, LargeBinary, Integer, Index, UniqueConstraint, DateTime, func

from common.models.base import AutoIdMixin, TimeStampMixin, Base
from common.utils.receipt import PlanetID


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
    planet_id = Column(LargeBinary(length=12), nullable=True, default=PlanetID.ODIN.value,
                       doc="An identifier of planets")
    mileage = Column(Integer, nullable=False, default=0, doc="Current mileage balance")
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
