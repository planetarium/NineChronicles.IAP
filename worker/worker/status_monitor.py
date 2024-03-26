import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common._graphql import GQL
from common.enums import ReceiptStatus, TxStatus
from common.models.receipt import Receipt
from common.utils.aws import fetch_secrets
from common.utils.receipt import PlanetID

STAGE = os.environ.get("STAGE")
DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
CURRENT_PLANET = PlanetID.ODIN if os.environ.get("STAGE") == "mainnet" else PlanetID.ODIN_INTERNAL
GQL_URL = f"{os.environ.get('HEADLESS')}/graphql"
IAP_ALERT_WEBHOOK_URL = os.environ.get("IAP_ALERT_WEBHOOK_URL")
IAP_GARAGE_WEBHOOK_URL = os.environ.get("IAP_GARAGE_WEBHOOK_URL")

FUNGIBLE_DICT = {
    "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a": "Hourglass (400000)",
    "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe": "AP Potion (500000)",
    "1a755098a2bc0659a063107df62e2ff9b3cdaba34d96b79519f504b996f53820": "Silver Dust (800201)",
    "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0": "Golden Dust (600201)",
    "48e50ecd6d1aa2689fd349c1f0611e6cc1e9c4c74ec4de9d4637ec7b78617308": "Golden Meat (800202)",
    "08f566bb43570aad34c1790901f824dd5609db880afebd5382fcec054203d92a": "Ruby Dust (600202)"
}

VIEW_ORDER = (
    "CRYSTAL",
    FUNGIBLE_DICT["3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a"],  # Hourglass
    FUNGIBLE_DICT["00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe"],  # AP Potion
    "RUNE_GOLDENLEAF",
    FUNGIBLE_DICT["f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"],  # Golden Dust
    FUNGIBLE_DICT["08f566bb43570aad34c1790901f824dd5609db880afebd5382fcec054203d92a"],  # Ruby Dust
    FUNGIBLE_DICT["48e50ecd6d1aa2689fd349c1f0611e6cc1e9c4c74ec4de9d4637ec7b78617308"],  # Golden Meat
    FUNGIBLE_DICT["1a755098a2bc0659a063107df62e2ff9b3cdaba34d96b79519f504b996f53820"],  # Silver Dust
    "SOULSTONE_1001", "SOULSTONE_1002", "SOULSTONE_1003", "SOULSTONE_1004",
)

engine = create_engine(DB_URI)


def send_message(url: str, title: str, blocks: List):
    if not blocks:
        logger.info(f"{title} :: No blocks to send.")
        return

    message = {
        "blocks": [{
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": title,
                "emoji": True
            }
        }],
        "attachments": [{"blocks": blocks}]
    }
    resp = requests.post(url, json=message)
    logger.info(f"{title} :: Sent {len(blocks)} :: {resp.status_code} :: {resp.text}")


def create_block(text: str) -> Dict:
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": text
        }
    }


def check_invalid_receipt(sess):
    """Notify all invalid receipt"""
    invalid_list = sess.scalars(select(Receipt).where(
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=1)),
        Receipt.status.in_([ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.INVALID])
    )).fetchall()

    msg = []
    for invalid in invalid_list:
        msg.append(create_block(f"ID {invalid.id} :: {invalid.uuid} :: {invalid.status.name}"))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Non-Valid Receipt Report", msg)


def check_tx_failure(sess):
    """Notify all failed Tx"""
    tx_failed_receipt_list = sess.scalars(select(Receipt).where(Receipt.tx_status == TxStatus.FAILURE)).fetchall()

    msg = []
    for receipt in tx_failed_receipt_list:
        msg.append(create_block(
            f"ID {receipt.id} :: {receipt.uuid} :: {receipt.tx_status.name}\nTx. ID: {receipt.tx_id}"
        ))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Tx. Failed Receipt Report", msg)


def check_halt_tx(sess):
    """Notify when STAGED|INVALID tx over 5min."""
    tx_halt_receipt_list = sess.scalars(select(Receipt).where(
        Receipt.tx_status.in_([TxStatus.INVALID, TxStatus.STAGED]),
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=5)),
    )).fetchall()

    msg = []
    for receipt in tx_halt_receipt_list:
        msg.append(create_block(f"ID {receipt.id} :: {receipt.uuid}\n{receipt.tx_id}"))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Tx. Invalid Receipt Report", msg)


def check_no_tx(sess):
    """Notify when no Tx created purchase over 3min."""
    no_tx_receipt_list = sess.scalars(select(Receipt).where(
        Receipt.status == ReceiptStatus.VALID,
        Receipt.tx.is_(None),
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=3))
    )).fetchall()

    msg = []
    for receipt in no_tx_receipt_list:
        msg.append(create_block(
            f"ID {receipt.id} :: {receipt.uuid}::Product {receipt.product_id}\n{receipt.agent_addr} :: {receipt.avatar_addr}"
        ))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] No Tx. Create Receipt Report", msg)


def check_garage():
    """Report IAP Garage stock"""
    query = """{
      stateQuery {
        garages(
          agentAddr: "0xCb75C84D76A6f97A2d55882Aea4436674c288673",
          currencyTickers: [
            "CRYSTAL", "RUNE_GOLDENLEAF",
            "SOULSTONE_1001", "SOULSTONE_1002", "SOULSTONE_1003", "SOULSTONE_1004",
          ]
          fungibleItemIds: [
            "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a",  # Hourglass (400000)
            "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe",  # AP Potion (500000)
            "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"   # Golden Dust (600201)
            "08f566bb43570aad34c1790901f824dd5609db880afebd5382fcec054203d92a",  # Ruby Dust (600202)
            "48e50ecd6d1aa2689fd349c1f0611e6cc1e9c4c74ec4de9d4637ec7b78617308",  # Golden Meat (800202)
            "1a755098a2bc0659a063107df62e2ff9b3cdaba34d96b79519f504b996f53820",  # Silver Dust (800201)
          ]
        ) {
          garageBalances { currency { ticker minters decimalPlaces } quantity }
          fungibleItemGarages { fungibleItemId item {itemSubType} count }
        }
      }
    }"""

    resp = requests.post(GQL_URL, json={"query": query}, headers={"Authorization": f"Bearer {GQL.create_token()}"})
    data = resp.json()["data"]["stateQuery"]["garages"]
    fav_data = data["garageBalances"]
    item_data = data["fungibleItemGarages"]

    result_dict = {}

    for fav in fav_data:
        result_dict[fav["currency"]["ticker"]] = fav["quantity"].split(".")[0]
    for item in item_data:
        result_dict[FUNGIBLE_DICT[item["fungibleItemId"]]] = item["count"]

    msg = []
    for key in VIEW_ORDER:
        result = result_dict.pop(key)
        msg.append(create_block(f"{key} : {int(result):,}"))
    for key, result in result_dict.items():
        msg.append(create_block(f"{key} : {int(result):,}"))

    send_message(IAP_GARAGE_WEBHOOK_URL, f"[NineChronicles.IAP] Daily Garage Report - {STAGE}", msg)


def handle(event, context):
    sess = scoped_session(sessionmaker(bind=engine))
    if datetime.utcnow().hour == 3 and datetime.now().minute == 0:  # 12:00 KST
        check_garage()

    try:
        check_invalid_receipt(sess)
        check_halt_tx(sess)
        check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()


if __name__ == "__main__":
    sess = scoped_session(sessionmaker(bind=engine))
    check_garage()
    check_invalid_receipt(sess)
    check_halt_tx(sess)
    check_tx_failure(sess)
