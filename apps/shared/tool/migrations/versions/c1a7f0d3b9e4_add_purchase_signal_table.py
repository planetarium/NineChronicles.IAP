"""Add purchase_signal table

Revision ID: c1a7f0d3b9e4
Revises: b1d5e1dc71ea
Create Date: 2026-08-13 00:00:00.000000

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c1a7f0d3b9e4"
down_revision = "b1d5e1dc71ea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_signal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("purchase_token", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("planet_id", sa.Text(), nullable=True),
        sa.Column("agent_addr", sa.Text(), nullable=True),
        sa.Column("avatar_addr", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipt.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_token", name="uq_purchase_signal_purchase_token"),
    )
    op.create_index(
        op.f("ix_purchase_signal_uuid"), "purchase_signal", ["uuid"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_signal_status"), "purchase_signal", ["status"], unique=False
    )

    # 배치가 "이 purchaseToken에 대응하는 영수증이 있나"를 묻는다.
    # 구글 영수증은 data->>'TransactionID' 가 purchaseToken 과 같은 값이다.
    # receipt는 70만 행 이상이라 CONCURRENTLY로 만든다(테이블 잠금 회피).
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_data_transaction_id "
            "ON receipt ((data->>'TransactionID'))"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_data_transaction_id")
    op.drop_index(op.f("ix_purchase_signal_status"), table_name="purchase_signal")
    op.drop_index(op.f("ix_purchase_signal_uuid"), table_name="purchase_signal")
    op.drop_table("purchase_signal")
