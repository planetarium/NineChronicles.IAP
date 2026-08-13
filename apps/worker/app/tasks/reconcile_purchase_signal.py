"""결제는 성립했는데 영수증이 안 생긴 건을 사후에 메운다.

배경: 클라이언트는 결제 성공 직후 `/api/purchase/log`로 결제 성공을 알리고
(→ `purchase_signal`), 이어서 `/api/purchase/request`를 보내 검증·ack·지급을
받는다. 두 번째 호출이 유실되면 영수증이 아예 생기지 않고, 구글은 72시간 뒤
미확인(unacknowledged) 결제를 자동 환불한다. 유저는 돈을 냈다가 돌려받고
상품은 못 받는다.

이 배치는 신호는 왔는데 영수증이 없는 건을 찾아 스토어에 실제 결제인지 확인한
뒤, 클라이언트가 보냈어야 할 `/api/purchase/request`를 대신 호출한다.

설계 노트:
- 지급 로직을 복제하지 않고 **API의 `/request` 엔드포인트를 그대로 호출**한다.
  검증·ack·지급·마일리지가 전부 그 경로에 있고, 복제하면 두 경로가 갈라진다.
- 서명된 영수증 payload는 없지만 필요 없다. `validate_google`은 서명을 검증하는
  게 아니라 구글에 직접 물어보기 때문에, `(sku, purchaseToken)`으로 조회한 결과로
  클라이언트가 보냈을 payload를 합성하면 동일한 경로를 탄다.
- **지급 없이 ack만 하는 일은 없어야 한다.** ack은 스토어의 자동 환불을 없애므로,
  지급이 실패하면 유저는 돈만 잃는다. 그래서 완결은 `/request`에 통째로 맡기고
  (지급까지 성공해야 200), 대상이 불명하면 알림만 남긴다.
"""

from datetime import datetime, timedelta, timezone

import requests
import structlog
from shared.enums import PurchaseSignalStatus, Store
from shared.models.product import Product
from shared.models.purchase_signal import PurchaseSignal
from shared.models.receipt import Receipt
from shared.utils.google import get_google_client
from shared.validator.common import build_apple_receipt_data, build_google_receipt_data
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(config.pg_dsn, pool_recycle=3600, pool_pre_ping=True)

GOOGLE_PURCHASE_STATE_PURCHASED = 0


def send_slack_alert(message: str) -> None:
    if not config.iap_alert_webhook_url:
        logger.warning("iap_alert_webhook_url이 설정되지 않았습니다.")
        return
    try:
        requests.post(
            config.iap_alert_webhook_url, json={"text": message}, timeout=10
        ).raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Slack 알림 전송 실패: {e}")


def find_receipt(sess, store: Store, purchase_token: str):
    """신호의 토큰에 대응하는 영수증을 찾는다.

    구글은 영수증 data의 `TransactionID`가 purchaseToken과 같은 값이고,
    애플은 transaction ID가 곧 order_id다.
    """
    if store == Store.APPLE:
        return sess.scalar(
            select(Receipt).where(Receipt.order_id == purchase_token).limit(1)
        )
    return sess.scalar(
        select(Receipt)
        .where(
            or_(
                Receipt.data["TransactionID"].astext == purchase_token,
                Receipt.order_id == purchase_token,
            )
        )
        .limit(1)
    )


def resolve_store_and_package(sess, sku: str):
    """SKU로 스토어와 패키지를 판별한다.

    `/log`는 스토어도 패키지도 보내지 않으므로 상품 마스터에서 역으로 찾는다.
    """
    product = sess.scalar(
        select(Product).where(
            or_(
                Product.google_sku == sku,
                Product.apple_sku == sku,
                Product.apple_sku_k == sku,
            )
        )
    )
    if product is None:
        return None, None, None
    if product.google_sku == sku:
        return Store.GOOGLE, product, None
    package = (
        "com.planetariumlabs.ninechroniclesmobilek"
        if product.apple_sku_k == sku
        else "com.planetariumlabs.ninechroniclesmobile"
    )
    return Store.APPLE, product, package


def lookup_google_purchase(sku: str, purchase_token: str):
    """어느 패키지의 결제인지 모르므로 양쪽에 물어본다.

    `/log`는 패키지명을 보내지 않는다. 잘못된 패키지로 조회하면 404가 난다.
    """
    client = get_google_client(config.google_credential)
    for package_name in config.google_package_dict.values():
        try:
            resp = (
                client.purchases()
                .products()
                .get(packageName=package_name, productId=sku, token=purchase_token)
                .execute()
            )
            return package_name, resp
        except Exception:  # noqa: BLE001  다른 패키지면 404: 다음 후보로
            continue
    return None, None


def request_product_via_api(package_name: str, body: dict) -> requests.Response:
    return requests.post(
        f"{config.iap_api_base_url.rstrip('/')}/api/purchase/request",
        json=body,
        headers={"X-IAP-PACKAGENAME": package_name},
        timeout=30,
    )


