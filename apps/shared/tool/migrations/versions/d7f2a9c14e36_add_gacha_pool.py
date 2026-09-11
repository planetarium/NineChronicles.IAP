"""(PLD-1562) 뽑기 풀 — product_gacha_entry + grant_outbox 추첨 결과

상금표는 **지급하는 쪽**에 둔다는 원칙에 따라 뽑기 풀이 IAP 에 온다(복권 상금은 NCG 라
포탈이 지급하므로 표가 포탈에, 뽑기 상금은 온체인 아이템이라 IAP 가 지급하므로 표가 여기).

풀은 **뽑기 상품의 자식 행**이다. 풀 멤버마다 Product 를 만들면 50종 뽑기가 상품 50개가
되고 그걸 목록에서 숨길 플래그를 또 만들어야 한다 — 유령 상품을 안 만들면 숨길 일도 없다.

`grant_outbox` 의 두 컬럼이 **재추첨 불가**를 DB 제약으로 만든다: 추첨은 아웃박스 행을
만들 때 1회 일어나고 결과가 `gacha_result` 에 동결되며, `external_ref` UNIQUE 가
"1 주문 = 1 행"이라 재요청은 같은 행 = 같은 결과다.

Revision ID: d7f2a9c14e36
Revises: c8e1a4f70b62
Create Date: 2026-09-11

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d7f2a9c14e36"
down_revision = "c8e1a4f70b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_gacha_entry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "name", sa.Text(), nullable=False, comment="운영·감사용 칸 이름(화면 라벨 아님)"
        ),
        sa.Column(
            "weight",
            sa.Integer(),
            nullable=False,
            comment="가중치. 확률 = weight / Σweight",
        ),
        sa.Column("sheet_item_id", sa.Integer(), nullable=False),
        sa.Column("fungible_item_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        # TimeStampMixin·형제 마이그레이션(a7c31f5b9e02)과 **같은 모양**으로 둔다.
        # NOT NULL + server_default 로 잡으면 autogenerate 가 영구 드리프트를 보고한다.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # 0 가중치를 허용하면 "넣었는데 절대 안 나오는 칸"이 조용히 생긴다. 0 수량은
        # "성공했는데 아무것도 안 준" 지급이 된다. 둘 다 앱이 아니라 DB 가 막는다.
        sa.CheckConstraint("weight > 0", name="ck_product_gacha_entry_weight_positive"),
        sa.CheckConstraint("amount > 0", name="ck_product_gacha_entry_amount_positive"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 같은 상품에 같은 아이템 칸이 둘이면 CSV 재임포트의 중복 삽입이다.
        sa.UniqueConstraint(
            "product_id", "fungible_item_id", name="uq_product_gacha_entry_item"
        ),
        comment="(PLD-1562) 뽑기 풀의 한 칸. 뽑기 상품이 자기 안에 든다",
    )
    op.create_index(
        "ix_product_gacha_entry_product_id", "product_gacha_entry", ["product_id"]
    )

    # 둘 다 nullable + DEFAULT 없음 → **카탈로그 변경만**이고 테이블 재작성이 없다
    # (PG11 미만에서도 안전하다. IAP 인터널은 15 지만 prod 를 가정하지 않는다).
    op.add_column(
        "grant_outbox",
        sa.Column(
            "gacha_entry_id",
            sa.Integer(),
            nullable=True,
            comment="뽑힌 풀 칸(조회·집계용). 지급 근거는 gacha_result 다",
        ),
    )
    op.add_column(
        "grant_outbox",
        sa.Column(
            "gacha_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="추첨 결과 동결본 + 풀 스냅샷. 워커는 이 값으로만 지급한다",
        ),
    )
    # ⚠️ **SET NULL** 이다. 기본(NO ACTION)이면 한 번이라도 뽑힌 칸은 참조 행 때문에 삭제가
    #    막혀 라이브 풀이 append-only 가 된다(이벤트 아이템 로테이션 첫 회차에 부딪힌다).
    #    CASCADE 도 아니다 — 칸을 지웠다고 지급 이력을 지우면 감사 기록이 사라진다.
    #    SET NULL 이면 지급은 무손실이다: 지급 근거는 `gacha_result` 동결본이고 이 FK 는
    #    "어느 칸이었나"를 조인해 보기 위한 링크일 뿐이라, 끊겨도 결과·수량·확률이 다 남는다.
    op.create_foreign_key(
        "grant_outbox_gacha_entry_id_fkey",
        "grant_outbox",
        "product_gacha_entry",
        ["gacha_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 감사 조인(`어느 칸이 몇 번 나왔나`)과 위 SET NULL 의 삭제 검사가 풀스캔이 되지 않게.
    op.create_index(
        "ix_grant_outbox_gacha_entry_id", "grant_outbox", ["gacha_entry_id"]
    )


def downgrade() -> None:
    # ⚠️ `gacha_result` 를 지운다 = **확률 공시 분쟁의 유일한 증거를 지운다**(그때의 풀
    #    스냅샷이 여기에만 있다). 롤백 전에 덤프를 뜰 것.
    op.drop_index("ix_grant_outbox_gacha_entry_id", table_name="grant_outbox")
    op.drop_constraint(
        "grant_outbox_gacha_entry_id_fkey", "grant_outbox", type_="foreignkey"
    )
    op.drop_column("grant_outbox", "gacha_result")
    op.drop_column("grant_outbox", "gacha_entry_id")
    op.drop_index("ix_product_gacha_entry_product_id", table_name="product_gacha_entry")
    op.drop_table("product_gacha_entry")
