"""add planet_id

Revision ID: b7a685e5ef1c
Revises: d09361e553f0
Create Date: 2023-10-25 21:11:55.913465

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7a685e5ef1c'
down_revision = '4beb3c9fcd4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('receipt', sa.Column('planet_id', sa.LargeBinary(length=12), nullable=True))
    op.execute("UPDATE receipt SET planet_id = '0x000000000000'::bytea")
    op.alter_column('receipt', 'planet_id', nullable=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('receipt', 'planet_id')
    # ### end Alembic commands ###
