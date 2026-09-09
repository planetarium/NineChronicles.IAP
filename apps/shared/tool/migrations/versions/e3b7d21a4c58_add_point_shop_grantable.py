"""Add product.point_shop_grantable + grant_outbox created_at index (PLD-1575)

Revision ID: e3b7d21a4c58
Revises: a7c31f5b9e02
Create Date: 2026-09-09 00:00:00

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && DATABASE_URI=... alembic upgrade head

## 왜 두 변경이 한 리비전인가
둘 다 PLD-1575 머니 가드의 저장 요건이고, 따로 두면 "플래그는 있는데 카운트 인덱스가 없는"
중간 상태가 생긴다. 둘 다 온라인 DDL 로 안전하다(아래 참고).

## ⚠️ 배포 순서: **이 마이그레이션이 새 이미지보다 먼저**
`product` 에 컬럼을 추가하고 모델에도 넣었으므로, 마이그레이션 없이 새 이미지가 뜨면
`Product` 를 SELECT 하는 **모든** 경로(상품 목록·구매·통계 = 유상 결제 포함)가
`UndefinedColumn` 으로 죽는다. 직전 리비전(a7c31f5b9e02)은 신규 테이블이라 새 코드만
깨졌지만 이번엔 범위가 결제까지다. 롤백도 같은 이유로 역순(이미지 먼저, downgrade 나중).

## point_shop_grantable
- `NOT NULL DEFAULT false` — **기존 상품 전부가 화이트리스트 밖**에서 시작한다(fail-closed).
- ⚠️ 이 DB 는 **PostgreSQL 10** 이다(2026-08 receipt 인덱스 작업 때 확인). PG11+ 의
  "상수 default 는 rewrite 없음" 최적화가 **적용되지 않는다** → 테이블 rewrite +
  `ACCESS EXCLUSIVE`. `product` 는 작아서 실 소요는 짧지만, product 를 조인하는 장기 쿼리
  (`/stats/product-sales` 등) 뒤에 잠금이 큐잉되면 그동안 product 읽기가 전부 막힌다.
  그래서 `lock_timeout` 을 걸어 **기다리다 막는 대신 빨리 실패**하게 한다(재시도하면 된다).
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
    # 잠금 대기로 product 읽기를 세우지 않는다 — 못 잡으면 이 트랜잭션만 실패하고(리비전 미적용)
    #   장기 쿼리가 끝난 뒤 다시 돌리면 된다. `SET LOCAL` 이라 같은 커넥션의 다음 리비전엔
    #   영향이 없다(alembic 은 리비전을 트랜잭션으로 감싼다).
    op.execute("SET LOCAL lock_timeout = '3s'")
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
