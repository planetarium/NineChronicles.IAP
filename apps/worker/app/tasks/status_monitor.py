import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
import structlog
from shared._graphql import GQL
from shared.enums import PlanetID, ReceiptStatus, Store, TxStatus
from shared.models.product import Price
from shared.models.receipt import Receipt
from shared.utils.balance import BALANCE_QUERY
from sqlalchemy import Date, create_engine, func, select, and_, cast
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


def create_divider_block() -> Dict:
    """Create a divider block for Slack Block Kit"""
    return {"type": "divider"}


def check_monthly_sales(sess):
    """Report monthly sales by date and store type"""
    if not config.iap_sales_webhook_url:
        logger.warning("iap_sales_webhook_url이 설정되지 않았습니다.")
        return

    # 현재 월의 시작일과 종료일 계산 (UTC 기준)
    now = datetime.now(tz=timezone.utc)
    year = now.year
    month = now.month

    # 해당 월의 시작일
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    # 다음 달의 시작일 (해당 월의 종료일)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    # INTERNAL planet ID 리스트 (제외할 planet들)
    internal_planet_ids = [
        PlanetID.ODIN_INTERNAL.value,
        PlanetID.HEIMDALL_INTERNAL.value,
        PlanetID.IDUN_INTERNAL.value,
        PlanetID.THOR_INTERNAL.value,
    ]

    # created_at 기준으로 날짜 추출
    date_column = cast(
        Receipt.created_at,
        Date
    )

    # Receipt와 Product, Price를 조인하여 VALID 상태인 receipt만 조회
    # INTERNAL planet은 제외
    query = (
        sess.query(
            date_column.label("sale_date"),
            Receipt.store,
            func.sum(Price.price).label("total_sales")
        )
        .join(Receipt.product)
        .join(Price, Price.product_id == Receipt.product_id)
        .filter(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.created_at >= month_start,
            Receipt.created_at < month_end,
            ~Receipt.planet_id.in_(internal_planet_ids)  # INTERNAL planet 제외
        )
        .group_by(date_column, Receipt.store)
        .order_by(date_column.desc(), Receipt.store)
    )

    results = query.all()

    # 데이터 구조화: {날짜: {store: 매출}}
    sales_by_date = {}
    store_totals = {Store.APPLE: 0, Store.GOOGLE: 0, Store.WEB: 0}

    for result in results:
        sale_date = result.sale_date
        store = result.store
        total_sales = float(result.total_sales) if result.total_sales else 0.0

        if sale_date not in sales_by_date:
            sales_by_date[sale_date] = {
                Store.APPLE: 0.0,
                Store.GOOGLE: 0.0,
                Store.WEB: 0.0,
                "total": 0.0
            }

        # 프로덕션 스토어만 집계 (TEST 스토어 제외)
        if store in [Store.APPLE, Store.GOOGLE, Store.WEB]:
            sales_by_date[sale_date][store] = total_sales
            sales_by_date[sale_date]["total"] += total_sales
            store_totals[store] += total_sales

    # 슬랙 Block Kit 포맷으로 메시지 생성
    blocks = []

    # 헤더 행
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*날짜* | *총매출* | *APPLE* | *GOOGLE* | *WEB*"
        }
    })

    # 구분선
    blocks.append(create_divider_block())

    # 날짜별 데이터
    for sale_date in sorted(sales_by_date.keys(), reverse=True):
        date_data = sales_by_date[sale_date]
        date_str = sale_date.strftime("%Y-%m-%d")

        total = date_data["total"]
        apple = date_data.get(Store.APPLE, 0.0)
        google = date_data.get(Store.GOOGLE, 0.0)
        web = date_data.get(Store.WEB, 0.0)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{date_str} | ${total:,.2f} | ${apple:,.2f} | ${google:,.2f} | ${web:,.2f}"
            }
        })

    # 구분선
    blocks.append(create_divider_block())

    # 합계 행
    grand_total = sum(store_totals.values())
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*합계* | *${grand_total:,.2f}* | *${store_totals[Store.APPLE]:,.2f}* | *${store_totals[Store.GOOGLE]:,.2f}* | *${store_totals[Store.WEB]:,.2f}*"
        }
    })

    # 슬랙에 전송
    send_message(
        config.iap_sales_webhook_url,
        f"[NineChronicles.IAP] Daily Sales Report :: {month}월",
        blocks,
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
                check_token_balance(planet_id)

        check_halt_tx(sess)
        # check_tx_failure(sess)
    finally:
        if sess is not None:
            sess.close()
            logger.debug("status_monitor session closed successfully")


@app.task(
    name="iap.daily_sales_report",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def daily_sales_report(self):
    """Send daily sales report to Slack at 10:00 AM KST (01:00 AM UTC)"""
    sess = scoped_session(sessionmaker(bind=engine))

    try:
        check_monthly_sales(sess)
    except Exception as e:
        logger.error(f"Daily sales report failed: {e}", exc_info=True)
        raise
    finally:
        if sess is not None:
            sess.close()
            logger.debug("daily_sales_report session closed successfully")
