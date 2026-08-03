"""
(PLD-1469/1472) NCG Voucher 지급 트리거.

검증 완료(VALID) + 상품 지급 성공(tx SUCCESS)한 결제를 폴링해 포탈 grant를 호출하는 beat 태스크.
복잡한 send_product handle()을 건드리지 않고 아웃박스(voucher_grant_outbox)로 디커플링 — 멱등·재시도.

흐름:
  (A) enroll: cutoff 이후 VALID+SUCCESS+실스토어 영수증 중 아직 아웃박스 없는 건 → PENDING 아웃박스 생성(레이스는 SAVEPOINT로 흡수).
  (B) dispatch: PENDING 아웃박스 → platform/amountUsd 유도 → 포탈 grant 호출 → GRANTED / 재시도 / FAILED.

멱등: 아웃박스 receipt_id UNIQUE + 포탈 grant 자체가 iapUuid 멱등. 포탈 policy.enabled=false면 'voucher disabled'로
      반환되며, 이 경우 아웃박스는 PENDING 유지(활성화 후 재발급).
"""

import datetime
from decimal import Decimal
from typing import Optional, Tuple

import jwt
import requests
import structlog
from shared.enums import ReceiptStatus, Store, TxStatus, VoucherGrantStatus
from shared.models.product import Price
from shared.models.receipt import Receipt
from shared.models.voucher_grant_outbox import VoucherGrantOutbox
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(
    config.pg_dsn, pool_size=5, max_overflow=10, pool_recycle=3600, pool_pre_ping=True
)

# 실 결제 스토어 → 바우처 플랫폼. TEST/REDEEM은 바우처 대상 아님(None).
_MOBILE_STORES = {Store.APPLE, Store.APPLE_TEST, Store.GOOGLE, Store.GOOGLE_TEST}
_PC_STORES = {Store.WEB, Store.WEB_TEST}

HTTP_TIMEOUT = 10
ENROLL_BATCH = 500
DISPATCH_BATCH = 200


def platform_for_store(store: Store) -> Optional[str]:
    """(PLD-1472) 스토어 → 플랫폼. WEB=PC, APPLE/GOOGLE=MOBILE. TEST/REDEEM=None(대상 아님)."""
    if store in _PC_STORES:
        return "PC"
    if store in _MOBILE_STORES:
        return "MOBILE"
    return None


def usd_amount_for_product(sess, product_id: int) -> Optional[Decimal]:
    """(PLD-1472) 상품 USD 가격(WEB 스토어=canonical USD). 없거나 <=0이면 None."""
    price = sess.scalar(
        select(Price).where(
            Price.product_id == product_id,
            Price.currency == "USD",
            Price.store == Store.WEB,
        )
    )
    if price is None or price.price is None or Decimal(str(price.price)) <= 0:
        return None
    return Decimal(str(price.price))


def _planet_str(planet_id) -> str:
    """planet_id(LargeBinary) → hex 문자열('0x...')."""
    if isinstance(planet_id, (bytes, bytearray, memoryview)):
        return bytes(planet_id).decode()
    return str(planet_id)


def _make_jwt() -> str:
    """포탈 gameBackendApiHandler용 서버간 JWT(HS256, 1분 만료)."""
    now = datetime.datetime.utcnow()
    return jwt.encode(
        {"iat": now, "exp": now + datetime.timedelta(minutes=1), "iss": "iap"},
        config.portal_iap_jwt_secret,
    )


def _post_grant(payload: dict) -> Tuple[bool, Optional[str], bool]:
    """
    포탈 grant 호출. 반환 (terminal_ok, ref, transient):
      - terminal_ok=True  → GRANTED로 종료(success/already granted/amount too small)
      - transient=True     → 재시도(PENDING 유지): 5xx 또는 'voucher disabled'(아직 미활성)
      - 둘 다 False         → FAILED(4xx 검증오류 등, 재시도해도 동일)
    """
    resp = requests.post(
        config.portal_grant_url,
        json=payload,
        headers={"Authorization": f"Bearer {_make_jwt()}"},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 500:
        return False, f"{resp.status_code}", True
    if resp.status_code != 200:
        return False, f"{resp.status_code}:{resp.text[:200]}", False
    body = resp.json()
    msg = body.get("message", "")
    if msg == "voucher disabled":
        return False, None, True  # 킬스위치 off — 활성화 후 재발급
    return True, f"granted={body.get('granted')}", False


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

    sess = scoped_session(sessionmaker(bind=engine))
    enrolled = granted = failed = 0
    try:
        # (A) enroll — 적격 영수증 중 아웃박스 없는 건을 PENDING으로.
        eligible = (
            sess.execute(
                select(Receipt)
                .where(
                    Receipt.id > config.voucher_grant_cutoff_receipt_id,
                    Receipt.status == ReceiptStatus.VALID,
                    Receipt.tx_status == TxStatus.SUCCESS,
                    Receipt.product_id.isnot(None),
                    Receipt.id.notin_(select(VoucherGrantOutbox.receipt_id)),
                )
                .order_by(Receipt.id)
                .limit(ENROLL_BATCH)
            )
            .scalars()
            .all()
        )
        for r in eligible:
            if platform_for_store(Store(r.store)) is None:
                continue  # TEST/REDEEM 등 — 아웃박스도 만들지 않음(다음 회차에도 스킵)
            try:
                with sess.begin_nested():  # SAVEPOINT — 레이스 시 이 행만 롤백
                    sess.add(VoucherGrantOutbox(receipt_id=r.id))
                enrolled += 1
            except IntegrityError:
                pass  # 이미 등록됨(동시 실행) — 무시
        sess.commit()

        # (B) dispatch — PENDING 아웃박스를 포탈 grant로.
        pendings = (
            sess.execute(
                select(VoucherGrantOutbox)
                .where(VoucherGrantOutbox.status == VoucherGrantStatus.PENDING)
                .order_by(VoucherGrantOutbox.receipt_id)
                .limit(DISPATCH_BATCH)
            )
            .scalars()
            .all()
        )
        for ob in pendings:
            r = sess.scalar(select(Receipt).where(Receipt.id == ob.receipt_id))
            if r is None:
                ob.status = VoucherGrantStatus.FAILED
                ob.last_error = "receipt not found"
                failed += 1
                continue
            platform = platform_for_store(Store(r.store))
            amount_usd = (
                usd_amount_for_product(sess, r.product_id) if r.product_id else None
            )
            if platform is None or amount_usd is None:
                ob.status = VoucherGrantStatus.FAILED
                ob.last_error = f"platform={platform} amount_usd={amount_usd}"
                failed += 1
                continue

            payload = {
                "iapUuid": str(r.uuid),
                "receiptId": r.id,
                "agentAddress": r.agent_addr,
                "planetId": _planet_str(r.planet_id),
                "amountUsd": float(amount_usd),
                "platform": platform,
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
                ob.last_error = "transient (retry)"
            else:
                ob.status = VoucherGrantStatus.FAILED
                ob.attempts = (ob.attempts or 0) + 1
                ob.last_error = ref or "grant failed"
                failed += 1
        sess.commit()

        result = f"enrolled={enrolled} granted={granted} failed={failed}"
        logger.info("voucher grant run", result=result)
        return result
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.remove()
