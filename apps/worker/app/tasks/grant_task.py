"""
(PLD-1564) 영수증 없는 범용 지급 워커 — 포탈 포인트샵 주문을 온체인 `grant_items` 로 내보낸다.

`send_product_task` 와 **같은 조립 로직**을 쓴다(`shared.utils.grant`) — 구성품→티커 변환,
GrantItems, unsigned tx, KMS 서명. 다른 것은 추적 단위뿐이다: 저쪽은 `receipt`, 이쪽은
`grant_outbox`(영수증이 없으므로).

흐름:
  (A) `iap.send_grant` — API 가 아웃박스 행을 만들 때 즉시 1건 처리(지연 최소화).
  (B) `iap.grant_track` — beat(*/1분). 두 가지를 한다.
      · dispatch : 아직 tx 를 못 낸 PENDING 행(메시지 유실·브로커 장애·노드 다운 재시도)
      · track    : 스테이징된 tx 의 확정 추적 → SUCCESS 면 GRANTED(+granted_at)
      (`tracker.py` 는 receipt 만 본다 — 아웃박스는 여기서 추적해야 한다.)

멱등(이중 tx 금지):
  · `external_ref` UNIQUE 로 1 주문 = 1 행.
  · 진입 시 이미 GRANTED/SUCCESS 면 즉시 종료.
  · 한 번 만든 서명 tx(`row.tx`)와 nonce 는 **재사용**한다. 재시도는 같은 tx 를 다시
    스테이징할 뿐이라 체인에서 같은 tx id 로 수렴한다(중복 지급 없음).

nonce: `shared.utils.nonce` 의 통합 규칙을 쓴다 — receipt·grant_outbox 양쪽의 DB max 와 노드
  nextTxNonce 중 안전한 값. 채번 구간만 PG 자문 잠금으로 감싸고 **즉시 커밋**해 다른 워커에게
  보인다(그 모듈 docstring 참고).

운영 메모:
  · FAILED 는 포탈의 환급 신호다. 수동 재구동이 필요하면 `status=PENDING, attempts=0` 으로
    되돌리면 다음 beat 가 **같은 tx**(같은 nonce)를 다시 스테이징한다 — 새 tx 를 만들지 않으니
    이중 지급 위험이 없다. `tx`/`nonce` 를 지우면 새 tx 가 나가므로 지우지 말 것.
  · ⚠️ 남는 위험 하나: 스테이징 응답만 유실되고 tx 는 노드가 받은 경우. tx_id 를 못 받아
    추적이 안 되고, 재시도가 MAX 를 넘기면 FAILED(=포탈 환급)로 굳는데 tx 는 뒤늦게 블록에
    들어갈 수 있다. 같은 tx 를 계속 재스테이징하므로 대개 다음 회차에 tx_id 를 받아 해소되지만,
    노드가 장시간 응답 불능이면 사람이 체인에서 대조해야 한다(memo 의 order 로 역추적).
"""

import datetime
import json
from typing import Any, Dict, Optional, Tuple

import requests
import structlog
from gql.dsl import DSLQuery, dsl_gql
from shared._crypto import Account
from shared._graphql import GQL
from shared.enums import GrantStatus, PlanetID, TxStatus
from shared.models.grant_outbox import GrantOutbox
from shared.models.product import Product
from shared.schemas.message import SendGrantMessage
from shared.utils.grant import build_claim_data, create_grant_items_tx
from shared.utils.nonce import as_bytes, lock_planet_nonce, max_db_nonce, pick_nonce
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import scoped_session, selectinload, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(
    config.pg_dsn, pool_size=5, max_overflow=10, pool_recycle=3600, pool_pre_ping=True
)

# 재시도 소진 기준. 이 횟수 이상 실패하면 FAILED(종단) — 포탈이 그걸 보고 자동 환급한다.
#   너무 크게 잡으면 환급이 늦어지고, 너무 작으면 노드 일시 장애가 환급으로 이어진다.
MAX_ATTEMPTS = 5
DISPATCH_BATCH = 50
TRACK_BATCH = 50
ERROR_MAX_LEN = 500

# 무상 지급에는 결제 프로모션(THOR 2배)을 적용하지 않는다. 수량의 권위는 포탈(포인트 차감분)이고,
#   IAP 는 productId 구성품을 그대로 지급만 한다.
GRANT_MULTIPLIER = 1


