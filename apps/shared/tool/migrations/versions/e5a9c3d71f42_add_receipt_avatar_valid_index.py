"""Add partial index for per-avatar season-pass purchase counts

Revision ID: e5a9c3d71f42
Revises: c8f4a2e61b09
Create Date: 2026-10-15 14:00:00.000000

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && alembic upgrade head

인덱스만 추가하는 마이그레이션이라 앞뒤 어느 이미지에서도 안전하다. **API 이미지보다 먼저**
적용한다 — 순서가 뒤집혀도 오류는 없지만 그 사이 상점 요청마다 receipt 전체를 훑는다.

## 왜 (PLD-1674)

포탈 상점(`GET /api/product?avatar_addr=`)이 고정 SKU 시즌패스에 "이 아바타가 이번 시즌에
샀는가" 를 싣는다(`app/fixed_pass.py:count_granted_for_avatar`). 상점 요청마다 도는 쿼리인데
receipt 에 avatar_addr 인덱스가 없어서 그대로면 매번 순차 스캔이다. 메인넷 receipt 는
74만 행 / 힙 1.4GB, PG 10 에 shared_buffers 128MB 라 인덱스 없는 상시 쿼리 하나가 버퍼를
밀어내 다른 감시 쿼리까지 15~40초로 늘린다(d2f4a1c6e8b3 의 2026-08-25 사례).

결제 경로의 시즌 한도(`count_granted_in_season`)도 같은 조건이라 같이 인덱스를 탄다.

## 무엇을

    status = 'VALID' 부분 인덱스 (avatar_addr, product_id)

두 쿼리 모두 `avatar_addr = ? AND status = 'VALID' AND (product_id = 고정행 ... OR
product_id = 회차행)` 이다. 키에 product_id 를 넣어 OR 두 갈래를 Index Cond 로 거른다.
`msg IS NULL`·`data->>...` 는 아바타 한 명의 VALID 영수증 몇 건에 대한 힙 필터라 키에
넣지 않는다.

## 주의

CONCURRENTLY 라서 테이블을 잠그지 않는다(라이브 결제 흐름 무영향). 대신 실패하면
INVALID 인덱스가 남을 수 있으니, 실패 시 DROP INDEX 후 재실행한다:

    SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5a9c3d71f42"
down_revision = "c8f4a2e61b09"
branch_labels = None
depends_on = None

AVATAR_VALID_INDEX = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_avatar_valid
    ON receipt (avatar_addr, product_id)
 WHERE status = 'VALID'
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(AVATAR_VALID_INDEX)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_avatar_valid")
