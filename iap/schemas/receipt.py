import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union, Dict
from uuid import UUID

from pydantic import BaseModel as BaseSchema

from common.enums import (
    ReceiptStatus, Store, TxStatus,
    GooglePurchaseState, GoogleConsumptionState, GooglePurchaseType, GoogleAckState,
)
from common.utils import format_addr


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


@dataclass
class ReceiptSchema:
    store: Store
    data: Union[str, Dict, object]
    agentAddress: str
    avatarAddress: str

    # Google
    payload: Optional[Dict] = None
    order: Optional[Dict] = None

    # Apple

    def __post_init__(self):
        # Parse purchase data to JSON
        if type(self.data) == str:
            self.data = json.loads(self.data)

        if self.store in (Store.GOOGLE, Store.GOOGLE_TEST):
            self.payload = json.loads(self.data["Payload"])
            self.order = json.loads(self.payload["json"])
        elif self.store in (Store.APPLE, Store.APPLE_TEST):
            # TODO: Support Apple
            pass
        elif self.store == Store.TEST:
            # No further action
            pass

        # Reformat address to starts with `0x`
        self.agentAddress = format_addr(self.agentAddress)
        self.avatarAddress = format_addr(self.avatarAddress)


class ReceiptDetailSchema(BaseSchema):
    store: Store
    uuid: UUID
    order_id: str
    status: ReceiptStatus
    tx_id: Optional[str] = None
    tx_status: Optional[TxStatus] = None

    class Config:
        orm_mode = True


class RefundedReceiptSchema(BaseSchema):
    store: Store
    uuid: UUID
    order_id: str
    status: ReceiptStatus
    tx_id: Optional[str] = None
    tx_status: Optional[TxStatus] = None
    agent_addr: Optional[str] = None
    purchased_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
