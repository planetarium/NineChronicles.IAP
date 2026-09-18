"""(PLD-1564) product.point_payable_kinds — 결제 가능 포인트 종류

기획(포인트샵 상품표 v0.9)이 **가챠·확정교환 = PP-X 전용 / 주간·아카이브 = PP-S·PP-X 모두**
를 요구한다. PP-X 는 기존 포탈 포인트(= 우리 `RewardKind.NCG`)고, PP-S 는 샵 전용
무상 포인트다. 즉 "이 상품을 어떤 포인트로 살 수 있는가" 축이 다시 필요하다.

포탈에 `shop_sku.payable_kinds` 로 있다가 PLD-1561 에서 지웠다 — "종류가 둘뿐이고 PP_S
발급 경로가 없어 아무 차이를 못 만들면서 설정 실수의 자리만 만들었다"는 이유였다.
**그 판단이 틀렸다.** 기획 문서 부록 C.5 는 이 제약을 *확률보다 강한 가드*로 쓴다 —
가챠를 NCG 전용으로 두면 체크인 적립만 하는 층(봇 주 서식지)이 가챠에 아예 못 닿는다.
지울 때 적어 둔 대로 **IAP 상품 컬럼으로** 되살린다(판매조건은 IAP 소유).

기존 상품은 전부 'ANY'(제약 없음 = 현행 동작)로 백필한다. server_default 를 **남긴다** —
빠뜨린 INSERT 가 'ANY' 가 되는 건 "덜 막는" 방향이라 fail-open 처럼 보이지만, 반대로
떨구면 포인트샵과 무관한 기존 상품 INSERT 가 전부 깨진다. 실제 가드는 가챠 상품에 'NCG'
를 **명시적으로 켜는 것**이고, 그건 CSV 로 한다.

Revision ID: a4e8b1f905c7
Revises: f1c6a82e37d9
Create Date: 2026-09-18

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4e8b1f905c7"
down_revision = "f1c6a82e37d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable=False + server_default → 기존 행이 바로 만족한다. PG11+ 는 non-volatile
    #   default 의 ADD COLUMN 이 메타데이터 연산이라 재작성이 없다(실 DB 는 PG15).
    op.add_column(
        "product",
        sa.Column(
            "point_payable_kinds",
            sa.Text(),
            nullable=False,
            server_default="ANY",
            comment="'ANY'=PP_S 로도 결제 가능 / 'NCG'=현금화 가능 포인트로만",
        ),
    )
    # 모르는 값이 들어오면 포탈이 해석을 못 해 **fail-open**(제약 없음)으로 떨어질 수 있다.
    #   값 집합을 DB 가 막는다 — 머니 경로라 "한 군데서만 검사"로는 부족하다.
    op.create_check_constraint(
        "ck_product_point_payable_kinds",
        "product",
        "point_payable_kinds in ('ANY', 'NCG')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_product_point_payable_kinds", "product", type_="check")
    op.drop_column("product", "point_payable_kinds")
