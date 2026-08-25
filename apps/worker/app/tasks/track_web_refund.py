"""
(PLD-1470) WEB(Stripe) 환불 → NCG Voucher 회수.

왜 필요한가:
  복권 바우처는 결제 후 홀드(기본 72h)가 끝나야 개봉할 수 있고, 그 사이 결제가 환불되면 회수해야 한다.
  그런데 기존 회수 신호원은 둘뿐이었다 — google void 훅(track_google_refund)과
  reconcile 의 admin 환불 스캔(receipt.status=REFUNDED_*/INVALID).
  **WEB(Stripe) 결제의 환불 신호는 어디에도 없었다.**
  확정 기획이 PC(=WEB) 결제에 상금 ×1.25 를 주므로, 가장 후한 플랫폼이 곧 회수 경로가 없는 플랫폼이었다
  (환불 어뷰징의 기대이익이 다른 플랫폼보다 25% 크다). 이 태스크가 그 구멍을 막는다.

어떻게:
  Stripe 웹훅을 IAP 로 물려둔 곳이 없으므로 track_google_refund 와 같은 결로 **폴링**한다.
  매칭 키는 실측 사실 하나 — **유료 WEB 영수증의 receipt.order_id 가 곧 Stripe payment_intent id**
  (메인넷 실측: order_id=pi_3U7WUvHMe8eeDxjg03lY9f6k, data 에 amount/currency/paymentIntent/purchaseDate/productId).
  무료 클레임(`FREE-<uuid>`)·마일리지 교환(`MILE-<uuid>`)은 Stripe 결제가 아니라 접두어가 다르고,
  Stripe 가 돌려주는 값은 항상 `pi_…` 이므로 구조적으로 섞일 수 없다(별도 접두어 필터가 불필요한 이유).

  refund.payment_intent → Receipt.order_id 매칭 → enqueue_revoke_by_order_ids(stores=WEB_STORES)
  → 아웃박스 REVOKE_PENDING → reconcile 이 포탈 revoke 호출(미개봉만 회수, 개봉건은 skippedOpened+경보).
  **회수 파이프라인은 이미 있는 것을 그대로 재사용**하고, 이 모듈은 "신호원" 역할만 한다.

폴링 전략(커서를 두지 않은 이유):
  track_google_refund 와 동일하게 **고정 룩백 윈도우 + 겹침**이고, 중복 방지는 커서가 아니라
  `enqueue_revoke_for_receipt` 의 멱등성(REVOKE_PENDING/REVOKED 는 no-op)이 담당한다.
  커서를 DB 에 두려면 재사용할 kv/설정 테이블이 IAP 에 없어 신규 테이블이 필요한데(최후수단),
  얻는 게 "이미 멱등인 조회의 중복 제거"뿐이라 비용이 이득보다 크다.
  대신 윈도우를 스케줄보다 크게 잡아 beat/워커가 죽어 있던 구간을 자동으로 되짚는다 —
  웹훅이 없어 폴링이 유일 신호원이므로, 놓친 구간을 만회하는 수단이 겹침밖에 없다.
  ⚠️ 유실이 실제로 생기는 경로는 "룩백보다 긴 공백"이다(휴면→배선 컷오버 갭 / 워커가 룩백보다 오래 다운 /
     콜드 스타트에 MAX_REFUNDS 도달). 그래서 룩백은 모듈 상수가 아니라 config
     (`WORKER_STRIPE_REFUND_LOOKBACK_HOURS`)다 — 컷오버 때 재배포 없이 일회성 광역 스캔을 돌릴 수 있어야 한다.

⚠️ 회수는 되살릴 수 없다 — 오회수 시 수동 복구뿐이다(절차는 voucher_reconcile_task 모듈 docstring).
   그래서 이 태스크는 **큐잉을 요청한 order_id 목록과 그중 pending 유래 subset 을 INFO 로 남긴다**.
   뒤집힘 위험이 pending 에 국한되지 않는 것도 이유다 — Stripe 는 이미 `succeeded` 인 환불도 며칠 뒤
   `failed` 로 뒤집을 수 있다(refund.failed 이벤트, failure_reason/failure_balance_transaction).
   즉 "어느 상태를 회수 대상에 넣느냐"보다 **"뒤집힘을 사후에 찾아낼 수 있느냐"** 가 실질적인 방어선이고,
   그 단서가 이 로그다(reconcile 의 enqueue 로그와 짝).

범위 경계(의도적으로 안 하는 것):
  - **receipt.status 를 REFUNDED_BY_BUYER 등으로 바꾸지 않는다.** google 트래커도 안 바꾼다.
    영수증 상태는 환불 회계·구매제한(get_purchase_count)·재구매 판정에 물려 있어 별건으로 다뤄야 한다.
    이 태스크는 **바우처 회수만** 한다.
  - Apple 셀프 환불(App Store Server Notifications)은 여전히 신호 경로가 없다 — 별건.
  - 카드 분쟁/차지백(charge.dispute)은 Refund 객체가 아니어서 여기 안 잡힌다 — 별건.
  - 건별 Slack 알림도 붙이지 않는다. Stripe 계정에는 IAP 영수증과 무관한 환불도 섞일 수 있어
    "미매칭 환불"이 정상이고, 그걸 건별로 쏘면 노이즈다. 대신 **신호원이 조용히 죽는 것**은 경보한다(아래).
"""

