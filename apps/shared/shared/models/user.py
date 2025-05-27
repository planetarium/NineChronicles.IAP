from sqlalchemy import Column, Index, Integer, LargeBinary, Text

from shared.enums import PlanetID
from shared.models.base import AutoIdMixin, Base, TimeStampMixin


class AvatarLevel(AutoIdMixin, TimeStampMixin, Base):
    """
    AvatarLevel is some sort of cache table checking required level.
    """

    __tablename__ = "avatar_level"
    agent_addr = Column(Text, nullable=False, doc="9c agent address where to get FAVs")
    avatar_addr = Column(
        Text, nullable=False, doc="9c avatar's address where to get items"
    )
    planet_id = Column(
        LargeBinary(length=12),
        nullable=False,
        default=PlanetID.ODIN.value,
        doc="An identifier of planets",
    )
    level = Column(Integer, nullable=False, doc="Cached max level of avatar")

    __table_args__ = (Index("idx_avatar_planet", avatar_addr, planet_id),)
