"""Add product.point_shop_grantable + grant_outbox created_at index (PLD-1575)

Revision ID: e3b7d21a4c58
Revises: a7c31f5b9e02
Create Date: 2026-09-09 00:00:00

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && DATABASE_URI=... alembic upgrade head

## 왜 두 변경이 한 리비전인가
둘 다 PLD-1575 머니 가드의 저장 요건이고, 따로 두면 "플래그는 있는데 카운트 인덱스가 없는"
중간 상태가 생긴다. 둘 다 온라인 DDL 로 안전하다(아래 참고).

## point_shop_grantable
- `NOT NULL DEFAULT false` — **기존 상품 전부가 화이트리스트 밖**에서 시작한다(fail-closed).
  PG 11+ 는 상수 default 의 ADD COLUMN 을 테이블 rewrite 없이 처리한다.
- 이 플래그를 켜지 않으면 `POST /api/admin/grant` 는 400 이다. 인터널부터 켜고 검증한 뒤
  메인넷 상품에 켠다(운영 순서는 grant_guard.py 도커스트링 참고).

## ix_grant_outbox_created_at
- 머니 가드의 시간창 카운트(`created_at >= now() - interval`)가 **요청 경로**에서 매번 돈다.
  인덱스 없으면 지급 API 지연이 아웃박스 행 수에 비례해 늘어난다.
- 신규 테이블이라 행이 거의 없어 CONCURRENTLY 없이도 잠금 시간이 무시할 만하다
  (alembic 기본 트랜잭션 안에서 CONCURRENTLY 는 쓸 수 없다).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e3b7d21a4c58"
down_revision = "a7c31f5b9e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column(
            "point_shop_grantable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_grant_outbox_created_at", "grant_outbox", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_grant_outbox_created_at", table_name="grant_outbox")
    op.drop_column("product", "point_shop_grantable")