import datetime

import stripe
import structlog

from app.celery_app import app
from app.config import config
from app.tasks.voucher_reconcile_task import (
    LOG_ID_CAP,
    WEB_STORES,
    _alert,  # 회수 도메인의 슬랙 경보 헬퍼 재사용(같은 웹훅) — 같은 함수를 또 만들지 않는다.
    enqueue_revoke_by_order_ids,
)

logger = structlog.get_logger(__name__)

# 스케줄은 celery_app.py 에서 15분 간격(다른 바우처 beat 와 겹치지 않게 7/22/37/52분). 룩백은 config(기본 24h).
# 근거:
#   - 홀드가 72h 라 15분 지연은 회수 여유에 비해 무시할 수준이고(최악 15분 + reconcile 5분),
#     Stripe 호출은 실행당 1~2 페이지라 하루 ~100 콜 — API 낭비가 아니다.
#   - 겹침이 24h 면 워커/beat 가 하루 종일 죽어 있어도 유실이 0 이다.
#   - 중복 조회는 무해하다: enqueue 가 멱등이라 이미 큐잉된 건은 DB 쓰기조차 없다.
#   - refund.created 는 status 가 pending→succeeded 로 바뀌어도 그대로다. 넓은 윈도우가
#     그 전이를 같은 창 안에서 다시 보게 해준다(웹훅 없이 상태 전이를 따라잡는 유일한 방법).
PAGE_SIZE = 100  # Stripe list 최대치. 페이지 수(=API 호출 수)를 최소화.
# 폭주 방어 상한. Stripe list 는 최신순이므로 잘리는 쪽은 **가장 오래된** 건 —
#   즉 이전 실행들이 이미 처리한 구간이다(상한에 닿아도 신규 환불을 놓치지 않는다).
#   단, 콜드 스타트(첫 광역 스캔)에서는 상한 = 유실 경계이므로 경고를 보고 룩백을 조절해야 한다.
MAX_REFUNDS = 2000
# 회수 대상 환불 상태. failed/canceled 는 돈이 안 돌아갔으므로 제외.
#   pending 을 포함하는 건 판단이다 — 목적이 어뷰징 방어이고, 회수는 **미개봉** 바우처만 대상이며
#   포탈 revoke 가 멱등이다. 반대로 pending 을 빼면 "윈도우 밖에서 succeeded 로 전이한 환불"을
#   영구히 놓친다(더 나쁜 실패). 뒤집힘은 로그로 사후 추적한다(위 docstring).
_REVOCABLE_REFUND_STATUSES = {"succeeded", "pending"}
# 연속 실패 경보 임계. 15분 × 3 = 45분 이상 신호가 끊기면 알린다.
#   왜 필요한가: 키 폐기·restricted key 의 refund:read 누락·계정 권한 변경 같은 **지속 실패**는
#   "회수 신호 0" 상태를 만드는데, 워커엔 task_failure 핸들러가 없고 reconcile 의 stalled 경보는
#   **이미 큐잉된 것**만 본다 → 어뷰징 방어가 꺼진 채 조용히 굳는다.
ALERT_FAILURES = 3
# ⚠️ 프로세스-로컬 카운터다(prefork 워커면 자식마다 별개) → 임계 도달이 늦어질 수 있지만,
#    지속 실패라면 어느 자식에서든 결국 도달한다. 상태 저장소를 새로 만들지 않기 위한 의도적 트레이드오프.
_consecutive_failures = 0


def _lookback() -> datetime.timedelta:
    """폴링 룩백. config 값이 이상하면(0/음수) 기본 24h 로 되돌린다 — 창이 0 이면 신호가 조용히 끊긴다."""
    hours = config.stripe_refund_lookback_hours
    if not hours or hours <= 0:
        logger.warning("invalid stripe refund lookback, falling back to 24h", value=hours)
        hours = 24
    return datetime.timedelta(hours=hours)


def _list_recent_refunds(created_gte: int) -> list:
    """
    Stripe 최근 환불 목록(created >= created_gte).

    api_key/stripe_version 을 **요청 옵션으로** 넘긴다 — `stripe.api_key` 전역을 세팅하면
    같은 프로세스의 다른 태스크로 새기 때문(워커는 한 프로세스에서 여러 태스크를 돈다).
    """
    page = stripe.Refund.list(
        created={"gte": created_gte},
        limit=PAGE_SIZE,
        api_key=config.stripe_secret_key,
        stripe_version=config.stripe_api_version,
    )
    refunds = []
    for refund in page.auto_paging_iter():
        refunds.append(refund)
        if len(refunds) >= MAX_REFUNDS:
            logger.warning(
                "stripe refund 조회가 상한에 도달(룩백/환불량 재검토 필요)",
                limit=MAX_REFUNDS,
            )
            break
    return refunds


