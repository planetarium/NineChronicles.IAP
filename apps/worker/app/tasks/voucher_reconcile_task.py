"""
(PLD-1470/1471) NCG Voucher 회수/리컨사일.

환불 감지 → 포탈 revoke 호출을 아웃박스(voucher_grant_outbox)를 단일 조율점으로 처리.

두 갈래로 REVOKE_PENDING이 큐잉된다:
  - google buyer 환불: track_google_refund가 void 감지 시 `enqueue_revoke_by_order_id`로 큐잉
    (google 환불은 receipt.status를 갱신하지 않으므로 훅이 유일 신호원).
  - admin 환불/무효(status=REFUNDED_*/INVALID): 이 태스크의 status 기반 enroll이 잡음.

아웃박스가 단일 조율점인 이유:
  - REVOKE_PENDING/REVOKED 행은 grant enroll의 notin_에 걸려 재등록 안 되고, grant dispatch(PENDING만)도 안 탄다
    → 환불이 grant보다 먼저 도착해도(REVOKE_PENDING로 생성) 발급이 선점적으로 차단된다.
  - revoke dispatch가 REVOKE_PENDING → 포탈 revoke → REVOKED.

멱등: 포탈 revoke 자체가 iapUuid 기준 멱등(미개봉만 회수, 개봉건은 skippedOpened+경보). 재시도 안전.

⚠️ known gap: Apple buyer 셀프 환불은 현재 신호 경로가 없다(google void tracker만 존재, status도 미갱신).
   Apple 환불 회수는 App Store Server Notifications 처리기 도입 시 같은 enqueue_revoke_for_receipt로 연결 필요.
"""

import datetime
from typing import Optional, Tuple

import jwt
import requests
import structlog
from shared.enums import ReceiptStatus, Store, VoucherGrantStatus
from shared.models.receipt import Receipt
from shared.models.voucher_grant_outbox import VoucherGrantOutbox
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

# grant 태스크와 엔진 공유 — 프로세스당 커넥션 풀 이중 생성 방지(커넥션 예산).
from app.tasks.voucher_grant_task import engine

logger = structlog.get_logger(__name__)

HTTP_TIMEOUT = 10
REVOKE_BATCH = 200
ENROLL_BATCH = 500
ALERT_ATTEMPTS = 5  # REVOKE_PENDING이 이 횟수 이상 재시도 중이면 스톨로 간주해 경보(회수 유실 진행중).
_TRANSIENT_STATUS = {401, 403, 408, 429}
# 환불/무효 — 발급된 바우처를 회수해야 하는 receipt 상태.
_REFUNDED_STATUSES = [
    ReceiptStatus.REFUNDED_BY_ADMIN,
    ReceiptStatus.REFUNDED_BY_BUYER,
    ReceiptStatus.INVALID,
]
# google void → receipt 매칭 시 좁힐 스토어(order_id는 (store,order_id)로만 유일 → 크로스-스토어 오매칭 방지).
#   ⚠️ ONESTORE 를 여기 넣으면 안 된다. 이 목록은 "google void 폴링이 준 order_id" 를 받는
#      자리이고, 넓히는 순간 같은 order_id 를 가진 원스토어 영수증까지 회수된다 — 위 주석이
#      경고하는 크로스-스토어 오매칭 그 자체다. 원스토어 환불 회수는 원스토어 취소 조회를
#      도는 **별도 폴링**이 필요하다(track_google_refund 대응물, 아직 없음).
_GOOGLE_STORES = [Store.GOOGLE, Store.GOOGLE_TEST]
# 회수 대상 = 발급됐을 수 있는 모든 비-종단 상태 + FAILED(크래시창에 발급 후 FAILED 찍힌 건 포함).
_REVOCABLE_OUTBOX_STATUSES = [
    VoucherGrantStatus.PENDING,
    VoucherGrantStatus.GRANTED,
    VoucherGrantStatus.FAILED,
]


