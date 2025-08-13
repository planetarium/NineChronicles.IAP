from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Optional

import requests
import structlog
from shared.utils.google import get_google_client

import app
from app.config import config

logger = structlog.get_logger(__name__)


class VoidReason(IntEnum):
    Other = 0
    Remorse = 1
    Not_received = 2
    Defective = 3
    Accidental_purchase = 4
    Fraud = 5
    Friendly_fraud = 6
    Chargeback = 7
    Unacknowledged_purchase = 8


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
        self.purchaseTime = datetime.fromtimestamp(
            int(self.purchaseTimeMillis[:-3]), tz=timezone.utc
        )
        self.voidedTime = datetime.fromtimestamp(
            int(self.voidedTimeMillis[:-3]), tz=timezone.utc
        )
        self.voidedSource = VoidSource(self.voidedSource)
        self.voidedReason = VoidReason(self.voidedReason)


def send_slack_alert(message: str) -> None:
    if not config.iap_alert_webhook_url:
        logger.warning("iap_alert_webhook_url이 설정되지 않았습니다.")
        return

    try:
        payload = {"text": message}
        response = requests.post(config.iap_alert_webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack 알림이 성공적으로 전송되었습니다.")
    except Exception as e:
        logger.error(f"Slack 알림 전송 실패: {e}")


def handle(event, context):
    client = get_google_client(config.google_credential)
    current_time = datetime.now(timezone.utc)
    one_hour_ago = current_time - timedelta(hours=1)

    start_time_ms = int(one_hour_ago.timestamp() * 1000)
    end_time_ms = int(current_time.timestamp() * 1000)

    logger.info(f"환불 데이터 확인 시작 - {current_time.isoformat()}")
    logger.info(
        f"1시간 이내 환불 건만 조회 (시작: {one_hour_ago.isoformat()}, 종료: {current_time.isoformat()})"
    )

    for package_name, data in config.google_package_dict.items():
        logger.info(f"{package_name.value} 패키지의 환불 데이터를 확인합니다.")

        voided_list = (
            client.purchases()
            .voidedpurchases()
            .list(
                packageName=data, startTime=str(start_time_ms), endTime=str(end_time_ms)
            )
            .execute()
        )

        if not voided_list.get("voidedPurchases"):
            logger.info(
                f"{package_name.value} 패키지에서 최근 1시간 내 환불 건이 없습니다."
            )
            continue

        voided_purchases = [RefundData(**x) for x in voided_list["voidedPurchases"]]

        logger.info(
            f"{package_name.value} 패키지에서 최근 1시간 내 {len(voided_purchases)}개 환불 발견"
        )

        for void in voided_purchases:
            message = (
                f"🚨 Google Play 환불 알림\n"
                f"패키지: {package_name.value}\n"
                f"주문 ID: {void.orderId}\n"
                f"구매 시간: {void.purchaseTime.isoformat()}\n"
                f"환불 시간: {void.voidedTime.isoformat()}\n"
                f"환불 소스: {void.voidedSource.name}\n"
                f"환불 사유: {void.voidedReason.name}"
            )

            send_slack_alert(message)
            logger.info(
                f"환불 알림 전송: {void.orderId} (환불 시간: {void.voidedTime.isoformat()})"
            )

        logger.info(
            f"{package_name.value} 패키지에서 {len(voided_purchases)}개의 최근 환불 데이터를 처리했습니다."
        )


@app.task(
    name="iap.track_google_refund",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def track_google_refund(self):
    handle(self, None)


if __name__ == "__main__":
    handle(None, None)
