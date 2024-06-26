"""Add package_name into Receipt table

Revision ID: 065b2b11e898
Revises: f6de778b7fe3
Create Date: 2024-04-25 11:54:30.925518

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '065b2b11e898'
down_revision = 'f6de778b7fe3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('receipt', sa.Column('package_name', sa.Text(), nullable=False,
                                       server_default='com.planetariumlabs.ninechroniclesmobile'))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('receipt', 'package_name')
    # ### end Alembic commands ###
