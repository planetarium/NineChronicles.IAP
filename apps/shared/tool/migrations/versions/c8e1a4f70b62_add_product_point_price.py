"""(PLD-1561) product.point_price — 포인트샵 판매가를 IAP 로

Revision ID: c8e1a4f70b62
Revises: b4d9e1c72f83
Create Date: 2026-09-10

포탈이 `shop_sku.price_points` 로 따로 들고 있던 포인트 판매가를 IAP 상품으로 옮긴다.

왜 옮기나: `shop_sku` 는 IAP 가 이미 가진 축을 다시 만든 테이블이었다 —
  price_points ↔ mileage_price / active_from·to ↔ open·close_timestamp
  monthly_cap ↔ account_limit·daily_limit·weekly_limit / 행의 존재 ↔ point_shop_grantable
6 필드 중 4 개가 중복이었고, `mileage_price`(비현금 화폐 가격)가 정확히 같은 모양의 선례다.

옮겨서 실제로 해결되는 것: **포탈에는 SKU 등록·수정 경로가 아예 없었다**(shopSku.create/update
호출 0건, 백오피스 화면 0개 — 인터널 상품도 파드에서 손으로 upsert 했다). IAP 에는 CSV import
와 백오피스 상품 CRUD 가 이미 있으므로, 여기로 오면 기획이 기존 경로로 등록·수정한다.

⚠️ 포인트 차감·환급은 여전히 포탈이 한다(포인트 원장은 포탈 소유). IAP 는 **값만** 안다.

비용: nullable INTEGER 를 DEFAULT 없이 추가한다 → **카탈로그만 고친다.** PG10(prod)에서도
테이블 rewrite 가 없다(rewrite 가 나는 건 `ADD COLUMN ... DEFAULT x` 이고 그건 PG11+ fast
default 이전 얘기다). 인터널은 PG 15.12.

백필하지 않는다: NULL = "포인트로 팔지 않음" 이 올바른 기본값이다. 기존 상품 전부가 그 상태다.
"""

from alembic import op
import sqlalchemy as sa

revision = "c8e1a4f70b62"
down_revision = "b4d9e1c72f83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column(
            "point_price",
            sa.Integer(),
            nullable=True,
            comment="(PLD-1561) 포탈 포인트샵 판매가(표시 포인트). NULL = 포인트로 팔지 않음.",
        ),
    )


def downgrade() -> None:
    op.drop_column("product", "point_price")