def _revocable_order_ids(refunds):
    """
    환불 목록 → (회수 대상 order_id 목록, 그중 pending 만으로 이뤄진 subset).

    pending-only subset 을 따로 돌려주는 이유는 추적이다 — 뒤집힐 확률이 가장 높은 회수가 그쪽이므로
    로그에서 바로 골라낼 수 있어야 한다(오회수 복구는 수동뿐).
      - 부분 환불도 회수 대상으로 본다(어뷰징 방어 우선). 한 PaymentIntent 에 부분 환불이 여러 건이면
        같은 order_id 가 반복되므로 dedup 해서 쿼리·집계를 정직하게 유지한다.
      - expand 를 안 걸었으므로 payment_intent 는 문자열 id 다. Charge 직접 환불(payment_intent=None)은
        WEB 결제 경로가 아니므로 건너뛴다.
    """
    order_ids = []
    statuses = {}
    for refund in refunds:
        status = getattr(refund, "status", None)
        if status not in _REVOCABLE_REFUND_STATUSES:
            continue
        payment_intent = getattr(refund, "payment_intent", None)
        if not isinstance(payment_intent, str) or not payment_intent:
            continue
        if payment_intent not in statuses:
            statuses[payment_intent] = set()
            order_ids.append(payment_intent)
        statuses[payment_intent].add(status)
    pending_only = [oid for oid in order_ids if statuses[oid] == {"pending"}]
    return order_ids, pending_only


def handle() -> str:
    global _consecutive_failures

    # 킬스위치 먼저 — enqueue 헬퍼도 같은 검사를 하지만, 여기서 끊어야 Stripe 호출 자체가 낭비되지 않는다.
    if not config.voucher_grant_enabled:
        return "voucher grant disabled"
    if not config.stripe_secret_key:
        # 휴면. 메인넷엔 아직 WORKER_STRIPE_SECRET_KEY 가 없으므로 이미지만 올라가도 아무 일도 안 일어나야 한다.
        #   (reconcile 의 "not configured" 와 같은 결로 매 실행 warning — 배선 누락을 조용히 넘기지 않는다.)
        logger.warning("web refund tracking not configured (stripe secret missing)")
        return "stripe secret not configured"

    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = now - _lookback()
    try:
        refunds = _list_recent_refunds(int(window_start.timestamp()))
    except Exception as e:  # noqa: BLE001
        # 실패를 삼키지 않고 올린다(다음 tick 이 같은 창을 되짚으므로 한 번의 실패는 무해).
        #   다만 **지속 실패는 "회수 신호 0" 이라 반드시 사람에게 알려야 한다** → 임계 초과 시 경보.
        _consecutive_failures += 1
        logger.error(
            "stripe refund scan failed",
            error=str(e),
            consecutive_failures=_consecutive_failures,
        )
        if _consecutive_failures % ALERT_FAILURES == 0:
            _alert(
                f"[voucher-revoke] WEB(Stripe) 환불 스캔이 {_consecutive_failures}회 연속 실패 — "
                f"환불 회수 신호가 끊긴 상태입니다(키 폐기/권한 확인 필요). 마지막 오류: {str(e)[:300]}"
            )
        raise

    _consecutive_failures = 0
    order_ids, pending_only = _revocable_order_ids(refunds)
    queued = enqueue_revoke_by_order_ids(order_ids, stores=WEB_STORES)

    result = f"refunds={len(refunds)} revocable={len(order_ids)} queued={queued}"
    # 성공 스캔 하트비트 + 추적 단서. last_success 를 매 실행 남겨서 "신호원이 언제까지 살아 있었나"를
    #   로그만으로 되짚을 수 있게 한다(별도 저장소 없이).
    logger.info(
        "web(stripe) refund scan",
        last_success=now.isoformat(),
        window_start=window_start.isoformat(),
        result=result,
        order_ids=order_ids[:LOG_ID_CAP],
        pending_only_order_ids=pending_only[:LOG_ID_CAP],
        truncated=len(order_ids) > LOG_ID_CAP,
    )
    return result


# 재시도 노브(max_retries/default_retry_delay/retry_backoff)를 달지 않는다 — autoretry_for 도 self.retry() 도
#   없으면 무효 설정이고(google 트래커의 그 설정은 실제로 아무 일도 하지 않는다), 이 태스크는 룩백 겹침으로
#   다음 tick 이 같은 창을 되짚기 때문에 celery 재시도가 필요 없다. bind 도 쓸 데가 없어 뺀다.
@app.task(
    name="iap.track_web_refund",
    acks_late=True,
    queue="background_job_queue",
)
def track_web_refund():
    return handle()


if __name__ == "__main__":
    handle()
