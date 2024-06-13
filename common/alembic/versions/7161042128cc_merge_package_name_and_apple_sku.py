"""Merge PackageName and Apple SKU for K

Revision ID: 7161042128cc
Revises: 065b2b11e898, 3378efa82b6c
Create Date: 2024-05-10 16:20:34.292377

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7161042128cc'
down_revision = ('065b2b11e898', '3378efa82b6c')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
