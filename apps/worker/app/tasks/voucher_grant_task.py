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
from shared.enums import (
    ProductType,
    ReceiptStatus,
    Store,
    TxStatus,
    VoucherGrantStatus,
)
from shared.models.product import Product
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


def grantable_product_ids():
    """
    (C6) 바우처 발급 대상 상품 id 서브쿼리 — active 매핑이 있고 **결제 상품(IAP)** 인 것만.

    얼로우리스트다. FREE 는 무료 클레임도 VALID+SUCCESS 영수증을 만들어 결제 0원 발급이 되고,
    MILEAGE 는 그 무료 클레임으로 적립한 마일리지로 사는 상품이라 같은 사슬의 연장이다.
    `!= FREE` 로 두면 MILEAGE 우회가 열리고 컬럼이 나중에 nullable 이 되면 fail-open 한다.

    설정시점 가드(admin PUT / CSV import)와 별개의 2선 방어 — DB 직접수정·구버전 경로,
    그리고 enroll 이후 상품유형이 바뀌는 경우까지 덮는다. enroll 과 dispatch 가 같은 조건을
    쓰도록 여기 한 곳에 둔다.
    """
    return (
        select(ProductVoucherGrant.product_id)
        .join(Product, Product.id == ProductVoucherGrant.product_id)
        .where(
            ProductVoucherGrant.active.is_(True),
            Product.product_type == ProductType.IAP,
        )
    )


def ineligible_active_mappings(sess) -> list:
    """
    (C6) 발급 대상이 아닌 상품유형(FREE·MILEAGE)에 붙어 있는 active 매핑 [(product_id, sku, type), ...].

    grantable_product_ids() 가 걸러내므로 발급은 안 되지만, 제외가 조용하면 운영자는
    "왜 티켓이 안 나오지"를 디버깅하게 된다. 매 회차 경고로 표면화한다(테이블 수십 행 규모).
    """
    rows = sess.execute(
        select(
            ProductVoucherGrant.product_id,
            Product.google_sku,
            Product.product_type,
        )
        .join(Product, Product.id == ProductVoucherGrant.product_id)
        .where(
            ProductVoucherGrant.active.is_(True),
            Product.product_type != ProductType.IAP,
        )
    ).all()
    return [(r[0], r[1], getattr(r[2], "name", r[2])) for r in rows]


def tickets_for_product(sess, product_id: int) -> list:
    """
    (PLD-1472) 상품 → 복권 티켓 매핑(active). [{"ticketType": str, "count": int}, ...]. 없으면 [].

    (C6) 결제 상품(IAP)만. enroll 과 같은 조건을 dispatch 에서도 다시 본다 — enroll 이후에
    상품유형이 IAP→FREE 로 바뀌는 경로가 있어서다(voucher 컬럼이 빈 CSV 행은 매핑을 그대로 두고
    product_type 만 갱신한다). 여기서 []가 되면 기존 "no active mapping (retry)" 분기가 받아
    PENDING 재시도 → stall 경보로 사람에게 도달한다(새 상태전이 불필요).
    """
    rows = (
        sess.execute(
            select(ProductVoucherGrant)
            .join(Product, Product.id == ProductVoucherGrant.product_id)
            .where(
                ProductVoucherGrant.product_id == product_id,
                ProductVoucherGrant.active.is_(True),
                Product.product_type == ProductType.IAP,
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
      - transient=True     → 재시도(PENDING 유지): 5xx·인증(401/403)·레이트리밋(429)·타임아웃(408),
                             'voucher disabled', 또는 포탈이 body.retryable=true로 명시한 설정 불일치(R2).
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
        # (R2) 포탈이 명시적으로 retryable로 표시한 설정 불일치(예: ticket_type이 아직 정책에
        #   반영 안 됨 → 409 ERR-TICKET-TYPE-UNKNOWN)는 종단이 아니라 재시도 대상. 정책이 일관되면
        #   self-heal. 상태코드 관례(4xx=종단)에 의존하지 않고 body.retryable 플래그로 판정.
        retryable = False
        try:
            body = resp.json()
            retryable = isinstance(body, dict) and body.get("retryable") is True
        except ValueError:
            retryable = False
        if retryable:
            return False, f"{resp.status_code}:retryable", True
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
        # (C6) 발급 불가 유형에 붙은 매핑은 아래 enroll 에서 제외된다 — 조용히 무시되지 않게 경고.
        #   ⚠️ 진단 목적이므로 실패가 정상 발급을 막으면 안 된다 → swallow.
        try:
            ineligible = ineligible_active_mappings(sess)
            if ineligible:
                logger.warning(
                    "active voucher mapping on non-IAP product — enroll 제외됨(설정 확인 필요)",
                    mappings=[
                        f"{pid}:{sku or '?'}:{ptype}" for (pid, sku, ptype) in ineligible
                    ],
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("ineligible mapping check failed", error=str(e))

        # (A) enroll — 적격 영수증(실스토어) 중 아웃박스 없는 건을 PENDING으로.
        #   ⚠️ 스토어 필터를 SQL에 둠: skip 대상(REDEEM 등)을 Python에서 거르면 아웃박스가 안 생겨
        #      매 회차 재조회되어 limit 윈도우를 침전·starve시킨다(리뷰 지적).
        conditions = [
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status == TxStatus.SUCCESS,
            Receipt.product_id.isnot(None),
            Receipt.store.in_(grantable),
            # 바우처 발급 대상 상품만(active 매핑 + 결제 상품) — 미대상 상품이 윈도우 침전하지 않게.
            #   (C6) 상품유형 조건은 grantable_product_ids() 한 곳에 둔다(dispatch 와 동일 조건).
            Receipt.product_id.in_(grantable_product_ids()),
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
