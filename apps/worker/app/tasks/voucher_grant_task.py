"""
(PLD-1469/1472) NCG Voucher 지급 트리거.

검증 완료(VALID) + 상품 지급 성공(tx SUCCESS)한 결제를 폴링해 포탈 grant를 호출하는 beat 태스크.
복잡한 send_product handle()을 건드리지 않고 아웃박스(voucher_grant_outbox)로 디커플링 — 멱등·재시도.

흐름:
  (A) enroll: cutoff 이후 VALID+SUCCESS+실스토어 영수증 중 아직 아웃박스 없는 건 → PENDING 아웃박스 생성(레이스는 SAVEPOINT로 흡수).
  (B) dispatch: PENDING 아웃박스 → 상태 재검증 → 상품별 tickets 조회 → 포탈 grant 호출 → GRANTED / 재시도(PENDING) / FAILED.

상태 의미:
  PENDING  = 미처리/재시도 대상(회복 가능한 실패 포함: 인증·레이트리밋·5xx·가격 미활성).
  GRANTED  = 포탈 grant 성공(종단).
  FAILED   = 진짜 종단 실패(환불/무효 영수증, 미등록 planet, 금액 상한 초과 등 재시도 무의미) — 알림 대상.

멱등: 아웃박스 receipt_id UNIQUE + 포탈 grant 자체가 iapUuid 멱등. 포탈 policy.enabled=false면 'voucher disabled'로
      반환되며 PENDING 유지(활성화 후 재발급).
"""

import datetime
from typing import Optional, Tuple

import jwt
import requests
import structlog
from shared.enums import ReceiptStatus, Store, TxStatus, VoucherGrantStatus
from shared.models.product_voucher_grant import ProductVoucherGrant
from shared.models.receipt import Receipt
from shared.models.voucher_grant_outbox import VoucherGrantOutbox
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(
    config.pg_dsn, pool_size=5, max_overflow=10, pool_recycle=3600, pool_pre_ping=True
)

# 실 결제 스토어 → 바우처 플랫폼. WEB=PC, APPLE/GOOGLE=MOBILE.
_PROD_STORES = {Store.APPLE, Store.GOOGLE, Store.WEB}
_TEST_STORES = {Store.APPLE_TEST, Store.GOOGLE_TEST, Store.WEB_TEST}
_MOBILE_STORES = {Store.APPLE, Store.APPLE_TEST, Store.GOOGLE, Store.GOOGLE_TEST}
_PC_STORES = {Store.WEB, Store.WEB_TEST}

HTTP_TIMEOUT = 10
ENROLL_BATCH = 500
DISPATCH_BATCH = 200
ALERT_ATTEMPTS = 5  # PENDING이 이 횟수 이상 재시도 중이면 stall로 간주해 경보(미지급 침전 가시화).
# 인증(만료/무효 JWT)·레이트리밋·타임아웃은 회복 가능 → transient(재시도). 그 외 4xx는 종단.
_TRANSIENT_STATUS = {401, 403, 408, 429}


def _grantable_stores() -> set:
    """바우처 대상 스토어. production에선 실 스토어만, 그 외(dev/staging)엔 샌드박스도 포함(e2e)."""
    if config.stage == "production":
        return set(_PROD_STORES)
    return _PROD_STORES | _TEST_STORES


def platform_for_store(store: Store) -> Optional[str]:
    """(PLD-1472) 스토어 → 플랫폼. WEB=PC, APPLE/GOOGLE=MOBILE. TEST/REDEEM=None(대상 아님)."""
    if store in _PC_STORES:
        return "PC"
    if store in _MOBILE_STORES:
        return "MOBILE"
    return None


def tickets_for_product(sess, product_id: int) -> list:
    """(PLD-1472) 상품 → 복권 티켓 매핑(active). [{"ticketType": str, "count": int}, ...]. 없으면 []."""
    rows = (
        sess.execute(
            select(ProductVoucherGrant)
            .where(
                ProductVoucherGrant.product_id == product_id,
                ProductVoucherGrant.active.is_(True),
            )
            .order_by(ProductVoucherGrant.ticket_type)
        )
        .scalars()
        .all()
    )
    return [
        {"ticketType": r.ticket_type, "count": r.count}
        for r in rows
        if r.count and r.count > 0
    ]


