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
from common.utils.address import format_addr
from common.utils.receipt import PlanetID
from iap.schemas.product import SimpleProductSchema


class GooglePurchaseSchema(BaseSchema):
    # https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.products
    kind: str
    purchaseTimeMillis: str
    purchaseState: GooglePurchaseState
    consumptionState: GoogleConsumptionState
    developerPayload: str = ""
    orderId: str
    regionCode: str
    quantity: int = 1
    acknowledgementState: GoogleAckState
    purchaseToken: Optional[str] = None
    purchaseType: Optional[GooglePurchaseType] = None
    productId: Optional[str] = None
    obfuscatedExternalAccountId: Optional[str] = None
    obfuscatedExternalProfileId: Optional[str] = None


class ApplePurchaseSchema(BaseSchema):
    transactionId: str
    originalTransactionId: str
    bundleId: str
    productId: str
    purchaseDate: datetime
    originalPurchaseDate: datetime
    quantity: int
    type: str
    inAppOwnershipType: str
    signedDate: datetime
    environment: str
    transactionReason: str
    storefront: str
    storefrontId: str

    @property
    def json_data(self) -> dict:
        data = self.model_dump()
        data["purchaseDate"] = data["purchaseDate"].timestamp()
        data["originalPurchaseDate"] = data["originalPurchaseDate"].timestamp()
        data["signedDate"] = data["signedDate"].timestamp()
        return data


@dataclass
class FreeReceiptSchema:
    sku: str
    agentAddress: str
    avatarAddress: str
    store: Store
    planetId: Union[str, PlanetID]

    def __post_init__(self):
        # Reformat address to starts with `0x`
        if self.agentAddress:
            self.agentAddress = format_addr(self.agentAddress)
        if self.avatarAddress:
            self.avatarAddress = format_addr(self.avatarAddress)

        # Parse planet
        if isinstance(self.planetId, str):
            self.planetId = PlanetID(bytes(self.planetId, 'utf-8'))


@dataclass
class SimpleReceiptSchema:
    data: Union[str, Dict, object]
    store: Optional[Store] = None

    # Google
    payload: Optional[Dict] = None
    order: Optional[Dict] = None

    # Apple

    def __post_init__(self):
        # Parse purchase data to JSON
        if isinstance(self.data, str):
            self.data = json.loads(self.data)

        if not self.store:
            if "AppleAppStore" in self.data.get("Store", ""):
                self.store = Store.APPLE
            elif "GooglePlay" in self.data.get("Store", ""):
                self.store = Store.GOOGLE
            else:
                self.store = Store.TEST

        if self.store in (Store.GOOGLE, Store.GOOGLE_TEST):
            self.payload = json.loads(self.data["Payload"])
            self.order = json.loads(self.payload["json"])
        elif self.store in (Store.APPLE, Store.APPLE_TEST):
            pass
        elif self.store == Store.TEST:
            # No further action
            pass


@dataclass
class ReceiptSchema(SimpleReceiptSchema):
    agentAddress: Optional[str] = None
    avatarAddress: Optional[str] = None
    planetId: Union[str, PlanetID] = None

    def __post_init__(self):
        super().__post_init__()

        # Reformat address to starts with `0x`
        if self.agentAddress:
            self.agentAddress = format_addr(self.agentAddress)
        if self.avatarAddress:
            self.avatarAddress = format_addr(self.avatarAddress)

        if isinstance(self.planetId, str):
            self.planetId = PlanetID(bytes(self.planetId, 'utf-8'))


class FullReceiptSchema(BaseSchema):
    store: Store
    uuid: UUID
    order_id: str
    product: Optional[SimpleProductSchema] = None
    agent_addr: str
    avatar_addr: str
    status: ReceiptStatus
    tx_id: Optional[str] = None
    tx_status: Optional[TxStatus] = None
    purchased_at: datetime
    updated_at: datetime
    planet_id: PlanetID

    class Config:
        from_attributes = True


class ReceiptDetailSchema(BaseSchema):
    store: Store
    uuid: UUID
    order_id: str
    status: ReceiptStatus
    tx_id: Optional[str] = None
    tx_status: Optional[TxStatus] = None
    planet_id: PlanetID

    class Config:
        from_attributes = True


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
    planet_id: PlanetID

    class Config:
        from_attributes = True
