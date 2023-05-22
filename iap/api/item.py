from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select

from iap.dependencies import session
from iap.models.item import Item
from iap.schemas.item import ItemSchema

router = APIRouter(
    prefix="/item",
    tags=["Item"],
)


@router.get("", response_model=List[ItemSchema])
def item_list(sess=Depends(session)):
    items = sess.execute(select(Item)).scalars().fetchall()
    return items