def _planet_str(planet_id) -> str:
    """planet_id(LargeBinary) → hex 문자열('0x...')."""
    if isinstance(planet_id, (bytes, bytearray, memoryview)):
        return bytes(planet_id).decode()
    return str(planet_id)


def _make_jwt() -> str:
    """포탈 gameBackendApiHandler용 서버간 JWT(HS256, 1분 만료)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {"iat": now, "exp": now + datetime.timedelta(minutes=1), "iss": "iap"},
        config.portal_iap_jwt_secret,
        algorithm="HS256",
    )


def _post_grant(payload: dict) -> Tuple[bool, Optional[str], bool]:
    """
    포탈 grant 호출. 반환 (terminal_ok, ref, transient):
      - terminal_ok=True  → GRANTED로 종료(success/already granted/amount too small)
      - transient=True     → 재시도(PENDING 유지): 5xx·인증(401/403)·레이트리밋(429)·타임아웃(408) 또는 'voucher disabled'
      - 둘 다 False         → FAILED(그 외 4xx = 검증오류, 재시도해도 동일)
    """
    resp = requests.post(
        config.portal_grant_url,
        json=payload,
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
    if body.get("message") == "voucher disabled":
        return False, None, True  # 킬스위치 off — 활성화 후 재발급
    return True, f"granted={body.get('granted')}", False


def _alert(text: str) -> None:
    """운영 알림(best-effort). 실패해도 태스크 진행을 막지 않음."""
    url = config.iap_alert_webhook_url
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        logger.warning("voucher grant alert failed", error=str(e))


@app.task(
    name="iap.voucher_grant",
    bind=True,
    acks_late=True,
    queue="background_job_queue",
)
def grant_vouchers(self):
    """검증된 결제에 대한 포탈 바우처 발급 트리거(beat, */2분)."""
    if not config.voucher_grant_enabled:
        return "voucher grant disabled"
    if not (config.portal_grant_url and config.portal_iap_jwt_secret):
        logger.warning("voucher grant not configured (url/secret missing)")
        return "not configured"

    grantable = _grantable_stores()
    sess = scoped_session(sessionmaker(bind=engine))
    enrolled = granted = failed = 0
    try:
        # (A) enroll — 적격 영수증(실스토어) 중 아웃박스 없는 건을 PENDING으로.
        #   ⚠️ 스토어 필터를 SQL에 둠: skip 대상(REDEEM 등)을 Python에서 거르면 아웃박스가 안 생겨
        #      매 회차 재조회되어 limit 윈도우를 침전·starve시킨다(리뷰 지적).
        conditions = [
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status == TxStatus.SUCCESS,
            Receipt.product_id.isnot(None),
            Receipt.store.in_(grantable),
            # 바우처 발급 대상 상품만(active 티켓 매핑 존재) — 미대상 상품이 윈도우 침전하지 않게.
            Receipt.product_id.in_(
                select(ProductVoucherGrant.product_id).where(
                    ProductVoucherGrant.active.is_(True)
                )
            ),
            Receipt.id.notin_(select(VoucherGrantOutbox.receipt_id)),
        ]
        # 타임스탬프 컷오프(설정 시): 이 시각(created_at) 이후 결제만 대상 — 과거 소급 방지.
        if config.voucher_grant_cutoff is not None:
            conditions.append(Receipt.created_at >= config.voucher_grant_cutoff)
        eligible = (
            sess.execute(
                select(Receipt).where(*conditions).order_by(Receipt.id).limit(ENROLL_BATCH)
            )
            .scalars()
            .all()
        )
        for r in eligible:
            try:
                with sess.begin_nested():  # SAVEPOINT — 레이스 시 이 행만 롤백
                    sess.add(VoucherGrantOutbox(receipt_id=r.id))
                enrolled += 1
            except IntegrityError:
                pass  # 이미 등록됨(동시 실행) — 무시
        sess.commit()

        # (B) dispatch — PENDING 아웃박스를 포탈 grant로. 행 잠금(skip_locked)으로 동시 실행 중복 방지.
        pendings = (
            sess.execute(
                select(VoucherGrantOutbox)
                .where(VoucherGrantOutbox.status == VoucherGrantStatus.PENDING)
                .order_by(VoucherGrantOutbox.receipt_id)
                .limit(DISPATCH_BATCH)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for ob in pendings:
            # 행별 격리 — 한 건의 예상외 예외가 배치 전체를 롤백/중단시키지 않게.
            try:
                r = sess.scalar(select(Receipt).where(Receipt.id == ob.receipt_id))
                if r is None:
                    ob.status = VoucherGrantStatus.FAILED
                    ob.last_error = "receipt not found"
                    failed += 1
                    continue

                # dispatch 시점 상태 재검증 — enroll 이후 환불/무효 전이 시 발급 금지(종단).
                if r.status != ReceiptStatus.VALID or r.tx_status != TxStatus.SUCCESS:
                    ob.status = VoucherGrantStatus.FAILED
                    ob.last_error = (
                        f"receipt no longer grantable: status={r.status} tx={r.tx_status}"
                    )
                    failed += 1
                    continue

                platform = platform_for_store(Store(r.store))
                if platform is None:
                    # 실스토어 아님(설정/데이터 이상) — enroll 필터상 도달 어려우나 방어적 종단.
                    ob.status = VoucherGrantStatus.FAILED
                    ob.last_error = f"non-grantable store: {r.store}"
                    failed += 1
                    continue

                tickets = (
                    tickets_for_product(sess, r.product_id) if r.product_id else []
                )
                if not tickets:
                    # 티켓 매핑이 아직 미설정/비활성일 수 있음 → 종단 아닌 재시도(PENDING 유지).
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = "no active voucher ticket mapping (retry)"
                    continue

                payload = {
                    "iapUuid": str(r.uuid),
                    "receiptId": r.id,
                    "agentAddress": r.agent_addr,
                    "planetId": _planet_str(r.planet_id),
                    "tickets": tickets,
                    "platform": platform,  # 통계용
                    "purchasedAt": (r.purchased_at or r.created_at).isoformat(),
                }
                try:
                    ok, ref, transient = _post_grant(payload)
                except requests.RequestException as e:
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = f"http error: {e}"[:500]
                    continue  # transient — PENDING 유지

                if ok:
                    ob.status = VoucherGrantStatus.GRANTED
                    ob.portal_ref = ref
                    ob.granted_at = datetime.datetime.now(datetime.timezone.utc)
                    granted += 1
                elif transient:
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = (
                        f"transient (retry): {ref}" if ref else "transient (retry)"
                    )
                else:
                    ob.status = VoucherGrantStatus.FAILED
                    ob.attempts = (ob.attempts or 0) + 1
                    ob.last_error = ref or "grant failed"
                    failed += 1
            except Exception as e:  # noqa: BLE001
                # 예상외 예외(비정상 데이터 등) — 이 행만 재시도로 남기고 배치는 계속.
                ob.attempts = (ob.attempts or 0) + 1
                ob.last_error = f"unexpected: {e}"[:500]
        sess.commit()

        # stall 경보 — transient(5xx/인증/티켓매핑 미설정)로 무한 재시도 중인 PENDING은 failed에 안 잡히므로
        #   attempts 임계 이상 PENDING 백로그를 별도 집계해 알림(결제 유효 유저의 미지급 침전 가시화).
        stalled = (
            sess.scalar(
                select(func.count())
                .select_from(VoucherGrantOutbox)
                .where(
                    VoucherGrantOutbox.status == VoucherGrantStatus.PENDING,
                    VoucherGrantOutbox.attempts >= ALERT_ATTEMPTS,
                )
            )
            or 0
        )

        result = f"enrolled={enrolled} granted={granted} failed={failed} stalled={stalled}"
        logger.info("voucher grant run", result=result)
        if failed > 0 or stalled > 0:
            # FAILED(종단·무재시도) + stall(무한 재시도) — 미지급이 침묵으로 굳지 않도록 알림.
            _alert(
                f"[voucher-grant] 미지급 주의: failed={failed} "
                f"stalled(attempts>={ALERT_ATTEMPTS})={stalled}. {result}"
            )
        return result
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.remove()
