from dataclasses import dataclass
from typing import Union

from pydantic import BaseModel as BaseSchema

from common.utils.address import format_addr
from common.utils.receipt import PlanetID


@dataclass
class MileageRequestSchema(BaseSchema):
    agentAddress: str
    planetId: Union[str, PlanetID]

    def __post_init__(self):
        if self.agentAddress:
            self.agentAddress = format_addr(self.agentAddress)

        if isinstance(self.planetId, str):
            self.planetId = PlanetID(bytes(self.planetId, "utf-8"))


class MileageSchema(BaseSchema):
    id: int
    planet_id: PlanetID
    agent_addr: str
    mileage: int

    class Config:
        from_attributes = True
