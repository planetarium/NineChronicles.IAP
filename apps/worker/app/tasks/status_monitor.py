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


# 멈춘 영수증을 "새로 막힌 것"과 "오래 박힌 것"으로 가르는 경계.
#   이 나이를 넘긴 건은 재시도로 풀릴 가능성이 사실상 없고 수동 개입 대상이라,
#   10분마다 같은 숫자를 다시 쏘는 대신 하루 한 번 묶어서 보고한다.
STUCK_STALE_AFTER = timedelta(hours=6)
# 5분은 "아직 확정 안 됨"과 구분하기 위한 최소 나이다(기존 동작 유지).
STUCK_MIN_AGE = timedelta(minutes=5)


def _stuck_tx_stats(sess, now: datetime):
    """
    VALID 인데 tx 가 INVALID/STAGED 로 멈춘 영수증을 나이로 갈라 센다.

    한 번의 쿼리로 (최근, 오래된, 가장 오래된 시각) 을 같이 얻는다. 셋을 따로 세면
    그 사이에 트래커가 상태를 바꿔 숫자끼리 안 맞는 보고가 나간다.
    """
    return (
        sess.query(
            func.count(Receipt.id).filter(Receipt.created_at > now - STUCK_STALE_AFTER),
            func.count(Receipt.id).filter(
                Receipt.created_at <= now - STUCK_STALE_AFTER
            ),
            func.min(Receipt.created_at),
        )
        .filter(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_([TxStatus.INVALID, TxStatus.STAGED]),
            Receipt.created_at <= now - STUCK_MIN_AGE,
        )
        .one()
    )


def check_halt_tx(sess):
    """Notify when STAGED|INVALID tx over 5min."""
    now = datetime.now(tz=timezone.utc)
    recent, stale, oldest = _stuck_tx_stats(sess, now)

    if not recent:
        # 오래 박힌 건만 남은 상태. 여기서 쏘면 그 건이 수동 처리될 때까지
        #   10분마다 영구 재발화한다(2026-09-28 알람 폭주가 이 모양이었다).
        #   대신 아래 report_stale_halt_tx() 가 하루 한 번 보고한다.
        if stale:
            logger.info("stale stuck receipts only — 일일 보고로 넘김", stale=stale)
        return

    # ⚠️ 여기서 막는 건 "오래된 건의 영구 반복"까지다. 같은 건이 풀릴 때까지
    #   10분마다 반복되는 것 자체는 이 함수로는 못 막는다(발화 이력을 들고 있지 않다).
    #   반복 억제와 해소(resolved) 알림은 Grafana 알림 규칙 쪽에서 붙인다.
    detail = f"최근 {recent}건"
    if stale:
        detail += f" (+ 6시간 이상 박힌 {stale}건)"
    if oldest is not None:
        detail += f", 최장 {int((now - oldest).total_seconds() // 60)}분"

    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] Tx. Invalid Receipt Report",
        [
            create_block(
                f"<@U03DRL8R1FE> <@UCKUGBH37> Tx. Invalid Receipt Report :: {recent + stale}\n{detail}"
            )
        ],
    )


def report_stale_halt_tx(sess):
    """하루 한 번, 수동 개입이 필요한 장기 정체 건을 보고한다."""
    now = datetime.now(tz=timezone.utc)
    _, stale, oldest = _stuck_tx_stats(sess, now)
    if not stale:
        return

    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] Stale Tx. Receipt Digest",
        [
            create_block(
                f"6시간 이상 tx 가 INVALID/STAGED 로 멈춘 영수증 {stale}건 "
                f"(최장 {int((now - oldest).total_seconds() // 3600)}시간). 수동 확인이 필요합니다."
            )
        ],
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
        daily_slot = (
            datetime.utcnow().hour == 3 and datetime.now().minute == 0
        )  # 12:00 KST
        if daily_slot:
            for planet_id in config.converted_gql_url_map.keys():
                # Token balance report should exclude Thor network.
                if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
                    continue
                check_token_balance(planet_id)
            # 장기 정체 건은 check_halt_tx 가 매 회차 쏘지 않으므로 여기서 하루 한 번 본다.
            report_stale_halt_tx(sess)

        check_halt_tx(sess)
        # check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()
            logger.debug("status_monitor session closed successfully")
