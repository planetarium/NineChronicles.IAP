from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from common.utils.receipt import PlanetID
from iap.dependencies import session
from iap.schemas.mileage import MileageSchema
from iap.utils import get_mileage as get_mileage_fn

router = APIRouter(
    prefix="/mileage",
    tags=["Mileage"],
)


@router.get("", response_model=MileageSchema)
def get_mileage(agent_addr: str, planet_id: str, sess: Session = Depends(session)):
    mileage = get_mileage_fn(sess, agent_addr)
    schema = MileageSchema(**mileage.__dict__, planet_id=PlanetID(bytes(planet_id, "utf-8")))
    return schema
