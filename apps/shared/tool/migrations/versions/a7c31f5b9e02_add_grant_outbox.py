"""Add grant_outbox table (PLD-1564)

Revision ID: a7c31f5b9e02
Revises: a5f3c8d21b7e
Create Date: 2026-09-09 00:00:00

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && DATABASE_URI=... alembic upgrade head

## enum 타입
- `status` 는 `EnumType(GrantStatus)` = **Integer 백엔드**라 PG 타입 생성이 없다
  (`voucher_grant_outbox.status` 선례와 동일 — 0/1/2 정수로 저장).
- `tx_status` 는 **기존 PG enum `txstatus` 를 재사용**한다(receipt 와 같은 어휘).
  그래서 `create_type=False` 로 참조만 하고 CREATE TYPE 을 내지 않는다. 이 타입은
  이 리비전의 조상(3e29896ac79d / 57e65ed34bd6)에서 이미 만들어지므로 신규 DB 에서도 존재한다.
  downgrade 에서 타입을 지우지 않는 이유도 같다 — receipt 가 아직 쓴다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a7c31f5b9e02"
down_revision = "a5f3c8d21b7e"
branch_labels = None
depends_on = None

# 이미 존재하는 `txstatus` 를 참조만 한다(create_type=False). 라벨 목록은 receipt 마이그레이션
#   (88d48811f7a9)과 글자 그대로 같아야 한다 — 다르면 PG 가 타입 재정의를 요구한다.
TX_STATUS = postgresql.ENUM(
    "CREATED",
    "STAGED",
    "SUCCESS",
    "FAILURE",
    "INVALID",
    "NOT_FOUND",
    "FAIL_TO_CREATE",
    "UNKNOWN",
    name="txstatus",
    create_type=False,
)


def upgrade() -> None:
    # (PLD-1564) 영수증 없는 범용 지급 아웃박스. external_ref UNIQUE = 1 주문 = 1 tx(멱등).
    op.create_table(
        "grant_outbox",
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("planet_id", sa.LargeBinary(length=12), nullable=False),
        sa.Column("avatar_addr", sa.Text(), nullable=False),
        sa.Column("agent_addr", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tx", sa.Text(), nullable=True),
        sa.Column("nonce", sa.Integer(), nullable=True),
        sa.Column("tx_id", sa.Text(), nullable=True),
        sa.Column("tx_status", TX_STATUS, nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_ref", name="uq_grant_outbox_external_ref"),
    )
    # 미완료 폴링(status=PENDING)용 — voucher_grant_outbox 선례.
    op.create_index("ix_grant_outbox_status", "grant_outbox", ["status"], unique=False)
    # tx 상태 추적/역추적용(receipt.tx_id 와 같은 관례).
    op.create_index("ix_grant_outbox_tx_id", "grant_outbox", ["tx_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_grant_outbox_tx_id", table_name="grant_outbox")
    op.drop_index("ix_grant_outbox_status", table_name="grant_outbox")
    op.drop_table("grant_outbox")
    # `txstatus` enum 은 receipt 가 계속 쓰므로 지우지 않는다.
