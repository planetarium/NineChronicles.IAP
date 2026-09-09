"""
지급 계정(KMS 지갑)의 tx nonce 채번 — **영수증 경로와 무영수증 경로가 하나의 규칙을 본다.**

## 왜 이 모듈이 생겼나 (PLD-1564)
nonce 는 `receipt.nonce` 에 결합돼 있었다. `send_product_task` 는

    nonce = max(노드 nextTxNonce, DB max(receipt.nonce) + 1)

로 정했는데, 무영수증 지급(`grant_outbox`)이 **별도 카운터**를 쓰면 같은 지갑에서 같은 nonce 를
두 번 쓴다(둘 중 하나는 영구히 스테이징 실패한다). 그래서 새 카운터를 만들지 않고 **기존 규칙의
"DB max" 범위만 두 테이블로 넓혔다.** 두 경로가 반드시 이 함수를 통해야 한다.

노드 `nextTxNonce` 만으로는 부족한 이유는 그대로다 — 스테이징된 tx 가 블록에 들어가기 전까지
노드는 옛 nonce 를 돌려주므로, 아직 확정 안 된 DB 의 nonce 를 함께 봐야 한다.

## 경합 — 잠금은 **두 경로가 모두** 잡아야 의미가 있다
`pick_nonce()` 로 값을 고르고 그 행을 커밋하기까지가 위험 구간이다. 한쪽만 잠그면 상대는
"커밋 전이라 안 보이는" 같은 값을 그대로 고른다 → 둘 중 하나가 영구 스테이징 실패한다.
그래서 두 경로 모두 `lock_planet_nonce()` 를 잡는다:

  · 무영수증 경로: 잠금 → DB max 재조회 → 조건부 UPDATE(nonce 선점) → **즉시 커밋**(잠금 해제)
  · 영수증 경로(`send_product`): 잠금 → DB max 재조회 → nonce 지정 → tx 서명 → 커밋(잠금 해제)

잠금은 트랜잭션 스코프라 커밋/롤백에서 자동 해제된다. 영수증 경로는 KMS 서명까지 들고 있어
같은 행성의 채번이 서명 시간만큼 직렬화되지만(이전에도 send_product 동시 실행끼리 경합이
있었다), 그 값이 IAP 처리량(초당 1건 미만)을 제약하지는 않는다. 커밋 순서는 바뀌지 않는다.

노드 조회(nextTxNonce)는 **잠금 밖**에서 한다 — 네트워크 호출을 잠금 안에 두면 상대 경로가
그 시간만큼 막힌다. 값이 조금 스테일해도 DB max 가 미확정 nonce 를 덮으므로 안전하다.
"""

import zlib
from typing import Optional, Union

from shared.models.grant_outbox import GrantOutbox
from shared.models.receipt import Receipt
from sqlalchemy import func, select

PlanetKey = Union[bytes, bytearray, memoryview]

# 자문 잠금 네임스페이스(임의 상수). 같은 DB 의 다른 잠금과 겹치지 않게 첫 인자를 고정한다.
NONCE_LOCK_NAMESPACE = 1564


def as_bytes(planet_id: PlanetKey) -> bytes:
    """LargeBinary/PlanetID/memoryview 를 dict 키로 쓸 수 있는 bytes 로."""
    if isinstance(planet_id, (bytes, bytearray, memoryview)):
        return bytes(planet_id)
    return bytes(planet_id, "utf-8")


def max_db_nonce(sess, planet_id: PlanetKey) -> Optional[int]:
    """
    해당 행성에서 **DB 가 아는** 최대 nonce. receipt·grant_outbox 양쪽의 max. 없으면 None.

    한쪽만 보면 다른 경로가 쓴 nonce 를 재발급한다 — 이 함수의 존재 이유다.
    """
    planet = as_bytes(planet_id)
    receipt_max = sess.scalar(
        select(func.max(Receipt.nonce)).where(Receipt.planet_id == planet)
    )
    grant_max = sess.scalar(
        select(func.max(GrantOutbox.nonce)).where(GrantOutbox.planet_id == planet)
    )
    candidates = [x for x in (receipt_max, grant_max) if x is not None]
    return max(candidates) if candidates else None


def pick_nonce(node_next_nonce: int, db_max_nonce: Optional[int]) -> int:
    """
    노드가 말하는 다음 nonce 와 DB 가 아는 최대 nonce 중 안전한 쪽.

    `send_product` 가 쓰던 `max(노드, DB max + 1)` 과 같은 식이다.
    """
    if db_max_nonce is None:
        return node_next_nonce
    return max(node_next_nonce, db_max_nonce + 1)


def lock_planet_nonce(sess, planet_id: PlanetKey) -> bool:
    """
    행성별 nonce 채번 자문 잠금(PG 트랜잭션 스코프). 잠갔으면 True.

    PG 가 아니면(테스트용 sqlite 등) no-op 으로 False 를 돌려준다 — 잠금 없이도 로직은 돌아야 한다.
    커밋/롤백 시 자동 해제되므로 채번→커밋 구간만 감싸는 용도로 쓴다.
    """
    try:
        dialect = sess.get_bind().dialect.name
    except Exception:  # noqa: BLE001 — 바인드를 못 얻는 세션(모의 객체 등)
        return False
    if dialect != "postgresql":
        return False
    key = zlib.crc32(as_bytes(planet_id)) & 0x7FFFFFFF
    sess.execute(select(func.pg_advisory_xact_lock(NONCE_LOCK_NAMESPACE, key)))
    return True
