"""nonce 채번용 인덱스 — receipt(planet_id, nonce) / grant_outbox(planet_id, nonce)

`max_db_nonce` 는 `SELECT max(nonce) ... WHERE planet_id = ?` 다. `receipt` 에는
`planet_id` 인덱스가 없어서(기존 `ix_receipt_*` 는 uuid/address/store/tx_id/bridged_tx_id 뿐)
이 쿼리가 **매번 전체 스캔**이고, `receipt` 는 74만 행대 + 메인넷은 PG10/shared_buffers 128MB 다.
같은 테이블의 순차 스캔이 이미 한 번 타임아웃 알람을 냈다(IAP#483).

예전엔 이 스캔이 핸들러당 1회, **잠금 밖**이었다. 지급 API(PLD-1564)가 들어오면서
  · 유상 결제: `lock_planet_nonce` → 스캔 → 서명 → 커밋 (스캔이 **잠금 구간 안**)
  · 무상 지급 워커: `claim_nonce` 마다 같은 스캔, beat 1분 주기 × 최대 50건
이 됐다. 포인트샵 이벤트로 grant 가 몰리면 그 스캔들이 같은 행성 잠금을 직렬 점유하고,
**유상 결제 nonce 채번이 그 뒤에 줄을 선다.**

잠금 설계 자체는 옳으므로 되돌릴 게 아니라 인덱스를 얹는다. 그러면 잠금 구간이 마이크로초가 된다.

⚠️ `IF NOT EXISTS` 때문에 **CONCURRENTLY 빌드가 실패한 뒤 재실행하면 INVALID 인덱스를
건너뛰고 리비전만 stamped 된다** — 순차 스캔이 조용히 남는다. 적용 후 반드시 확인할 것:

    SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;

나오면 그 인덱스를 DROP 하고 이 리비전을 다시 돌려야 한다.

`CONCURRENTLY` 를 쓴다 — `receipt` 에 ACCESS EXCLUSIVE 를 잡으면 그동안 결제가 멈춘다.
그래서 이 리비전은 **트랜잭션 밖**에서 돌아야 한다(`autocommit_block`).

Revision ID: c8f4a2e61b09
Revises: b2d94f6c15a8
Create Date: 2026-09-22
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c8f4a2e61b09"
down_revision = "b2d94f6c15a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PG10 에도 CREATE INDEX CONCURRENTLY 는 있다. 실패하면 INVALID 인덱스가 남으므로
    #   (그 상태로도 쿼리는 정상 동작한다) DROP 후 재시도하면 된다.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receipt_planet_nonce "
            "ON receipt (planet_id, nonce DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_grant_outbox_planet_nonce "
            "ON grant_outbox (planet_id, nonce DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_grant_outbox_planet_nonce")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_receipt_planet_nonce")
