"""Add partial index for the stuck-receipt monitors

Revision ID: d2f4a1c6e8b3
Revises: 0eb7c95c9f30
Create Date: 2026-08-25 17:40:00.000000

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && alembic upgrade head

코드 변경은 없다. 인덱스만 추가하는 마이그레이션이라 앞뒤 어느 이미지에서도 안전하다.

## 왜

"밀린 영수증"을 세는 감시 쿼리 3개가 전부 receipt 전체(74만 행 / 힙 1.4GB)를 순차
스캔한다. PG 버퍼가 128MB뿐이라 캐시에 남아 있으면 0.25초, 밀려나면 15~40초가 걸려서
API 감시가 간헐적으로 타임아웃 알람을 냈다(2026-08-25 알람).

    1. GET /api/purchase/invalid-receipt-count  (외부 감시)
       status='VALID' AND (tx_status IN ('INVALID','STAGED','FAILURE') OR tx_status IS NULL)
    2. check_halt_tx      (status_monitor, 10분마다)   tx_status IN ('INVALID','STAGED')
    3. track_tx           (tracker, 1분마다)           tx_status IN ('STAGED','INVALID')

기존 부분 인덱스로는 1번의 OR 조건을 못 탄다. ix_receipt_null_txstatus 는 IS NULL 쪽만,
ix_receipt_retry_pending 은 CREATED/INVALID + tx IS NOT NULL 만 커버한다.

## 무엇을

조건을 그대로 담은 부분 인덱스 하나로 3개를 다 태운다. 2·3번은 IN 목록이 더 좁아서
플래너가 "좁은 IN ⊂ (넓은 IN OR IS NULL)" 을 증명해 같은 인덱스를 쓴다(PG 10 확인).
키에 tx_status 를 같이 넣은 이유는 2·3번이 tx_status 를 Index Cond 로 처리해 힙을
안 읽게 하려는 것이다(112kB 더 쓰고 힙 페치 3,103 → 96 블록).

## 실측 (PG 10.15 로컬 재현: 743,043행 / 힙 1,451MB — 메인넷 1,449MB 와 동형)

    쿼리                     before                        after
    invalid-receipt-count    Seq Scan  185,875 blocks      Index Scan    532 blocks
    check_halt_tx            Seq Scan  202,136 cost          "            96 blocks
    track_tx                 Parallel Seq Scan 743k행        "            96 blocks
    인덱스 크기              -                             392 kB (12,016행)

메인넷 실측은 순차 스캔 시 shared read=174,905 blocks / 15.5초(EXPLAIN ANALYZE)였다.

## 주의

CONCURRENTLY 라서 테이블을 잠그지 않는다(라이브 결제 흐름 무영향). 대신 실패하면
INVALID 인덱스가 남을 수 있으니, 실패 시 DROP INDEX 후 재실행한다:

    SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "d2f4a1c6e8b3"
down_revision = "0eb7c95c9f30"
branch_labels = None
depends_on = None

# 조건은 apps/api/app/api/purchase.py:check_invalid_receipt 의 필터와 글자 그대로
# 같아야 한다. IN 목록 순서까지 같아야 플래너가 부분 인덱스를 매칭한다.
STUCK_MONITOR_INDEX = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_stuck_monitor
    ON receipt (created_at, tx_status)
 WHERE status = 'VALID'
   AND (tx_status IN ('INVALID', 'STAGED', 'FAILURE') OR tx_status IS NULL)
"""

# 아래 둘은 2026-08-24 에 메인넷에 손으로 만든 것이라 코드에는 없었다. 여기서 IF NOT
# EXISTS 로 같이 선언해 메인넷에서는 no-op 이 되게 하고, 인터널/신규 DB 에서도 retryer
# (get_pending_receipts / get_null_tx_status_receipts, 1분마다) 가 인덱스를 타게 한다.
RETRYER_INDEXES = [
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_null_txstatus
        ON receipt (created_at)
     WHERE tx_status IS NULL AND status = 'VALID'
    """,
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_retry_pending
        ON receipt (created_at)
     WHERE tx_status IN ('CREATED', 'INVALID') AND tx IS NOT NULL
    """,
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(STUCK_MONITOR_INDEX)
        for stmt in RETRYER_INDEXES:
            op.execute(stmt)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_stuck_monitor")
        # 손으로 만든 두 인덱스는 이 마이그레이션 이전부터 메인넷에 있었으므로 되돌리지 않는다.