def resolve(sess, signal: PurchaseSignal, dry_run: bool) -> str:
    """신호 하나를 처리하고 결과 라벨을 돌려준다."""
    store, product, apple_package = resolve_store_and_package(sess, signal.sku)
    if store is None:
        signal.status = PurchaseSignalStatus.FAILED
        signal.msg = f"Unknown SKU: {signal.sku}"
        return "unknown_sku"

    receipt = find_receipt(sess, store, signal.purchase_token)
    if receipt is not None:
        signal.status = PurchaseSignalStatus.MATCHED
        signal.receipt_id = receipt.id
        return "matched"

    # 여기부터는 "결제는 있었는데 영수증이 없다"는 뜻이다.
    if dry_run:
        signal.status = PurchaseSignalStatus.UNRESOLVED
        signal.msg = "dry-run: receipt missing"
        return "missing_dry_run"

    if not (signal.agent_addr and signal.avatar_addr and signal.planet_id):
        # 지급 대상을 모른다. 여기서 ack만 하면 자동 환불까지 막혀 유저만 손해다.
        signal.status = PurchaseSignalStatus.UNRESOLVED
        signal.msg = "Cannot complete: agent/avatar/planet missing in signal"
        return "unresolved"

    if store == Store.GOOGLE:
        package_name, purchase = lookup_google_purchase(
            signal.sku, signal.purchase_token
        )
        if purchase is None:
            signal.status = PurchaseSignalStatus.FAILED
            signal.msg = "Google lookup failed for every package"
            return "lookup_failed"
        if purchase.get("purchaseState") != GOOGLE_PURCHASE_STATE_PURCHASED:
            signal.status = PurchaseSignalStatus.VOIDED
            signal.msg = f"purchaseState={purchase.get('purchaseState')}"
            return "voided"
        data = build_google_receipt_data(
            purchase["orderId"],
            signal.sku,
            signal.purchase_token,
            purchase["purchaseTimeMillis"],
        )
    else:
        package_name = apple_package
        data = build_apple_receipt_data(signal.purchase_token)

    resp = request_product_via_api(
        package_name,
        {
            "store": int(store),
            "data": data,
            "agentAddress": signal.agent_addr,
            "avatarAddress": signal.avatar_addr,
            "planetId": signal.planet_id,
        },
    )
    if resp.status_code != 200:
        signal.status = PurchaseSignalStatus.FAILED
        signal.msg = f"{resp.status_code} :: {resp.text[:500]}"
        return "request_failed"

    signal.status = PurchaseSignalStatus.COMPLETED
    completed = find_receipt(sess, store, signal.purchase_token)
    if completed is not None:
        signal.receipt_id = completed.id
    return "completed"


def handle(event=None, context=None):
    dry_run = config.purchase_signal_dry_run
    grace = timedelta(minutes=config.purchase_signal_grace_minutes)
    limit = config.purchase_signal_batch_size

    sess = scoped_session(sessionmaker(bind=engine))
    counts: dict[str, int] = {}
    try:
        cutoff = datetime.now(tz=timezone.utc) - grace
        signals = (
            sess.scalars(
                select(PurchaseSignal)
                .where(
                    PurchaseSignal.status == PurchaseSignalStatus.RECEIVED,
                    PurchaseSignal.created_at < cutoff,
                )
                .order_by(PurchaseSignal.created_at)
                .limit(limit + 1)
            )
            .unique()
            .all()
        )
        capped = len(signals) > limit
        signals = signals[:limit]
        if not signals:
            logger.info("확인할 결제 신호가 없습니다.")
            return counts

        for signal in signals:
            try:
                label = resolve(sess, signal, dry_run)
            except Exception as e:  # noqa: BLE001  한 건이 배치 전체를 죽이지 않게
                logger.error(f"신호 처리 실패 {signal.uuid}: {e}")
                signal.status = PurchaseSignalStatus.FAILED
                signal.msg = str(e)[:500]
                label = "error"
            signal.resolved_at = datetime.now(tz=timezone.utc)
            counts[label] = counts.get(label, 0) + 1
            sess.commit()

        logger.info(f"결제 신호 확인 완료 (dry_run={dry_run}): {counts}")

        attention = {k: v for k, v in counts.items() if k != "matched"}
        if attention or capped:
            lines = [
                "🧾 결제 신호 리컨실",
                f"모드: {'DRY-RUN(기록만)' if dry_run else '완결 수행'}",
                f"확인: {sum(counts.values())}건 / 정상: {counts.get('matched', 0)}건",
                f"주의: {attention}",
            ]
            if capped:
                # 상한에 걸려 남은 건은 다음 회차로 넘어간다. 조용히 자르지 않는다.
                lines.append(
                    f"⚠️ 배치 상한({limit})에 걸려 일부는 다음 회차로 미뤘습니다."
                )
            send_slack_alert("\n".join(lines))
        return counts
    finally:
        sess.close()


@app.task(
    name="iap.reconcile_purchase_signal",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def reconcile_purchase_signal(self):
    return handle()


if __name__ == "__main__":
    handle()
