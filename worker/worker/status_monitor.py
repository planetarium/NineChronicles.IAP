import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List

import requests
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common._graphql import GQL
from common.consts import GQL_DICT
from common.enums import ReceiptStatus, TxStatus
from common.models.receipt import Receipt
from common.utils.aws import fetch_parameter, fetch_secrets
from common.utils.receipt import PlanetID

STAGE = os.environ.get("STAGE")
DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
PLANET_LIST = (PlanetID.ODIN, PlanetID.HEIMDALL, PlanetID.THOR) if STAGE == "mainnet" \
    else (PlanetID.ODIN_INTERNAL, PlanetID.HEIMDALL_INTERNAL, PlanetID.THOR_INTERNAL)
IAP_ALERT_WEBHOOK_URL = os.environ.get("IAP_ALERT_WEBHOOK_URL")
IAP_GARAGE_WEBHOOK_URL = os.environ.get("IAP_GARAGE_WEBHOOK_URL")
HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]

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
    invalid_list = sess.query(func.count(Receipt.id)).filter(
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=1)),
        Receipt.status.in_([ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.INVALID])
    ).scalar()

    msg = []
    msg.append(create_block(f"<@U03DRL8R1FE> <@UCKUGBH37>Non-Valid Receipt Report :: {invalid_list}"))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Non-Valid Receipt Report", msg)


def check_tx_failure(sess):
    """Notify all failed Tx"""
    tx_failed_receipt_list = sess.scalars(select(Receipt).where(Receipt.tx_status == TxStatus.FAILURE)).fetchall()

    msg = []
    if len(tx_failed_receipt_list) > 0:
        msg.append(create_block(f"<@U03DRL8R1FE> <@UCKUGBH37>"))
        for receipt in tx_failed_receipt_list:
          msg.append(create_block(
              f"ID {receipt.id} :: {receipt.uuid} :: {receipt.tx_status.name}\nTx. ID: {receipt.tx_id}"
          ))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Tx. Failed Receipt Report", msg)


def check_halt_tx(sess):
    """Notify when STAGED|INVALID tx over 5min."""
    tx_halt_receipt_list = sess.query(func.count(Receipt.id)).filter(
        Receipt.status == ReceiptStatus.VALID,
        Receipt.tx_status.in_([TxStatus.INVALID, TxStatus.STAGED]),
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=5)),
    ).scalar()

    msg = []
    msg.append(create_block(f"<@U03DRL8R1FE> <@UCKUGBH37> Tx. Invalid Receipt Report :: {tx_halt_receipt_list}"))
    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] Tx. Invalid Receipt Report", msg)


def check_no_tx(sess):
    """Notify when no Tx created purchase over 3min."""
    no_tx_receipt_list = sess.scalars(select(Receipt).where(
        Receipt.status == ReceiptStatus.VALID,
        Receipt.tx.is_(None),
        Receipt.created_at <= (datetime.now(tz=timezone.utc) - timedelta(minutes=3))
    )).fetchall()

    msg = []
    if len(no_tx_receipt_list) > 0:
        msg.append(create_block(f"<@U03DRL8R1FE> <@UCKUGBH37>"))
        for receipt in no_tx_receipt_list:
            msg.append(create_block(
                f"ID {receipt.id} :: {receipt.uuid}::Product {receipt.product_id}\n{receipt.agent_addr} :: {receipt.avatar_addr}"
            ))

    send_message(IAP_ALERT_WEBHOOK_URL, "[NineChronicles.IAP] No Tx. Create Receipt Report", msg)


def check_token_balance(planet: PlanetID):
    """Report IAP Garage stock"""
    url = GQL_DICT[planet]
    gql = GQL(url, jwt_secret=HEADLESS_GQL_JWT_SECRET)
    query = """
query balanceQuery(
  $address: Address! = "0xCb75C84D76A6f97A2d55882Aea4436674c288673"
) {
  stateQuery {
    BlackCat: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1001", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RedDongle: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1002", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Valkyrie: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1003", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    LilFenrir: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1004", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    ThorRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_GOLDENTHOR", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenMeat: balance (
      address: $address,
      currency: {ticker: "Item_NT_800202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    CriRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_CRI", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    EmeraldDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600203", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Crystal: balance (
      address: $address,
      currency: {ticker: "FAV__CRYSTAL", decimalPlaces: 18, minters: [], }
    ) { currency {ticker} quantity }
    hourglass: balance (
      address: $address,
      currency: {ticker: "Item_NT_400000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    APPotion: balance (
      address: $address,
      currency: {ticker: "Item_NT_500000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenLeafRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNE_GOLDENLEAF", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RubyDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    SilverDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_800201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
  }
}"""

    resp = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {gql.create_token()}"})
    data = resp.json()["data"]["stateQuery"]

    msg = []
    for name, balance in data.items():
        msg.append(create_block(f"*{name}* (`{balance['currency']['ticker']}`) : {int(balance['quantity']):,}"))

    send_message(
        IAP_GARAGE_WEBHOOK_URL,
        f"[NineChronicles.IAP] <@U03DRL8R1FE> <@UCKUGBH37> Daily Token Report :: {' '.join([x.capitalize() for x in planet.name.split('_')])}",
        msg
    )


def handle(event, context):
    sess = scoped_session(sessionmaker(bind=engine))
    if datetime.utcnow().hour == 3 and datetime.now().minute == 0:  # 12:00 KST
        for planet_id in PLANET_LIST:
            check_token_balance(planet_id)

    try:
        check_invalid_receipt(sess)
        check_halt_tx(sess)
        check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()


if __name__ == "__main__":
    sess = scoped_session(sessionmaker(bind=engine))
    for planet_id in PLANET_LIST:
        check_token_balance(planet_id)
    check_invalid_receipt(sess)
    check_halt_tx(sess)
    check_tx_failure(sess)
