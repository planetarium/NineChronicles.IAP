from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
import structlog
from shared._graphql import GQL
from shared.enums import PlanetID, ReceiptStatus, TxStatus
from shared.models.receipt import Receipt
from shared.utils.balance import BALANCE_QUERY
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(
    config.pg_dsn,
    pool_size=10,  # 기본 연결 수 증가
    max_overflow=20,  # 오버플로우 연결 수 증가
    pool_timeout=60,  # 연결 타임아웃 증가
    pool_recycle=3600,  # 연결 재사용 시간 (1시간)
    pool_pre_ping=True  # 연결 상태 확인
)


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

    resp = requests.post(
        url,
        json={"query": BALANCE_QUERY},
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

    try:
        if datetime.utcnow().hour == 3 and datetime.now().minute == 0:  # 12:00 KST
            for planet_id in config.converted_gql_url_map.keys():
                # Token balance report should exclude Thor network.
                if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
                    continue
                check_token_balance(planet_id)

        check_halt_tx(sess)
        # check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()
            logger.debug("status_monitor session closed successfully")
