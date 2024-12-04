from sqlalchemy import Text, Column, LargeBinary, Integer, Index, UniqueConstraint

from common.models.base import AutoIdMixin, TimeStampMixin, Base
from common.utils.receipt import PlanetID


class Mileage(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "mileage"
    agent_addr = Column(Text, nullable=False)
    planet_id = Column(LargeBinary(length=12), nullable=True, default=PlanetID.ODIN.value,
                       doc="An identifier of planets")
    mileage = Column(Integer, nullable=False, default=0, doc="Current mileage balance")

    __table_args__ = (
        Index("ix_mileage_agent_planet", planet_id, agent_addr),
        UniqueConstraint("planet_id", "agent_addr", name="unique_planet_agent"),
    )
