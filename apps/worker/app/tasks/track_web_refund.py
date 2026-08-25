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

범위 경계(의도적으로 안 하는 것):
  - **receipt.status 를 REFUNDED_BY_BUYER 등으로 바꾸지 않는다.** google 트래커도 안 바꾼다.
    영수증 상태는 환불 회계·구매제한(get_purchase_count)·재구매 판정에 물려 있어 별건으로 다뤄야 한다.
    이 태스크는 **바우처 회수만** 한다.
  - Apple 셀프 환불(App Store Server Notifications)은 여전히 신호 경로가 없다 — 별건.
  - 카드 분쟁/차지백(charge.dispute)은 Refund 객체가 아니어서 여기 안 잡힌다 — 별건.
  - 건별 Slack 알림도 붙이지 않는다. Stripe 계정에는 IAP 영수증과 무관한 환불도 섞일 수 있어
    "미매칭 환불"이 정상이고, 그걸 건별로 쏘면 노이즈다. 회수 실패/스톨 경보는 reconcile 이 이미 담당한다.
"""

import datetime

import stripe
import structlog

from app.celery_app import app
from app.config import config
from app.tasks.voucher_reconcile_task import (
    WEB_STORES,
    enqueue_revoke_by_order_ids,
)

logger = structlog.get_logger(__name__)

# 룩백 윈도우 24h vs 스케줄 15분(celery_app.py) = 96배 겹침. 근거:
#   - 홀드가 72h 라 15분 지연은 회수 여유에 비해 무시할 수준이고(최악 15분 + reconcile 5분),
#     Stripe 호출은 실행당 1~2 페이지라 하루 ~100 콜 — API 낭비가 아니다.
#   - 겹침이 24h 면 워커/beat 가 하루 종일 죽어 있어도 유실이 0 이다.
#   - 중복 조회는 무해하다: enqueue 가 멱등이라 이미 큐잉된 건은 DB 쓰기조차 없다.
#   - refund.created 는 status 가 pending→succeeded 로 바뀌어도 그대로다. 넓은 윈도우가
#     그 전이를 같은 창 안에서 다시 보게 해준다(웹훅 없이 상태 전이를 따라잡는 유일한 방법).
POLL_WINDOW = datetime.timedelta(hours=24)
PAGE_SIZE = 100  # Stripe list 최대치. 페이지 수(=API 호출 수)를 최소화.
# 폭주 방어 상한. Stripe list 는 최신순이므로 잘리는 쪽은 **가장 오래된** 건 —
#   즉 이전 실행들이 이미 처리한 구간이다(상한에 닿아도 신규 환불을 놓치지 않는다).
MAX_REFUNDS = 2000
# 회수 대상 환불 상태. failed/canceled 는 돈이 안 돌아갔으므로 제외.
#   pending 을 포함하는 건 판단이다 — 목적이 어뷰징 방어이고, 회수는 **미개봉** 바우처만 대상이며
#   포탈 revoke 가 멱등이다. pending 이 나중에 failed 로 뒤집히는 카드 환불은 드물고,
#   반대로 pending 을 빼면 "윈도우 밖에서 succeeded 로 전이한 환불"을 영구히 놓친다(더 나쁜 실패).
_REVOCABLE_REFUND_STATUSES = {"succeeded", "pending"}


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
                "stripe refund 조회가 상한에 도달(윈도우/환불량 재검토 필요)",
                limit=MAX_REFUNDS,
            )
            break
    return refunds


def _revocable_order_ids(refunds) -> list:
    """
    환불 목록 → 회수 대상 order_id(=payment_intent id). 중복 제거.
      - 부분 환불도 회수 대상으로 본다(어뷰징 방어 우선). 한 PaymentIntent 에 부분 환불이 여러 건이면
        같은 order_id 가 반복되므로 dedup 해서 쿼리·집계를 정직하게 유지한다.
      - expand 를 안 걸었으므로 payment_intent 는 문자열 id 다. Charge 직접 환불(payment_intent=None)은
        WEB 결제 경로가 아니므로 건너뛴다.
    """
    order_ids = []
    seen = set()
    for refund in refunds:
        if getattr(refund, "status", None) not in _REVOCABLE_REFUND_STATUSES:
            continue
        payment_intent = getattr(refund, "payment_intent", None)
        if not isinstance(payment_intent, str) or not payment_intent:
            continue
        if payment_intent in seen:
            continue
        seen.add(payment_intent)
        order_ids.append(payment_intent)
    return order_ids


def handle() -> str:
    # 킬스위치 먼저 — enqueue 헬퍼도 같은 검사를 하지만, 여기서 끊어야 Stripe 호출 자체가 낭비되지 않는다.
    if not config.voucher_grant_enabled:
        return "voucher grant disabled"
    if not config.stripe_secret_key:
        # 휴면. 메인넷엔 아직 WORKER_STRIPE_SECRET_KEY 가 없으므로 이미지만 올라가도 아무 일도 안 일어나야 한다.
        #   (reconcile 의 "not configured" 와 같은 결로 매 실행 warning — 배선 누락을 조용히 넘기지 않는다.)
        logger.warning("web refund tracking not configured (stripe secret missing)")
        return "stripe secret not configured"

    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = now - POLL_WINDOW
    # Stripe 오류는 잡지 않고 올린다(google 트래커와 동일) — 윈도우가 스케줄보다 훨씬 넓어
    #   실패한 실행 구간은 다음 tick 이 그대로 되짚는다. 실패를 삼켜 안 보이게 만드는 쪽이 더 위험하다.
    refunds = _list_recent_refunds(int(window_start.timestamp()))
    order_ids = _revocable_order_ids(refunds)
    queued = enqueue_revoke_by_order_ids(order_ids, stores=WEB_STORES)

    result = f"refunds={len(refunds)} revocable={len(order_ids)} queued={queued}"
    logger.info(
        "web(stripe) refund scan",
        window_start=window_start.isoformat(),
        result=result,
    )
    return result


@app.task(
    name="iap.track_web_refund",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def track_web_refund(self):
    return handle()


if __name__ == "__main__":
    handle()
