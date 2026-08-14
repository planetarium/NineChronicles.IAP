"""merge purchase_signal and voucher chains

두 갈래가 같은 부모(b1d5e1dc71ea)에서 갈라져 각각 다른 환경에 이미 적용됐다.
스키마 변경은 없고 그래프만 봉합한다.

    운영(mainnet)  : c1a7f0d3b9e4  — purchase_signal 있음, 바우처 테이블 없음
    인터널          : 9c1e2f3a4b5c  — 바우처 테이블 있음, purchase_signal 없음

이 리비전을 두면 각 환경의 `alembic upgrade head`가 자기에게 없는 쪽만 채우고
같은 지점으로 수렴한다. 반대로 한쪽 체인의 down_revision 을 다른 쪽으로 바꾸는
방식(re-parenting)은 쓰면 안 된다 — 인터널은 이미 9c1e2f3a4b5c 라서 c1a7f0d3b9e4 를
조상으로 간주해 영구히 건너뛰고, purchase_signal 없이 "적용됨"으로 남는다.

Revision ID: 0eb7c95c9f30
Revises: c1a7f0d3b9e4, 9c1e2f3a4b5c
Create Date: 2026-08-14 01:59:25.730772

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0eb7c95c9f30'
down_revision = ('c1a7f0d3b9e4', '9c1e2f3a4b5c')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