def _planet(row: GrantOutbox) -> PlanetID:
    return PlanetID(as_bytes(row.planet_id))


def _gql(planet_id: PlanetID) -> GQL:
    return GQL(config.converted_gql_url_map[planet_id], config.headless_jwt_secret)


def node_next_nonce(planet_id: PlanetID, address: str) -> int:
    """노드의 nextTxNonce. 실패(-1)는 예외로 올려 재시도 대상으로 만든다."""
    nonce = _gql(planet_id).get_next_nonce(address)
    if nonce == -1:
        raise ValueError(f"Failed to get nonce from node for planet {planet_id}")
    return nonce


def stage_grant_tx(row: GrantOutbox) -> Tuple[bool, str, Optional[str]]:
    """서명된 tx 를 노드에 스테이징. 노드 장애도 (False, msg, None) 으로 눌러 재시도로 넘긴다."""
    try:
        return _gql(_planet(row)).stage(bytes.fromhex(row.tx))
    except Exception as e:  # noqa: BLE001
        msg = f"Failed to stage tx for {row.external_ref}: {e}"
        logger.error(msg)
        return False, msg, None


def fetch_tx_status(row: GrantOutbox) -> Tuple[Optional[TxStatus], Optional[str]]:
    """
    스테이징한 tx 의 체인 상태. (status, message). `tracker.process` 와 같은 쿼리를 본다.

    조회 자체가 실패하면 (None, 에러) — 상태를 함부로 바꾸지 않고 다음 회차에 다시 본다.
    """
    try:
        client = _gql(_planet(row))
        query = dsl_gql(
            DSLQuery(
                client.ds.StandaloneQuery.transaction.select(
                    client.ds.TransactionHeadlessQuery.transactionResult.args(
                        txId=row.tx_id
                    ).select(
                        client.ds.TxResultType.txStatus,
                        client.ds.TxResultType.blockIndex,
                        client.ds.TxResultType.exceptionNames,
                    )
                )
            )
        )
        resp = client.execute(query)
        if "errors" in resp:
            return None, json.dumps(resp["errors"])[:ERROR_MAX_LEN]
        result = resp["transaction"]["transactionResult"]
        exceptions = json.dumps(result.get("exceptionNames"))
        try:
            return TxStatus[result["txStatus"]], exceptions
        except KeyError:
            return None, f"unknown txStatus: {result.get('txStatus')} {exceptions}"
    except Exception as e:  # noqa: BLE001
        return None, f"tx status query failed: {e}"[:ERROR_MAX_LEN]


def load_product(sess, product_id: int) -> Optional[Product]:
    """구성품까지 로드된 상품. selectinload 인 이유는 send_product 와 같다(joinedload NULL 혼합 이슈)."""
    return sess.scalar(
        select(Product)
        .options(selectinload(Product.fav_list))
        .options(selectinload(Product.fungible_item_list))
        .where(Product.id == product_id)
    )


def assign_nonce(
    sess, row: GrantOutbox, account, *, next_nonce_fn=node_next_nonce
) -> int:
    """
    행에 nonce 를 채번하고 **즉시 커밋**한다(다른 워커·send_product 가 DB max 로 보게).

    자문 잠금은 트랜잭션 스코프라 이 커밋으로 풀린다 — 잠금을 들고 KMS 서명까지 가지 않는다.
    """
    planet_id = _planet(row)
    lock_planet_nonce(sess, row.planet_id)
    node_nonce = next_nonce_fn(planet_id, account.address)
    row.nonce = pick_nonce(node_nonce, max_db_nonce(sess, row.planet_id))
    sess.add(row)
    sess.commit()
    return row.nonce


_account: Optional[Account] = None


def get_account() -> Account:
    """KMS 서명 계정(프로세스 내 재사용). 지급 지갑은 receipt 경로와 **같은 계정**이다."""
    global _account
    if _account is None:
        _account = Account(config.kms_key_id)
    return _account


def _fail(row: GrantOutbox, error: str) -> str:
    row.status = GrantStatus.FAILED
    row.last_error = error[:ERROR_MAX_LEN]
    return f"failed: {error}"


def _retry(row: GrantOutbox, error: str) -> str:
    """재시도 기록. MAX 소진 시 종단(FAILED) — 포탈이 환급 신호로 읽는다."""
    row.attempts = (row.attempts or 0) + 1
    row.last_error = error[:ERROR_MAX_LEN]
    if row.attempts >= MAX_ATTEMPTS:
        row.status = GrantStatus.FAILED
        return f"failed (attempts exhausted): {error}"
    return f"retry ({row.attempts}/{MAX_ATTEMPTS}): {error}"


