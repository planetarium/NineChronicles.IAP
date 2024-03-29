"""Add TIME_LIMIT receipt status

Revision ID: 32e8805e8364
Revises: 73e03cbf8ba2
Create Date: 2023-11-20 16:45:02.560711

"""
import sqlalchemy as sa
from sqlalchemy import Text

from alembic import op

# revision identifiers, used by Alembic.
revision = '32e8805e8364'
down_revision = '73e03cbf8ba2'
branch_labels = None
depends_on = None

old_enum = (
    "INIT", "VALIDATION_REQUEST", "VALID", "REFUNDED+_BY_ADMIN", "INVALID", "REFUNDED_BY_BUYER",
    "PURCHASE_LIMIT_EXCEED",
    "UNKNOWN")
new_enum = sorted(old_enum + ("TIME_LIMIT",))

old_status = sa.Enum(*old_enum, name="receiptstatus")
new_status = sa.Enum(*new_enum, name="receiptstatus")
tmp_status = sa.Enum(*new_enum, name="_receiptstatus")

receipt_table = sa.sql.table(
    "receipt",
    sa.Column("status", new_status, nullable=False),
    sa.Column("msg", Text, nullable=False)
)


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    tmp_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE _receiptstatus USING status::text::_receiptstatus")
    old_status.drop(op.get_bind(), checkfirst=False)
    new_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE receiptstatus USING status::text::receiptstatus")
    tmp_status.drop(op.get_bind(), checkfirst=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute(receipt_table.update()
               .where(receipt_table.c.status.in_(['TIME_LIMIT']))
               .values(status="VALID", msg="TIME_LIMIT")
               )
    tmp_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE _receiptstatus USING status::text::_receiptstatus")
    new_status.drop(op.get_bind(), checkfirst=False)
    old_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE receiptstatus USING status::text::receiptstatus")
    tmp_status.drop(op.get_bind(), checkfirst=False)
    # ### end Alembic commands ###