def _make_jwt() -> str:
    """포탈 gameBackendApiHandler용 서버간 JWT(HS256, 1분 만료)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {"iat": now, "exp": now + datetime.timedelta(minutes=1), "iss": "iap"},
        config.portal_iap_jwt_secret,
        algorithm="HS256",
    )


def _post_revoke(iap_uuid: str) -> Tuple[bool, Optional[str], bool]:
    """
    포탈 revoke 호출. 반환 (ok, ref, transient):
      - ok=True     → REVOKED로 종료
      - transient   → 재시도(REVOKE_PENDING 유지): 5xx·인증·레이트리밋·타임아웃
      - 둘 다 False  → 재시도 무의미한 오류(4xx). revoke는 유실이 곧 미회수(환불 NCG 잔존)이므로
                        드롭하지 않고 REVOKE_PENDING 유지 + 경보로 사람 개입 유도(상위에서 처리).
    """
    resp = requests.post(
        config.portal_revoke_url,
        json={"iapUuid": iap_uuid},
        headers={"Authorization": f"Bearer {_make_jwt()}"},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 500 or resp.status_code in _TRANSIENT_STATUS:
        return False, f"{resp.status_code}", True
    if resp.status_code != 200:
        return False, f"{resp.status_code}:{resp.text[:200]}", False
    body = resp.json()
    if not isinstance(body, dict):
        return False, f"unexpected body: {str(body)[:100]}", False
    skipped = body.get("skippedOpened") or []
    ref = (
        f"revoked={body.get('revoked')} already={body.get('alreadyRevoked')} "
        f"skippedOpened={skipped}"
    )
    return True, ref, False


def _alert(text: str) -> None:
    url = config.iap_alert_webhook_url
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        logger.warning("voucher reconcile alert failed", error=str(e))


def enqueue_revoke_for_receipt(sess, receipt_id: int) -> bool:
    """
    환불된 결제의 아웃박스를 REVOKE_PENDING으로. 없으면 생성(grant 선점). 멱등.
      - 아웃박스 없음: REVOKE_PENDING으로 생성 → grant enroll(notin_)·dispatch(PENDING)가 모두 스킵 → 발급 선점 차단.
      - PENDING/GRANTED: REVOKE_PENDING으로 전이.
      - REVOKED/REVOKE_PENDING: no-op.
    반환: 큐잉(변경/생성) 여부.
    """
    ob = sess.scalar(
        select(VoucherGrantOutbox).where(VoucherGrantOutbox.receipt_id == receipt_id)
    )
    if ob is None:
        # 신규 생성. grant enroll이 같은 receipt_id를 동시에 INSERT할 수 있으므로 SAVEPOINT로 격리 —
        #   충돌 없으면 REVOKE_PENDING 생성, 충돌(grant가 선점)이면 재조회 후 전이(배치 통째 롤백 방지).
        try:
            with sess.begin_nested():
                sess.add(
                    VoucherGrantOutbox(
                        receipt_id=receipt_id, status=VoucherGrantStatus.REVOKE_PENDING
                    )
                )
            return True
        except IntegrityError:
            ob = sess.scalar(
                select(VoucherGrantOutbox).where(
                    VoucherGrantOutbox.receipt_id == receipt_id
                )
            )
            if ob is None:  # 이론상 도달 불가
                return False
    if ob.status in (VoucherGrantStatus.REVOKED, VoucherGrantStatus.REVOKE_PENDING):
        return False
    ob.status = VoucherGrantStatus.REVOKE_PENDING
    return True


def enqueue_revoke_by_order_id(sess, order_id: str) -> bool:
    """
    google void의 order_id로 receipt 찾아 revoke 큐잉. 반환: 하나라도 큐잉되면 True.
      ⚠️ order_id는 (store, order_id)로만 유일 → 스토어를 google 계열로 좁혀 크로스-스토어 오매칭 방지.
         (다른 스토어의 동일 order_id를 잘못 회수하면 정상 유저 손해). 다중 매치는 모두 큐잉.
    """
    receipts = (
        sess.execute(
            select(Receipt).where(
                Receipt.order_id == order_id,
                Receipt.store.in_(_GOOGLE_STORES),
            )
        )
        .scalars()
        .all()
    )
    queued = False
    for r in receipts:
        if enqueue_revoke_for_receipt(sess, r.id):
            queued = True
    return queued


def enqueue_revoke_by_order_ids(order_ids) -> int:
    """
    여러 order_id에 대해 revoke 큐잉(자체 세션 관리). track_google_refund 환불 감지 훅용.
    voucher_grant_enabled=False면 no-op(0). 한 건 실패가 나머지를 막지 않음.
    """
    if not config.voucher_grant_enabled or not order_ids:
        return 0
    sess = scoped_session(sessionmaker(bind=engine))
    n = 0
    try:
        for oid in order_ids:
            try:
                if enqueue_revoke_by_order_id(sess, oid):
                    n += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("enqueue revoke failed", order_id=oid, error=str(e))
        sess.commit()
        if n:
            logger.info("refund → revoke queued", count=n)
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.remove()
    return n


@app.task(
    name="iap.voucher_reconcile",
    bind=True,
    acks_late=True,
    queue="background_job_queue",
)
def reconcile_vouchers(self):
    """환불/무효 결제의 바우처 회수(beat, */5분)."""
    if not config.voucher_grant_enabled:
        return "voucher grant disabled"
    if not (config.portal_revoke_url and config.portal_iap_jwt_secret):
        logger.warning("voucher revoke not configured (url/secret missing)")
        return "not configured"

    sess = scoped_session(sessionmaker(bind=engine))
    enqueued = revoked = failed = 0
    try:
        # (A) status 기반 enroll — 환불/무효 receipt를 가진 미회수 아웃박스 → REVOKE_PENDING.
        #     (google buyer 환불은 status 미갱신이라 track_google_refund 훅이 담당; 여기선 admin 환불 등.)
        rows = (
            sess.execute(
                select(VoucherGrantOutbox)
                .join(Receipt, Receipt.id == VoucherGrantOutbox.receipt_id)
                .where(
                    # FAILED 포함: grant가 HTTP 200(발급)後 commit前 크래시→재전달 사이 admin 환불 시
                    # 재dispatch가 FAILED로 찍는데 바우처는 이미 발급됨 → 회수 누락 방지(revoke는 멱등이라
                    # 미발급 receipt엔 no-op으로 무해).
                    VoucherGrantOutbox.status.in_(_REVOCABLE_OUTBOX_STATUSES),
                    Receipt.status.in_(_REFUNDED_STATUSES),
                )
                .limit(ENROLL_BATCH)
            )
            .scalars()
            .all()
        )
        for ob in rows:
            ob.status = VoucherGrantStatus.REVOKE_PENDING
            enqueued += 1
        sess.commit()

        # (B) revoke dispatch — REVOKE_PENDING → 포탈 revoke. 행 잠금으로 동시 실행 중복 방지.
        pendings = (
            sess.execute(
                select(VoucherGrantOutbox)
                .where(VoucherGrantOutbox.status == VoucherGrantStatus.REVOKE_PENDING)
                # attempts 오름차순 우선 — 영구 4xx 등 고-attempts 행이 batch 앞을 막아
                # 신규 회수가 starve되지 않게(신규 attempts=0 먼저 처리).
                .order_by(VoucherGrantOutbox.attempts, VoucherGrantOutbox.receipt_id)
                .limit(REVOKE_BATCH)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for ob in pendings:
            try:
                r = sess.scalar(select(Receipt).where(Receipt.id == ob.receipt_id))
                if r is None:
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = "receipt not found (revoke)"
                    continue
                try:
                    ok, ref, transient = _post_revoke(str(r.uuid))
                except requests.RequestException as e:
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = f"http error: {e}"[:500]
                    continue

                if ok:
                    ob.status = VoucherGrantStatus.REVOKED
                    ob.revoked_at = datetime.datetime.now(datetime.timezone.utc)
                    ob.portal_ref = ref
                    revoked += 1
                else:
                    # transient/4xx 모두 REVOKE_PENDING 유지(회수 유실=환불 NCG 잔존이므로 드롭 금지).
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = f"{'transient' if transient else 'error'}: {ref}"
                    if not transient:
                        failed += 1
            except Exception as e:  # noqa: BLE001
                ob.attempts = (ob.attempts or 0) + 1
                ob.last_error = f"unexpected: {e}"[:500]
        sess.commit()

        # 스톨 경보 — transient(5xx/인증/레이트리밋)로 무한 재시도 중인 회수는 failed에 안 잡히므로
        #   attempts 임계 이상 REVOKE_PENDING 백로그를 별도 집계해 알림(회수 유실이 진행 중일 수 있음).
        stalled = (
            sess.scalar(
                select(func.count())
                .select_from(VoucherGrantOutbox)
                .where(
                    VoucherGrantOutbox.status == VoucherGrantStatus.REVOKE_PENDING,
                    VoucherGrantOutbox.attempts >= ALERT_ATTEMPTS,
                )
            )
            or 0
        )

        result = f"enqueued={enqueued} revoked={revoked} failed={failed} stalled={stalled}"
        logger.info("voucher reconcile run", result=result)
        if failed > 0 or stalled > 0:
            _alert(
                f"[voucher-revoke] 회수 실패/스톨 (수동 검토): failed={failed} "
                f"stalled(attempts>={ALERT_ATTEMPTS})={stalled}. {result}"
            )
        return result
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.remove()
