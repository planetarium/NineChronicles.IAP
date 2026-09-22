"""(PLD-1562) 10연뽑 — product.gacha_draw_count

한 번 구매가 돌리는 추첨 횟수. 1=단연, 10=10연.

**10연은 별도 SKU 다.** 가격이 다르고(보통 할인), IAP 는 원래 상품마다 자기 구성품 행을
드는 구조라 풀도 SKU 단위다. 풀 공유 포인터를 두면 "어느 상품의 표인가" 가 한 겹 더
생기고 그 간접이 확률 공시·감사에서 그대로 비용이 된다.

기존 상품은 전부 1(단연 또는 뽑기 아님)이라 server_default 로 백필한다. 이번엔
default 를 **남긴다** — `kind` 와 달리 "빠뜨리면 1" 은 fail-safe 방향이다(추첨을 덜 하지
더 하지 않는다). 반대로 떨구면 뽑기와 무관한 기존 상품 INSERT 가 전부 깨진다.

Revision ID: f1c6a82e37d9
Revises: e9b3c07d5a18
Create Date: 2026-09-11

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1c6a82e37d9"
down_revision = "e9b3c07d5a18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable=False + server_default → 기존 행이 바로 만족한다.
    # ⚠️ **이 DB 는 PostgreSQL 10 이다**(2026-08 receipt 인덱스 작업 때 확인). PG11+ 라면
    #   non-volatile default 의 ADD COLUMN 이 메타데이터 연산이지만, PG10 에서는
    #   **테이블 재작성 + ACCESS EXCLUSIVE** 다. `product` 는 작아 실 소요는 짧지만, 장기
    #   쿼리(`/stats/product-sales` 등) 뒤에 큐잉되면 그동안 `product` 읽기가 전부 막힌다
    #   = 결제 포함 전면 정지. 그래서 기다리다 막는 대신 **빨리 실패**하게 한다(재시도하면 된다).
    #   같은 판단을 e3b7d21a4c58 이 먼저 했다 — 세 리비전이 같은 테이블·같은 연산이다.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "product",
        sa.Column(
            "gacha_draw_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="한 번 구매가 돌리는 추첨 횟수. 1=단연, 10=10연",
        ),
    )
    # 0·음수는 "뽑기인데 아무것도 안 뽑는" 상품이 된다 — 지급 API 가 빈 claim 으로 죽거나,
    #   더 나쁘게는 포인트만 받고 아무것도 안 주는 주문이 된다.
    # 상한도 둔다: 추첨은 전 네임스페이스를 직렬화하는 advisory lock **안**에서 돈다.
    #   오타 `100000` 하나면 그 CPU 구간(≈1초) 동안 모든 지급 요청이 줄을 서고, 결과 JSON
    #   도 주문마다 수 MB 씩 영구 저장된다. 실무상 10연이 최대라 넉넉히 100.
    op.create_check_constraint(
        "ck_product_gacha_draw_count",
        "product",
        "gacha_draw_count between 1 and 100",
    )
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
    op.drop_constraint("ck_product_gacha_draw_count", "product", type_="check")
    op.drop_column("product", "gacha_draw_count")
