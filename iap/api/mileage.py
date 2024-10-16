from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.models.mileage import Mileage
from common.utils.receipt import PlanetID
from iap.dependencies import session
from iap.schemas.mileage import MileageSchema

router = APIRouter(
    prefix="/mileage",
    tags=["Mileage"],
)


@router.get("", response_model=MileageSchema)
def get_mileage(agent_addr: str, planet_id: str, sess: Session = Depends(session)):
    planet = PlanetID(bytes(planet_id, "utf-8"))
    mileage = sess.scalar(
        select(Mileage)
        .where(Mileage.agent_addr == agent_addr, Mileage.planet_id == planet)
    )
    if mileage is None:
        # Create new mileage info if not exists
        mileage = Mileage(planet_id=planet, agent_addr=agent_addr, mileage=0)
        sess.add(mileage)
        sess.commit()
    return mileage
