"""(PLD-1562) product_gacha_entry.slot_key — 칸의 정체성을 티커에서 분리

기획(포인트샵 상품표 v0.9) §1.1 의 재료 티어는 **아이템 5종을 수량 2단계로 쪼갠 9칸**이다
(모래시계 8,000개 21% + 25,000개 6%, AP 스톤 25개 18% + 80개 5% …). 그런데 기존 UNIQUE 는
`(product_id, ticker)` 였고 CSV upsert 키도 같아서, 같은 티커의 두 번째 행이 첫 번째를
**갱신해 버린다** — 임포트는 성공하고 9칸이 5칸이 된 채 확률만 기획과 달라진다. 확률표는
등록 순간에 틀리면 유저가 뽑은 뒤에야 드러나므로, 표현 자체가 되게 만들어야 한다.

`amount` 를 UNIQUE 에 더하는 안(A)은 **수량 수정이 갱신이 아니라 신규 삽입**이 된다 —
옛 칸을 지우지 않으면 총 가중치가 늘어 확률 전체가 어긋난다. 그래서 칸의 정체성을 산출물이
아니라 **표에서의 자리**로 옮긴다(안 B).

기존 행은 `slot_key = ticker` 로 백필한다. 옛 시트(slot_key 컬럼 없음)는 티커가 곧 키라
그대로 돌고, 정체성도 그대로 유지된다.

⚠️ downgrade 는 같은 티커가 둘 이상인 상품이 있으면 UNIQUE 복구에서 실패한다. 정상이다 —
   내려가려면 그 칸들을 먼저 정리해야 한다(조용히 한쪽을 버리는 것이 더 나쁘다).

Revision ID: b2d94f6c15a8
Revises: a4e8b1f905c7
Create Date: 2026-09-18

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2d94f6c15a8"
down_revision = "a4e8b1f905c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) nullable 로 추가 → 백필 → NOT NULL. server_default 는 두지 않는다 —
    #    빠뜨린 INSERT 가 조용히 빈 문자열 칸이 되면 그 상품의 모든 칸이 한 칸으로 합쳐진다.
    op.add_column(
        "product_gacha_entry",
        sa.Column(
            "slot_key",
            sa.Text(),
            nullable=True,
            comment="칸의 정체성(표에서의 자리). upsert 키 — 산출물이 아니다",
        ),
    )
    op.execute("UPDATE product_gacha_entry SET slot_key = ticker")
    op.alter_column("product_gacha_entry", "slot_key", nullable=False)

    # 2) UNIQUE 축 교체. 두 DDL 사이의 순서는 무관하고(서로 다른 컬럼이다), 중요한 건
    #    **이 마이그레이션 뒤에야** 같은 티커 두 칸이 들어갈 수 있다는 것이다.
    #    백필이 옛 UNIQUE 를 깰 수는 없다 — (product_id, ticker) 가 유일했으므로
    #    (product_id, slot_key=ticker) 도 유일하다.
    op.drop_constraint(
        "uq_product_gacha_entry_ticker", "product_gacha_entry", type_="unique"
    )
    op.create_unique_constraint(
        "uq_product_gacha_entry_slot", "product_gacha_entry", ["product_id", "slot_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_product_gacha_entry_slot", "product_gacha_entry", type_="unique"
    )
    op.create_unique_constraint(
        "uq_product_gacha_entry_ticker", "product_gacha_entry", ["product_id", "ticker"]
    )
    op.drop_column("product_gacha_entry", "slot_key")
