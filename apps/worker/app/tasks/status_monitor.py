import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
import structlog
from shared._graphql import GQL
from shared.enums import PlanetID, ReceiptStatus, TxStatus
from shared.models.receipt import Receipt
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(config.pg_dsn, pool_size=5, max_overflow=5)


def send_message(url: str, title: str, blocks: List):
    if not blocks:
        logger.info(f"{title} :: No blocks to send.")
        return

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            }
        ],
        "attachments": [{"blocks": blocks}],
    }
    resp = requests.post(url, json=message)
    logger.info(f"{title} :: Sent {len(blocks)} :: {resp.status_code} :: {resp.text}")


def create_block(text: str) -> Dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def check_invalid_receipt(sess):
    """Notify all invalid receipt"""
    invalid_list = (
        sess.query(func.count(Receipt.id))
        .filter(
            Receipt.created_at
            <= (datetime.now(tz=timezone.utc) - timedelta(minutes=1)),
            Receipt.status.in_(
                [
                    ReceiptStatus.INIT,
                    ReceiptStatus.VALIDATION_REQUEST,
                    ReceiptStatus.INVALID,
                ]
            ),
        )
        .scalar()
    )

    msg = []
    msg.append(create_block(f"Non-Valid Receipt Report :: {invalid_list}"))

    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] Non-Valid Receipt Report",
        msg,
    )


def check_tx_failure(sess):
    """Notify all failed Tx"""
    tx_failed_receipt_list = sess.scalars(
        select(Receipt).where(Receipt.tx_status == TxStatus.FAILURE)
    ).fetchall()

    msg = []
    if len(tx_failed_receipt_list) > 0:
        for receipt in tx_failed_receipt_list:
            msg.append(
                create_block(
                    f"ID {receipt.id} :: {receipt.uuid} :: {receipt.tx_status.name}\nTx. ID: {receipt.tx_id}"
                )
            )

    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] Tx. Failed Receipt Report",
        msg,
    )


def check_halt_tx(sess):
    """Notify when STAGED|INVALID tx over 5min."""
    tx_halt_receipt_list = (
        sess.query(func.count(Receipt.id))
        .filter(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_([TxStatus.INVALID, TxStatus.STAGED]),
            Receipt.created_at
            <= (datetime.now(tz=timezone.utc) - timedelta(minutes=5)),
        )
        .scalar()
    )

    msg = []
    if tx_halt_receipt_list > 0:
        msg.append(
            create_block(
                f"<@U03DRL8R1FE> <@UCKUGBH37> Tx. Invalid Receipt Report :: {tx_halt_receipt_list}"
            )
        )
        send_message(
            config.iap_alert_webhook_url,
            "[NineChronicles.IAP] Tx. Invalid Receipt Report",
            msg,
        )


def check_no_tx(sess):
    """Notify when no Tx created purchase over 3min."""
    no_tx_receipt_list = sess.scalars(
        select(Receipt).where(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx.is_(None),
            Receipt.created_at
            <= (datetime.now(tz=timezone.utc) - timedelta(minutes=3)),
        )
    ).fetchall()

    msg = []
    if len(no_tx_receipt_list) > 0:
        msg.append(create_block("<@U03DRL8R1FE> <@UCKUGBH37>"))
        for receipt in no_tx_receipt_list:
            msg.append(
                create_block(
                    f"ID {receipt.id} :: {receipt.uuid}::Product {receipt.product_id}\n{receipt.agent_addr} :: {receipt.avatar_addr}"
                )
            )

    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] No Tx. Create Receipt Report",
        msg,
    )


def check_token_balance(planet: PlanetID):
    """Report IAP Garage stock"""
    url = config.converted_gql_url_map[planet]
    gql = GQL(url, jwt_secret=config.headless_jwt_secret)
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

    resp = requests.post(
        url,
        json={"query": query},
        headers={"Authorization": f"Bearer {gql.create_token()}"},
    )
    data = resp.json()["data"]["stateQuery"]

    msg = []
    for name, balance in data.items():
        msg.append(
            create_block(
                f"*{name}* (`{balance['currency']['ticker']}`) : {int(balance['quantity']):,}"
            )
        )

    send_message(
        config.iap_garage_webhook_url,
        f"[NineChronicles.IAP] Daily Token Report :: {' '.join([x.capitalize() for x in planet.name.split('_')])}",
        msg,
    )


@app.task(
    name="iap.status_monitor",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def status_monitor(self):
    sess = scoped_session(sessionmaker(bind=engine))
    if datetime.utcnow().hour == 3 and datetime.now().minute == 0:  # 12:00 KST
        for planet_id in config.converted_gql_url_map.keys():
            check_token_balance(planet_id)

    try:
        check_halt_tx(sess)
        check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()
