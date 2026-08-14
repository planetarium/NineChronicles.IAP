"""Add voucher_grant_outbox table (PLD-1468)

Revision ID: 8db0d254c89d
Revises: b1d5e1dc71ea
Create Date: 2026-08-03 00:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8db0d254c89d"
down_revision = "b1d5e1dc71ea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (PLD-1468) NCG Voucher 아웃박스. status는 EnumType(VoucherGrantStatus) = Integer 백엔드.
    op.create_table(
        "voucher_grant_outbox",
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("portal_ref", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipt.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", name="uq_voucher_grant_outbox_receipt_id"),
    )
    op.create_index(
        "ix_voucher_grant_outbox_status", "voucher_grant_outbox", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_voucher_grant_outbox_status", table_name="voucher_grant_outbox")
    op.drop_table("voucher_grant_outbox")
