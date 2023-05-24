from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from iap.dependencies import session
from common.models.box import Box, BoxItem
from iap.schemas.box import BoxSchema

router = APIRouter(
    prefix="/box",
    tags=["Box"],
)


@router.get("", summary="List of all boxes", response_model=List[BoxSchema])
def box_list(sess=Depends(session)):
    return sess.scalars(select(Box).options(joinedload(Box.item_list).joinedload(BoxItem.item))).unique().all()


@router.post("/pack", summary="Pack new box to sell.")
def pack():
    """
    Pack new box to sell.

    ### NOTICE

    This action is actually executed from the `ADMIN` address.
    """
    pass


@router.post("/transfer", summary="Transfer box from one address to another")
def transfer():
    """

    :return:
    """
