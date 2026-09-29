"""Add grant_outbox (avatar_addr, created_at) index (PLD-1575 아바타 축)

Revision ID: b4d9e1c72f83
Revises: e3b7d21a4c58
Create Date: 2026-09-09 00:00:00

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && DATABASE_URI=... alembic upgrade head

코드 변경 없이도 안전하다 — 인덱스만 추가하므로 앞뒤 어느 이미지에서도 무해하다
(새 이미지는 이 인덱스가 없어도 **정상 동작**하고 카운트만 느려진다). 그래서 직전
리비전(e3b7d21a4c58, `product.point_shop_grantable`)과 달리 **배포 순서 제약이 없다**.

## 왜

아바타 축 시간창 상한(`grant_max_grants_per_avatar_per_hour/day`)과 의미적 중복 감지가
요청 경로에서 이 모양의 카운트를 돈다:

    -- 아바타 축
    SELECT count(*) FROM grant_outbox
     WHERE created_at >= now() - interval '1 day' AND avatar_addr = :addr;
    -- 중복 감지(경고 전용) — 위에 product_id 필터가 하나 더 붙는다
    SELECT count(*) FROM grant_outbox
     WHERE created_at >= now() - interval '60 seconds'
       AND avatar_addr = :addr AND product_id = :pid;

기존 `ix_grant_outbox_created_at` 만으로는 창 안 **모든** 행을 힙에서 읽어 avatar_addr 를
걸러야 한다(전역 count 는 index-only 로 끝나지만 컬럼 필터가 붙으면 못 끝낸다).
그리고 이 카운트들은 `pg_advisory_xact_lock`(app/grant_guard.py) 안에서 돌기 때문에
지연이 곧 **직렬화된 지급 처리량**이다 — 전 지급 요청이 그 뒤에 줄을 선다.

선두 컬럼을 avatar_addr 로 두면 한 아바타의 행만 훑는다. 아바타당 행 수는 아바타 축
상한이 직접 묶으므로(시간당/일당 N건) 스캔 폭에 상한이 있다. product_id 는 키에 넣지
않았다 — 아바타 축(상품 무관) 카운트가 이 인덱스를 그대로 쓰고, 중복 감지는 남은 행이
이미 몇 건 수준이라 필터가 사실상 무료다.

## 잠금

`grant_outbox` 는 (PLD-1564) 신규 테이블이라 프로덕션 행 수가 사실상 0 이다 →
CONCURRENTLY 없이도 잠금 시간이 무시할 만하다(직전 리비전의 `ix_grant_outbox_created_at`
과 같은 판단). 잠기는 대상도 이 테이블 하나뿐이고, 이 테이블을 읽는 경로는 포인트샵
지급/조회뿐이다(결제·정산은 `receipt` 라 무영향).

⚠️ 나중에 이 테이블이 커진 뒤에 신규 DB 를 세우는 게 아니라 **살아 있는 큰 테이블에**
같은 인덱스를 얹어야 한다면, 이 리비전을 고치지 말고 `op.get_context().autocommit_block()`
안에서 `CREATE INDEX CONCURRENTLY IF NOT EXISTS` 로 새 리비전을 쓴다(선례:
d2f4a1c6e8b3 · c1a7f0d3b9e4).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4d9e1c72f83"
down_revision = "e3b7d21a4c58"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_grant_outbox_avatar_addr_created_at"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "grant_outbox",
        ["avatar_addr", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="grant_outbox")
