"""(PLD-1562) 뽑기 풀에 FAV 상금 — kind/ticker/decimal_places

v1 풀을 아이템 전용으로 좁힌 건 잘못된 범위 설정이었다. 지급 가능한 건 아이템만이 아니다 —
룬스톤·소울스톤·크리스탈이 전부 FAV 축이고, 고정 상품은 `fav_list` 로 이미 그걸 준다.
뽑기라고 상금 종류가 좁을 이유가 없다.

온체인에서는 아이템도 FAV 도 `FungibleAssetValue`(티커+자릿수+수량)라 `ticker` 한 컬럼으로
합친다. 다만 **`kind` 를 따로 둔다** — 머니 가드가 FAV 를 얼로우리스트와 FAV 전용 상한으로
따로 보기 때문이고, 그 분기를 티커 접두어(`FAV__`)로 추론하면 접두어 관례 하나에 뚫린다.

`fungible_item_id` → `ticker` 로 옮긴다. 이 테이블은 같은 날 만들어졌고 인터널 테스트 행만
있어(prod 0행) 데이터 손실 위험이 없다. 기존 행은 전부 아이템이므로 kind='ITEM' 으로 채운다.

Revision ID: e9b3c07d5a18
Revises: d7f2a9c14e36
Create Date: 2026-09-11

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e9b3c07d5a18"
down_revision = "d7f2a9c14e36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ① 새 컬럼. server_default 를 주므로 기존 행이 NOT NULL 을 바로 만족한다
    #    (이 테이블은 인터널 테스트 행 수준이라 재작성 비용이 무의미하다).
    op.add_column(
        "product_gacha_entry",
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            server_default="ITEM",
            comment="'ITEM' | 'FAV'. 머니 가드의 분기가 이 값으로 갈린다",
        ),
    )
    op.add_column(
        "product_gacha_entry",
        sa.Column(
            "decimal_places",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="FAV 자릿수. 아이템은 항상 0",
        ),
    )

    # ② fungible_item_id → ticker. 아이템도 FAV 도 온체인에선 같은 티커 축이다.
    op.alter_column(
        "product_gacha_entry", "fungible_item_id", new_column_name="ticker"
    )

    # ③ FAV 는 아이템 sheet id 가 없다 → nullable 로.
    op.alter_column("product_gacha_entry", "sheet_item_id", nullable=True)

    # ④ 유니크 키를 티커 기준으로 교체(이름도 의미에 맞춘다).
    op.drop_constraint(
        "uq_product_gacha_entry_item", "product_gacha_entry", type_="unique"
    )
    op.create_unique_constraint(
        "uq_product_gacha_entry_ticker", "product_gacha_entry", ["product_id", "ticker"]
    )

    # ⑤ 값 무결성. 앱이 아니라 DB 가 막는다 — 머니 경로라 "한 군데서만 검사"로는 부족하다.
    op.create_check_constraint(
        "ck_product_gacha_entry_kind",
        "product_gacha_entry",
        "kind in ('ITEM', 'FAV')",
    )
    op.create_check_constraint(
        "ck_product_gacha_entry_decimal_places",
        "product_gacha_entry",
        "decimal_places >= 0",
    )
    # 아이템엔 아이콘 sheet id 가 있어야 하고 FAV 엔 없어야 한다. 섞이면 화면이 없는
    # 아이콘을 그리거나(FAV 에 sheet id) 빈 칸이 된다(아이템에 NULL).
    op.create_check_constraint(
        "ck_product_gacha_entry_sheet_id",
        "product_gacha_entry",
        "(kind = 'ITEM') = (sheet_item_id IS NOT NULL)",
    )


def downgrade() -> None:
    # ⚠️ FAV 칸이 있는 채로 내리면 되돌릴 곳이 없다(아이템 전용 스키마로 못 담는다).
    #    되돌리기 전에 FAV 칸을 지우거나 덤프할 것.
    op.drop_constraint(
        "ck_product_gacha_entry_sheet_id", "product_gacha_entry", type_="check"
    )
    op.drop_constraint(
        "ck_product_gacha_entry_decimal_places", "product_gacha_entry", type_="check"
    )
    op.drop_constraint(
        "ck_product_gacha_entry_kind", "product_gacha_entry", type_="check"
    )
    op.drop_constraint(
        "uq_product_gacha_entry_ticker", "product_gacha_entry", type_="unique"
    )
    op.create_unique_constraint(
        "uq_product_gacha_entry_item",
        "product_gacha_entry",
        ["product_id", "fungible_item_id"],
    )
    op.alter_column("product_gacha_entry", "sheet_item_id", nullable=False)
    op.alter_column(
        "product_gacha_entry", "ticker", new_column_name="fungible_item_id"
    )
    op.drop_column("product_gacha_entry", "decimal_places")
    op.drop_column("product_gacha_entry", "kind")
