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
    # 알람 경로가 무한 대기하면 이 PR 이 고치는 것과 같은 유형의 사고가 된다.
    resp = requests.post(url, json=message, timeout=10)
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

    한 번의 쿼리로 (최근, 오래된, 전체 최고령, 최근 최고령) 을 같이 얻는다. 따로 세면
    그 사이에 트래커가 상태를 바꿔 숫자끼리 안 맞는 보고가 나간다.
    """
    return (
        sess.query(
            func.count(Receipt.id).filter(Receipt.created_at > now - STUCK_STALE_AFTER),
            func.count(Receipt.id).filter(
                Receipt.created_at <= now - STUCK_STALE_AFTER
            ),
            func.min(Receipt.created_at),
            # recent 버킷만의 최고령. 전역 min 은 3일 묵은 한 건이 있으면 계속 그 값이라
            #   "지금 막 막힌 게 얼마나 됐나"를 못 알려준다.
            func.min(Receipt.created_at).filter(
                Receipt.created_at > now - STUCK_STALE_AFTER
            ),
        )
        .filter(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_([TxStatus.INVALID, TxStatus.STAGED]),
            Receipt.created_at <= now - STUCK_MIN_AGE,
        )
        .one()
    )


def _stale_hours() -> int:
    """메시지에 쓰는 경계 시간. 상수와 따로 놀면 메시지가 거짓말을 한다."""
    return int(STUCK_STALE_AFTER.total_seconds() // 3600)


def check_halt_tx(sess):
    """Notify when STAGED|INVALID tx over 5min."""
    now = datetime.now(tz=timezone.utc)
    recent, stale, oldest, recent_oldest = _stuck_tx_stats(sess, now)

    if not recent:
        # 오래 박힌 건만 남은 상태. 여기서 쏘면 그 건이 수동 처리될 때까지
        #   10분마다 영구 재발화한다(2026-09-28 알람 폭주가 이 모양이었다).
        #   대신 아래 report_stale_halt_tx() 가 하루 한 번 보고한다.
        if stale:
            logger.info("stale stuck receipts only — 일일 보고로 넘김", stale=stale)
        return

    # ⚠️ 여기서 막는 건 "오래된 건의 영구 반복"까지다. 같은 건이 풀릴 때까지
    #   10분마다 반복되는 것 자체는 이 함수로는 못 막는다(발화 이력을 들고 있지 않다).
    #   이 메시지는 Slack incoming webhook 으로 직행하므로 dedup·resolved 가 없다 —
    #   그건 Grafana 알림 규칙으로 옮겨야 붙는다(아직 미구현).
    detail = f"최근 {recent}건"
    if recent_oldest is not None:
        detail += f", 최장 {int((now - recent_oldest).total_seconds() // 60)}분"
    if stale:
        stale_min = int((now - oldest).total_seconds() // 60) if oldest else 0
        detail += (
            f" / {_stale_hours()}시간 이상 박힌 {stale}건(최장 {stale_min // 60}시간)"
        )

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
    _, stale, oldest, _ = _stuck_tx_stats(sess, now)
    if not stale:
        return

    # 멘션을 단다. 반복 알람에서 넘겨받은 "수동 확인" 책임이 이 하루 한 번짜리에 있는데
    #   조용하기까지 하면 아무도 안 본다.
    send_message(
        config.iap_alert_webhook_url,
        "[NineChronicles.IAP] Stale Tx. Receipt Digest",
        [
            create_block(
                f"<@U03DRL8R1FE> <@UCKUGBH37> {_stale_hours()}시간 이상 tx 가 "
                f"INVALID/STAGED 로 멈춘 영수증 {stale}건 "
                f"(최장 {int((now - oldest).total_seconds() // 3600)}시간). 수동 확인이 필요합니다."
            )
        ],
    )


def is_daily_slot(now: datetime) -> bool:
    """
    하루 1회 보고 슬롯(12:00 KST)인가.

    이 태스크가 10분 간격이라 minute < 10 이어도 하루 한 번이 유지된다. minute == 0 으로
    좁히면 정각에 due 가 몰려(track_tx·retryer·voucher_* 동시) 워커가 60초만 밀려도 그날
    슬롯이 통째로 사라진다 — 그 슬롯이 장기 정체를 보고하는 유일한 경로라 실패 방향이
    '침묵' 이 된다. 그래서 함수로 빼 테스트로 고정한다.
    """
    return now.hour == 3 and now.minute < 10


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
        if is_daily_slot(datetime.now(tz=timezone.utc)):
            # ⚠️ GQL 루프보다 **먼저** 부른다. check_token_balance 는 timeout 없는
            #   requests.post 라, 한 번 흔들리면 예외가 올라가 이 회차가 통째로 날아간다.
            report_stale_halt_tx(sess)
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
