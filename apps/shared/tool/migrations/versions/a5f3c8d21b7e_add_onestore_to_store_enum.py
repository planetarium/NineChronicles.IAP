"""Add ONESTORE to store enum

Revision ID: a5f3c8d21b7e
Revises: d2f4a1c6e8b3
Create Date: 2026-09-02 14:00:00.000000

배포 시 수동 적용이 필요하다(이미지 기동에 alembic 단계가 없다):

    cd apps/shared && alembic current   # d2f4a1c6e8b3 인지 먼저 확인 (아래 "주의")
    cd apps/shared && alembic upgrade head

## 왜

`Store` 파이썬 enum 에 `ONESTORE`(4) 를 추가했다. `receipt.store`
와 `price.store` 는 PG 네이티브 enum 타입(`store`)이고 **라벨 이름**을 저장하므로
(`models/receipt.py` 의 `values_callable`), DB 쪽 라벨을 같이 늘리지 않으면 원스토어
영수증을 처음 INSERT 하는 순간 `invalid input value for enum store: "ONESTORE"` 로
깨진다. 파이썬 코드만으로는 반쪽이다.

그 첫 INSERT 는 검증기·API 분기(인수인계 문서 3~6단계)가 들어간 뒤에 일어난다. 지금은
`get_order_data` 가 먼저 막아서 영수증이 DB 까지 못 간다. **그 PR 의 머지 조건에
메인넷·인터널 양쪽 `alembic current` 확인을 넣어라** — 안 그러면 결제가 이미 끝난
구매에서 터진다.

## 무엇을

`ALTER TYPE ... ADD VALUE IF NOT EXISTS` 로 라벨만 덧붙인다. 앞선 WEB(`5618fef65b02`) ·
REDEEM(`b1d5e1dc71ea`) 마이그레이션은 타입을 통째로 재생성하는 방식이었는데, 그건
`ALTER TABLE ... TYPE ... USING` 을 receipt 에 두 번 거는 것이라 **74만 행 / 힙 1.4GB
테이블을 ACCESS EXCLUSIVE 로 잠그고 두 번 재작성**한다. 라이브 결제가 그동안 멈춘다.
라벨 추가는 카탈로그만 건드리므로 테이블을 잠그지 않는다.

메인넷은 PostgreSQL 10.15 라서 `ADD VALUE` 를 트랜잭션 안에서 실행할 수 없다(그 제약은
PG 12 에서 풀렸다). 그래서 `autocommit_block()` 이 필수다. `IF NOT EXISTS` 는 PG 9.3
부터 있어 10 에서도 쓸 수 있고, 이것 덕분에 문장 자체가 멱등이라 재실행해도 안전하다.

`ONESTORE_TEST`(95) 는 일부러 안 넣는다. 봉투 문자열이 상용/검증 환경 동일이라 서버가
둘을 구분할 수 없어서 세팅할 주체가 없고, 환경 분리는 배포별 credential 로 한다(`enums.py` 의
`Store.ONESTORE` 주석 참조). **PG 는 enum 라벨을 못 지우므로** 필요해질 때 같은 방식으로
한 줄 추가하는 편이, 안 쓰는 라벨을 미리 박아 두는 것보다 낫다.

라벨 정렬 순서는 알파벳이 아니라 뒤에 붙는다. `b1d5e1dc71ea` 가 정렬해 둔 건 타입을
재생성하느라 생긴 부산물이고, 코드에 `ORDER BY store` 나 store 범위 비교가 없어
순서는 의미가 없다.

## 주의

`env.py` 에 `transaction_per_migration` 설정이 없어 `upgrade` 전체가 한 트랜잭션이다.
즉 `autocommit_block()` 은 이 리비전만이 아니라 **그때까지 적용된 앞 리비전들까지 커밋**
한다. 여러 리비전이 한 번에 올라가는 상황을 피하려면 적용 전에 `alembic current` 로
직전 리비전(`d2f4a1c6e8b3`)이 이미 올라가 있는지 확인하고 실행해라.

이 리비전 자체는 롤백되지 않는다. 뒤 리비전이 실패해도 라벨은 남는다 — 라벨이 남는 것
자체는 무해하다(파이썬 enum 에 없으면 아무도 안 쓴다).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a5f3c8d21b7e"
down_revision = "d2f4a1c6e8b3"
branch_labels = None
depends_on = None

NEW_LABELS = ("ONESTORE",)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for label in NEW_LABELS:
            op.execute(f"ALTER TYPE store ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    # PG 는 enum 라벨을 지울 수 없다. 되돌리려면 타입을 재생성해야 하는데, 그건 위에서
    # 피한 receipt 전체 재작성(테이블 잠금)을 다시 불러온다. 라벨이 남아 있어도 파이썬
    # enum 에 없으면 아무도 쓰지 않으므로 무해하다 — 의도적으로 no-op 이다.
    pass
