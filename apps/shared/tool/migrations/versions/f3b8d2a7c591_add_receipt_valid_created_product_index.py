"""Add partial index for voucher grant enroll (created_at, product_id)

Revision ID: f3b8d2a7c591
Revises: e5a9c3d71f42
Create Date: 2026-10-23 10:00:00.000000

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && alembic upgrade head

**워커 이미지보다 먼저** 적용한다. 순서가 뒤집혀도 오류는 없지만, 인덱스가 없으면 새 정렬
(`ORDER BY created_at, id`)이 컷오프 이후 구간을 순차로 읽는다(예전 PK 전체 스캔보다는 적다).

바우처 enroll(`grant_vouchers`, beat 2분마다)이 `status='VALID' AND created_at >= 컷오프 AND
product_id IN (발급 대상 상품) ... ORDER BY id LIMIT 500` 이었다. 평시에는 적격 영수증이 전부
이미 아웃박스에 있어 결과가 0건인데, 플래너가 PK 순서로 1번부터 훑으며 걸러서 0건을 확인하려고
receipt 를 끝까지 읽었다(메인넷: 86만 행 / 힙 1.4GB, 90초에 PK 스캔 32회·86만 행 페치,
iap_db 디스크 읽기 ~5,000 blk/s). PG 10 shared_buffers 128MB 를 같이 쓰는 포탈·펫팝이
그 사이 P1001/P2024/P2028 을 냈다(2026-10-22).

    status = 'VALID' 부분 인덱스 (created_at, product_id)

코드가 정렬을 `(created_at, id)` 로 바꿔 이 인덱스로 컷오프 이후 구간만 읽는다. product_id 를
키에 넣어 대상 상품 필터를 인덱스 안에서 끝내므로 힙은 적격 후보만 읽는다.

- CONCURRENTLY 라서 테이블을 잠그지 않는다. 빌드가 힙을 두 번 훑으므로 **저트래픽 시간대에**.
- 실패하면 INVALID 인덱스가 남는다 → `upgrade()` 끝에서 `indisvalid` 를 확인한다. 거짓이면:
      DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_valid_created_product;
"""
import sqlalchemy as sa
from alembic import op

revision = "f3b8d2a7c591"
down_revision = "e5a9c3d71f42"
branch_labels = None
depends_on = None

INDEX = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_valid_created_product
    ON receipt (created_at, product_id)
 WHERE status = 'VALID'
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(INDEX)
    valid = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indisvalid FROM pg_index "
                "WHERE indexrelid = 'ix_receipt_valid_created_product'::regclass"
            )
        )
        .scalar()
    )
    if not valid:
        raise RuntimeError(
            "ix_receipt_valid_created_product 가 INVALID 다 — DROP INDEX CONCURRENTLY 후 다시 실행할 것"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_valid_created_product")
