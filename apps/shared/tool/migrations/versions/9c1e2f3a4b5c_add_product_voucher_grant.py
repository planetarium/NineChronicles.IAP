"""Add product_voucher_grant table (PLD-1472)

Revision ID: 9c1e2f3a4b5c
Revises: 8db0d254c89d
Create Date: 2026-08-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9c1e2f3a4b5c"
down_revision = "8db0d254c89d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (PLD-1472) 상품 → 복권 티켓 매핑. (product_id, ticket_type) 별 1행, active=false면 발급 제외.
    op.create_table(
        "product_voucher_grant",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("ticket_type", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        # UNIQUE(product_id, ticket_type) 복합 btree가 product_id 선두 조회를 커버 → 별도 단일 인덱스 불요.
        sa.UniqueConstraint("product_id", "ticket_type", name="uq_product_voucher_grant"),
    )


def downgrade() -> None:
    op.drop_table("product_voucher_grant")
