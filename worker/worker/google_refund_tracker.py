import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional

from common import logger
from common.utils.aws import fetch_parameter
from common.utils.google import get_google_client, Spreadsheet

GOOGLE_PACKAGE_NAME = os.environ.get("GOOGLE_PACKAGE_NAME")
GOOGLE_CREDENTIAL = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_GOOGLE_CREDENTIAL", True
)["Value"]
SHEET_ID = os.environ.get("REFUND_SHEET_ID")


class VoidReason(IntEnum):
    Other = 0
    Remorse = 1
    Not_received = 2
    Defective = 3
    Accidental_purchase = 4
    Fraud = 5
    Friendly_fraud = 6
    Chargeback = 7


class VoidSource(IntEnum):
    User = 0
    Developer = 1
    Google = 2


@dataclass
class RefundData:
    orderId: str
    purchaseTimeMillis: str
    voidedTimeMillis: str
    voidedSource: int | VoidSource
    voidedReason: int | VoidReason
    purchaseToken: str
    kind: str

    purchaseTime: Optional[datetime] = None
    voidedTime: Optional[datetime] = None

    def __post_init__(self):
        self.purchaseTime = datetime.fromtimestamp(int(self.purchaseTimeMillis[:-3]), tz=timezone.utc)
        self.voidedTime = datetime.fromtimestamp(int(self.voidedTimeMillis[:-3]), tz=timezone.utc)
        self.voidedSource = VoidSource(self.voidedSource)
        self.voidedReason = VoidReason(self.voidedReason)


def handle(event, context):
    client = get_google_client(GOOGLE_CREDENTIAL)
    sheet = Spreadsheet(GOOGLE_CREDENTIAL, SHEET_ID)
    prev_data = sheet.get_values("Google!A2:B").get("values", [])
    prev_order_id = set([x[1] for x in prev_data])
    last_num = int(prev_data[-1][0]) + 1 if prev_data else 1
    logger.info(f"{len(prev_data)} refunded data are present.")
    voided_list = client.purchases().voidedpurchases().list(packageName=GOOGLE_PACKAGE_NAME).execute()
    voided_list = sorted([RefundData(**x) for x in voided_list["voidedPurchases"]], key=lambda x: x.voidedTimeMillis)

    new_data = []
    index = last_num
    for void in voided_list:
        if void.orderId in prev_order_id:
            continue
        new_data.append(
            [index, void.orderId, void.purchaseTime.isoformat(), void.voidedTime.isoformat(), void.voidedSource.name,
             void.voidedReason.name])
        index += 1

    sheet.set_values(f"Google!A{last_num + 1}:F", new_data)
    logger.info(f"{len(new_data)} Refunds are added")


if __name__ == "__main__":
    handle(None, None)
