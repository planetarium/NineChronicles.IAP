
from fastapi import APIRouter, Depends
from shared.enums import PlanetID
from shared.schemas.mileage import MileageSchema
from sqlalchemy.orm import Session

from app.dependencies import session
from app.utils import get_mileage as get_mileage_fn

router = APIRouter(
    prefix="/mileage",
    tags=["Mileage"],
)


@router.get("", response_model=MileageSchema)
def get_mileage(agent_addr: str, planet_id: str, sess: Session = Depends(session)):
    mileage = get_mileage_fn(sess, agent_addr)
    schema = MileageSchema(**mileage.__dict__, planet_id=PlanetID(bytes(planet_id, "utf-8")))
    return schema