from typing import List, Optional

from pydantic import BaseModel as Schema, validator

from common.models import BoxStatus
from iap.schemas.item import ItemSchema


class BoxItemSchema(Schema):
    item: ItemSchema
    count: int

    class Config:
        orm_mode = True


class BoxSchema(Schema):
    id: int
    name: str
    item_list: List[BoxItemSchema] = []
    price: float
    status: BoxStatus

    class Config:
        orm_mode = True


class TransferItemSchema(Schema):
    item_id: int
    amount: int

    @validator("amount")
    def amount_must_be_positive(cls, v):
        if v < 1:
            raise ValueError("Item amount to transfer must be positive.")
        return v


class BoxTransferSchema(Schema):
    sender: Optional[str]
    recipient: str
    transfer_list: List[TransferItemSchema]
