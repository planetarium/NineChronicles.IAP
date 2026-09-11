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
    # nullable=False + server_default → 기존 행이 바로 만족한다. PG11+ 는 non-volatile
    #   default 의 ADD COLUMN 이 메타데이터 연산이라 재작성이 없다(실 DB 는 PG15).
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
    op.create_check_constraint(
        "ck_product_gacha_draw_count",
        "product",
        "gacha_draw_count >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_product_gacha_draw_count", "product", type_="check")
    op.drop_column("product", "gacha_draw_count")
