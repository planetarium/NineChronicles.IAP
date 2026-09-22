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
    # **`or_` 로 묶으면 안 된다.** PG 는 OR 의 **모든** 가지가 인덱스 가능해야 BitmapOr 를 쓰는데,
    #   `receipt.order_id` 에는 인덱스가 없다(`data->>'TransactionID'` 쪽만 `d2f4a1c6e8b3` 이
    #   표현식 인덱스를 만들어 뒀다). 그래서 묶는 순간 그 인덱스가 죽고 seq scan 으로 떨어진다.
    #   그 마이그레이션 주석에 실측이 남아 있다 — receipt 74만 행 / 힙 1.4GB / PG 버퍼 128MB,
    #   메인넷 순차 스캔 shared read 174,905 blocks · **15.5초**. 10분마다 최대 50회면
    #   버퍼 축출까지 같이 온다. 그리고 이건 dry_run 과 무관하게 돈다 — dry-run 의 정상
    #   경로(MATCHED 판정)가 바로 이 함수다.
    #   그래서 인덱스 있는 쪽을 먼저 보고, 없을 때만 order_id 로 한 번 더 본다.
    hit = sess.scalar(
        select(Receipt)
        .where(Receipt.data["TransactionID"].astext == purchase_token)
        .limit(1)
    )
    if hit is not None:
        return hit
    return sess.scalar(
        select(Receipt).where(Receipt.order_id == purchase_token).limit(1)
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
        # **애플은 환불 게이트가 어디에도 없다.** 구글은 위에서 `purchaseState` 를 보지만,
        #   `validate_apple` 은 애플이 200 만 주면 무조건 success 이고 `ApplePurchaseSchema` 엔
        #   `revocationDate` 필드조차 없다. 즉 **환불된 애플 결제를 이 배치가 지급한다.**
        #
        #   평시엔 신호 10분 뒤 처리라 환불 창이 좁지만, 위험한 건 **묵은 신호를 한꺼번에
        #   드레인할 때**다 — dry_run 을 끄는 순간이 정확히 그 순간이고, 플래그는 env 하나라
        #   구글·애플이 **동시에** 켜진다. "나중에 기억해서 애플 게이트를 넣는다" 가 성립하지
        #   않는 구조라, 게이트가 생기기 전까지는 완결하지 않고 사람에게 넘긴다.
        signal.status = PurchaseSignalStatus.UNRESOLVED
        signal.msg = (
            "애플은 환불(revocationDate) 확인 경로가 없어 자동 완결하지 않는다 — "
            "게이트를 넣기 전까지는 수동 처리"
        )
        return "apple_needs_void_gate"

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
    else:
        # 200 을 받았는데 영수증을 못 찾았다 = **매칭 키가 어긋났다는 유일한 조기 신호**다.
        #
        # 이 배치의 이중 지급 안전성은 전부 `/request` 의 dedup `(store, order_id)` 에 실려 있고,
        # 그 `order_id` 는 우리가 **합성한** 값이다(구글 `orderId`). 반면 신호↔영수증 매칭은
        # `purchase_token` 으로 한다. 두 키가 같은 결제를 가리키는 한 재실행·경합·크래시가 전부
        # 막히지만, 합성한 `orderId` 가 클라가 보냈을 값과 달라지면 dedup 이 헛돌아 **같은 결제가
        # 두 번 지급될 수 있다.** 그 어긋남이 눈에 보이는 순간이 정확히 여기다 — 조용히 넘기면
        # 두 번째 지급이 나가고 나서야 안다.
        logger.warning(
            f"[SIGNAL_RECEIPT_UNMATCHED] {signal.id} :: {store} :: {signal.purchase_token} "
            "— /request 는 200 인데 영수증을 못 찾았다. 신호↔영수증 매칭 키가 어긋났을 수 있고, "
            "그러면 dedup 이 헛돌아 이중 지급이 가능하다. 즉시 확인할 것."
        )
        # 라벨을 쪼개야 Slack 요약(`attention`)에 실린다. "completed" 로 되돌리면
        #   정상 완결과 글자 하나 차이도 안 나서, "즉시 확인할 것" 이라 써 놓고 전달 수단이
        #   로그 한 줄뿐인 상태가 된다.
        return "completed_unmatched"
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
                # **rollback 이 먼저다.** DB 오류(statement timeout·커넥션 블립)면 세션이
                #   이미 실패 트랜잭션이라, 그대로 쓰고 commit 하면 PendingRollbackError 가
                #   for 루프 **밖으로** 튄다. 그러면 finally 만 돌고 아래 Slack 요약 구간을
                #   지나지 못한다 — 알람이 배치 **안**에 있는 구조라, 직전에 고친 '등록 누락'
                #   과 똑같이 **조용히 안 도는** 상태가 된다.
                #   rollback 뒤엔 signal 이 detach 되므로 다시 붙여서 쓴다.
                sess.rollback()
                signal = sess.get(PurchaseSignal, signal.id)
                if signal is None:  # 그 사이 지워졌다면 셀 것도 없다
                    counts["error"] = counts.get("error", 0) + 1
                    continue
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