def process_grant(
    sess,
    row: GrantOutbox,
    *,
    account=None,
    next_nonce_fn=node_next_nonce,
    stage_fn=stage_grant_tx,
) -> str:
    """
    아웃박스 1행을 온체인으로. 반환값은 로그용 요약 문자열.

    이미 성공한 행이면 아무것도 하지 않는다(이중 tx 금지). 서명 tx·nonce 는 한 번 만들면
    재사용하고, 재시도는 **스테이징만** 다시 한다.
    """
    if row.status == GrantStatus.GRANTED or row.tx_status == TxStatus.SUCCESS:
        return "already granted"
    if row.tx_id and row.tx_status not in (TxStatus.INVALID, TxStatus.NOT_FOUND):
        # 스테이징까지 끝났고 확정 대기 중 — track 이 처리한다.
        return "already staged"

    account = account or get_account()
    try:
        if row.tx is None:
            product = load_product(sess, row.product_id)
            if product is None:
                return _commit(sess, _fail(row, f"product {row.product_id} not found"))
            claim_data = build_claim_data(product, multiplier=GRANT_MULTIPLIER)
            if not claim_data:
                # 빈 지급 tx 는 "성공했는데 아무것도 안 준" 최악의 결과가 된다 → 종단 실패.
                return _commit(
                    sess,
                    _fail(row, f"product {row.product_id} has no grantable components"),
                )
            if row.nonce is None:
                assign_nonce(sess, row, account, next_nonce_fn=next_nonce_fn)
            row.tx = create_grant_items_tx(
                account=account,
                planet_id=_planet(row),
                avatar_addr=row.avatar_addr,
                claim_data=claim_data,
                nonce=row.nonce,
                memo=row.memo,
            ).hex()
            row.tx_status = TxStatus.CREATED
            sess.add(row)
            sess.commit()
    except Exception as e:  # noqa: BLE001 — 노드/KMS/데이터 이상 전부 재시도 대상
        sess.rollback()
        row = sess.merge(row)
        return _commit(sess, _retry(row, f"tx creation failed: {e}"))

    ok, msg, tx_id = stage_fn(row)
    if ok:
        row.tx_id = tx_id
        row.tx_status = TxStatus.STAGED
        # status 는 PENDING 유지 — GRANTED 는 체인 확정(SUCCESS) 후에만.
        result = f"staged: {tx_id}"
        logger.info(
            "grant staged",
            external_ref=row.external_ref,
            tx_id=tx_id,
            nonce=row.nonce,
            product_id=row.product_id,
            avatar_addr=row.avatar_addr,
        )
    else:
        result = _retry(row, f"stage failed: {msg}")
        logger.warning("grant stage failed", external_ref=row.external_ref, error=msg)
    return _commit(sess, result)


def _commit(sess, result: str) -> str:
    sess.commit()
    return result


def track_grant(sess, row: GrantOutbox, *, status_fn=fetch_tx_status) -> str:
    """스테이징된 tx 의 확정 추적. SUCCESS→GRANTED, FAILURE→FAILED, INVALID/NOT_FOUND→재시도."""
    tx_status, msg = status_fn(row)
    if tx_status is None:
        # 조회 실패는 상태를 바꾸지 않는다(노드 장애로 지급을 종단시키면 안 된다).
        logger.warning(
            "grant tx status unknown", external_ref=row.external_ref, error=msg
        )
        return "unknown"

    row.tx_status = tx_status
    if tx_status == TxStatus.SUCCESS:
        row.status = GrantStatus.GRANTED
        row.granted_at = datetime.datetime.now(datetime.timezone.utc)
        row.last_error = None
        logger.info(
            "grant confirmed",
            external_ref=row.external_ref,
            tx_id=row.tx_id,
            product_id=row.product_id,
            avatar_addr=row.avatar_addr,
        )
        result = "granted"
    elif tx_status == TxStatus.FAILURE:
        # 체인이 거부한 액션 — 같은 tx 를 다시 넣어도 결과는 같다(종단).
        result = _fail(row, f"tx failed on chain: {msg}")
    elif tx_status in (TxStatus.INVALID, TxStatus.NOT_FOUND):
        # 아직 체인에 안 들어갔음(멤풀 탈락 등) — 같은 tx 를 다시 스테이징한다.
        result = _retry(row, f"tx {tx_status.name}: {msg}")
    else:
        result = f"{tx_status.name}"  # STAGED 등 — 다음 회차에 다시 본다
    return _commit(sess, result)


