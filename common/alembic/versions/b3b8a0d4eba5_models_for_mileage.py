"""Models for mileage

Revision ID: b3b8a0d4eba5
Revises: 7161042128cc
Create Date: 2024-10-08 19:39:36.689559

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b3b8a0d4eba5'
down_revision = '7161042128cc'
branch_labels = None
depends_on = None

old_product_type_enum = postgresql.ENUM("SINGLE", "PACKAGE", name="producttype")
product_type_enum = postgresql.ENUM("IAP", "FREE", "MILEAGE", name="producttype")

old_receipt_status_enum = ("INIT", "VALIDATION_REQUEST", "VALID", "REFUNDED_BY_ADMIN", "INVALID", "REFUNDED_BY_BUYER",
                           "REQUIRED_LEVEL", "PURCHASE_LIMIT_EXCEED", "TIME_LIMIT", "UNKNOWN")
new_receipt_status_enum = sorted(old_receipt_status_enum + ("NOT_ENOUGH_MILEAGE",))

old_receipt_status = sa.Enum(*old_receipt_status_enum, name="receiptstatus")
new_receipt_status = sa.Enum(*new_receipt_status_enum, name="receiptstatus")
tmp_receipt_status = sa.Enum(*new_receipt_status_enum, name="_receiptstatus")

receipt_table = sa.sql.table(
    "receipt",
    sa.Column("status", new_receipt_status, nullable=False)
)


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    ## Delete unused
    old_product_type_enum.drop(op.get_bind(), checkfirst=False)
    product_type_enum.create(op.get_bind(), checkfirst=False)

    ## Create new table
    op.create_table('mileage',
                    sa.Column('agent_addr', sa.Text(), nullable=False),
                    sa.Column('planet_id', sa.LargeBinary(length=12), nullable=False),
                    sa.Column('mileage', sa.Integer(), nullable=False),
                    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('planet_id', 'agent_addr', name='unique_planet_agent')
                    )
    op.create_index('ix_mileage_agent_planet', 'mileage', ['planet_id', 'agent_addr'], unique=False)

    ## Update existing tables
    tmp_receipt_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE _receiptstatus USING status::text::_receiptstatus")
    old_receipt_status.drop(op.get_bind(), checkfirst=False)
    new_receipt_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE receiptstatus USING status::text::receiptstatus")
    tmp_receipt_status.drop(op.get_bind(), checkfirst=False)

    op.create_foreign_key("fk_fungible_item_product_product_id", 'fungible_item_product', 'product', ['product_id'],
                          ['id'])
    op.add_column('product', sa.Column('product_type', product_type_enum, nullable=False, server_default="IAP"))
    op.add_column('product', sa.Column('mileage', sa.Integer(), server_default='0', nullable=False))
    op.add_column('product', sa.Column('mileage_price', sa.Integer(), nullable=True))
    op.drop_column('product', 'is_free')

    op.add_column('receipt', sa.Column('mileage_change', sa.Integer, server_default='0', nullable=False))
    op.add_column('receipt', sa.Column('mileage_result', sa.Integer, server_default='0', nullable=False))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('receipt', 'mileage_result')
    op.drop_column('receipt', 'mileage_change')

    op.add_column('product', sa.Column('is_free', sa.BOOLEAN(), default=False, server_default="false", nullable=False))
    op.drop_column('product', 'mileage_price')
    op.drop_column('product', 'mileage')
    op.drop_column('product', 'product_type')
    op.drop_constraint("fk_fungible_item_product_product_id", 'fungible_item_product', type_='foreignkey')
    op.drop_index('ix_mileage_agent_planet', table_name='mileage')
    op.drop_table('mileage')
    product_type_enum.drop(op.get_bind(), checkfirst=False)
    old_product_type_enum.create(op.get_bind(), checkfirst=False)

    op.execute(receipt_table.update()
               .where(receipt_table.c.status.in_(["NOT_ENOUGH_MILEAGE"]))
               .values(status='INVALID')
               )
    tmp_receipt_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE _receiptstatus USING status::text::_receiptstatus")
    new_receipt_status.drop(op.get_bind(), checkfirst=False)
    old_receipt_status.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE receipt ALTER COLUMN status TYPE receiptstatus USING status::text::receiptstatus")
    tmp_receipt_status.drop(op.get_bind(), checkfirst=False)
    # ### end Alembic commands ###
