from typing import Optional
from uuid import UUID

from pydantic import BaseModel as BaseSchema

from common.enums import (ReceiptStatus, Store, TxStatus, GooglePurchaseState, GoogleConsumptionState,
                          GooglePurchaseType, GoogleAckState, )


class GooglePurchaseSchema(BaseSchema):
    # https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.products
    kind: str
    purchaseTimeMillis: str
    purchaseState: GooglePurchaseState
    consumptionState: GoogleConsumptionState
    developerPayload: str = ""
    orderId: str
    purchaseType: Optional[GooglePurchaseType]
    acknowledgementState: GoogleAckState
    purchaseToken: Optional[str]
    productId: Optional[str]
    quantity: int = 1
    obfuscatedExternalAccountId: Optional[str]
    obfuscatedExternalProfileId: Optional[str]
    regionCode: str


class ReceiptSchema(BaseSchema):
    store: Store
    data: str
    agentAddress: str
    inventoryAddress: str

    class Config:
        orm_mode = True


class ReceiptDetailSchema(BaseSchema):
    store: Store
    uuid: UUID
    order_id: str
    status: ReceiptStatus
    tx_id: Optional[str] = None
    tx_status: Optional[TxStatus] = None

    class Config:
        orm_mode = True