def _alert(text: str) -> None:
    """운영 알림(best-effort). 실패해도 태스크 진행을 막지 않음."""
    url = config.iap_alert_webhook_url
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.warning("grant alert failed", error=str(e))


def pending_dispatch_query(limit: int = DISPATCH_BATCH):
    """tx 를 아직 못 낸(또는 멤풀에서 탈락한) PENDING 행. 오래된 것부터."""
    return (
        select(GrantOutbox)
        .where(
            GrantOutbox.status == GrantStatus.PENDING,
            GrantOutbox.attempts < MAX_ATTEMPTS,
            or_(
                GrantOutbox.tx_id.is_(None),
                GrantOutbox.tx_status.in_((TxStatus.INVALID, TxStatus.NOT_FOUND)),
            ),
        )
        .order_by(GrantOutbox.id)
        .limit(limit)
    )


def pending_track_query(limit: int = TRACK_BATCH):
    """스테이징돼 확정 대기 중인 행."""
    return (
        select(GrantOutbox)
        .where(
            GrantOutbox.status == GrantStatus.PENDING,
            GrantOutbox.tx_id.isnot(None),
            GrantOutbox.tx_status == TxStatus.STAGED,
        )
        .order_by(GrantOutbox.id)
        .limit(limit)
    )


@app.task(
    name="iap.send_grant",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    priority=0,
    queue="product_queue",
)
def send_grant(self, message: Dict[str, Any]) -> str:
    """아웃박스 1건 즉시 처리(API 가 행 생성 직후 호출)."""
    sess = scoped_session(sessionmaker(bind=engine))
    try:
        parsed = SendGrantMessage.model_validate(message)
        row = sess.scalar(
            select(GrantOutbox).where(GrantOutbox.external_ref == parsed.external_ref)
        )
        if row is None:
            # 행이 없으면 재시도해도 없다(포탈 요청 없이 온 메시지). 조용히 끝낸다.
            logger.warning(
                "grant outbox row not found", external_ref=parsed.external_ref
            )
            return "not found"
        result = process_grant(sess, row)
        logger.info("send grant", external_ref=parsed.external_ref, result=result)
        return result
    except Exception as exc:
        sess.rollback()
        logger.error("Error processing send grant", message=message, exc_info=exc)
        self.retry(exc=exc)
    finally:
        sess.remove()


@app.task(
    name="iap.grant_track",
    bind=True,
    acks_late=True,
    queue="background_job_queue",
)
def track_grants(self) -> str:
    """미완료 아웃박스 재시도 + 스테이징 tx 확정 추적(beat)."""
    sess = scoped_session(sessionmaker(bind=engine))
    dispatched = granted = newly_failed = 0
    try:
        for row in sess.scalars(pending_dispatch_query()).all():
            try:
                process_grant(sess, row)
                dispatched += 1
                if row.status == GrantStatus.FAILED:
                    newly_failed += 1
            except Exception as e:  # noqa: BLE001 — 한 행이 배치를 죽이지 않게
                sess.rollback()
                logger.error(
                    "grant dispatch error", external_ref=row.external_ref, error=str(e)
                )

        for row in sess.scalars(pending_track_query()).all():
            try:
                result = track_grant(sess, row)
                if result == "granted":
                    granted += 1
                elif row.status == GrantStatus.FAILED:
                    newly_failed += 1
            except Exception as e:  # noqa: BLE001
                sess.rollback()
                logger.error(
                    "grant track error", external_ref=row.external_ref, error=str(e)
                )

        failed_total = (
            sess.scalar(
                select(func.count())
                .select_from(GrantOutbox)
                .where(GrantOutbox.status == GrantStatus.FAILED)
            )
            or 0
        )
        result = (
            f"dispatched={dispatched} granted={granted} "
            f"newly_failed={newly_failed} failed_total={failed_total}"
        )
        logger.info("grant track run", result=result)
        if newly_failed:
            # 포탈이 FAILED 를 보고 자동 환급하지만, IAP 쪽 원인(노드·KMS·상품설정)은 사람이 봐야 한다.
            _alert(f"[grant] 지급 종단 실패 {newly_failed}건. {result}")
        return result
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.remove()
