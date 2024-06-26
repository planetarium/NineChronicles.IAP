"""Delete unused models

Revision ID: 1ab63d3081f4
Revises: 3e29896ac79d
Create Date: 2023-06-12 17:29:14.333582

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1ab63d3081f4'
down_revision = '3e29896ac79d'
branch_labels = None
depends_on = None

box_status = sa.Enum("CREATED", "MESSAGE_SENT", "TX_CREATED", "TX_STAGED", "SUCCESS", "FAIL", "ERROR", name="boxstatus")


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('box_item')
    op.drop_index('ix_item_id', table_name='item')
    op.drop_table('item')
    op.drop_table('box')
    box_status.drop(op.get_bind(), checkfirst=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('box',
                    sa.Column('name', sa.TEXT(), autoincrement=False, nullable=False),
                    sa.Column('price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
                    sa.Column('status',
                              postgresql.ENUM('CREATED', 'MESSAGE_SENT', 'TX_CREATED', 'TX_STAGED', 'SUCCESS', 'FAIL',
                                              'ERROR', name='boxstatus'), autoincrement=False, nullable=False),
                    sa.Column('id', sa.INTEGER(), server_default=sa.text("nextval('box_id_seq'::regclass)"),
                              autoincrement=True, nullable=False),
                    sa.PrimaryKeyConstraint('id', name='box_pkey'),
                    postgresql_ignore_search_path=False
                    )
    op.create_table('item',
                    sa.Column('id', sa.INTEGER(), server_default=sa.text("nextval('item_id_seq'::regclass)"),
                              autoincrement=True, nullable=False),
                    sa.Column('name', sa.TEXT(), autoincrement=False, nullable=True),
                    sa.PrimaryKeyConstraint('id', name='item_pkey'),
                    postgresql_ignore_search_path=False
                    )
    op.create_index('ix_item_id', 'item', ['id'], unique=False)
    op.create_table('box_item',
                    sa.Column('box_id', sa.INTEGER(), autoincrement=False, nullable=False),
                    sa.Column('item_id', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('count', sa.INTEGER(), autoincrement=False, nullable=False),
                    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
                    sa.ForeignKeyConstraint(['box_id'], ['box.id'], name='box_item_box_id_fkey'),
                    sa.ForeignKeyConstraint(['item_id'], ['item.id'], name='box_item_item_id_fkey'),
                    sa.PrimaryKeyConstraint('box_id', 'id', name='box_item_pkey')
                    )
    # ### end Alembic commands ###
