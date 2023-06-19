from typing import Optional

from pydantic import BaseModel as BaseSchema

from common.enums import ReceiptStatus, Store, TxStatus


class ReceiptSchema(BaseSchema):
    store: Store
    data: str
    # agentAddress: str  # Reserve for FAV
    inventoryAddress: str

    class Config:
        orm_mode = True


class PurchaseProcessResultSchema(BaseSchema):
    store: Store
    uuid: str
    status: ReceiptStatus

    class Config:
        orm_mode = True


class ReceiptDetailSchema(BaseSchema):
    store: Store
    uuid: str
    status: ReceiptStatus
    tx_id: Optional[str]
    tx_status: Optional[TxStatus]
