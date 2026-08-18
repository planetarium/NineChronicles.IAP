"""`get_user_receipts_by_month`가 실제로 status 조건을 쿼리에 넣는지 검증한다.

소스 문자열을 보는 방식은 쓰지 않는다 — 조건식을 만들어놓고 filter에 안 넣어도 통과하고,
주석에 상태 이름만 적어도 깨진다. 여기서는 세션을 가로채 filter()에 넘어간 SQLAlchemy
표현식을 그대로 받아 컴파일해서 확인한다. DB가 없어도 돈다.

배경(회귀 방지 대상): 8/07 결제가 자동 환불됐고, 막혀 있던 클라이언트 재시도가 풀리면서
8/17 에 그 결제의 영수증이 INVALID 로 생성됐다. 이 함수가 status 를 보지 않아 "8월에
시즌패스 보유"로 잡혔고 웹샵 재구매가 막혔다.

실행: 리포 루트에서 `pytest tests/shared/test_receipt_month_status.py`
"""

import pytest
from sqlalchemy.dialects import postgresql

from shared.enums import ReceiptStatus
from shared.models.receipt import Receipt

SETTLED = {
    ReceiptStatus.INIT,
    ReceiptStatus.VALIDATION_REQUEST,
    ReceiptStatus.VALID,
}


class _CapturingQuery:
    """filter()에 넘어온 표현식만 모으는 최소 스텁."""

    def __init__(self, sink):
        self._sink = sink

    def filter(self, *conditions):
        self._sink.extend(conditions)
        return self

    def join(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def options(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _CapturingSession:
    def __init__(self):
        self.conditions = []

    def query(self, *_args, **_kwargs):
        return _CapturingQuery(self.conditions)


@pytest.fixture
def captured():
    session = _CapturingSession()
    Receipt.get_user_receipts_by_month(
        session,
        agent_addr="0x0000000000000000000000000000000000000000",
        year=2026,
        month=8,
    )
    return session.conditions


def _compiled(conditions):
    dialect = postgresql.dialect()
    return [c.compile(dialect=dialect) for c in conditions]


def test_status_condition_is_actually_applied(captured):
    """조건식을 만들어만 두고 filter에 안 넣으면 여기서 걸린다."""
    sql = " ".join(str(c) for c in _compiled(captured))
    assert "status IN" in sql, f"status 조건이 쿼리에 없다: {sql}"


def test_only_settled_statuses_are_counted(captured):
    """집계 대상이 정확히 INIT/VALIDATION_REQUEST/VALID 인지 — 바인드 파라미터로 확인."""
    found = set()
    for compiled in _compiled(captured):
        for value in compiled.params.values():
            if isinstance(value, ReceiptStatus):
                found.add(value)
            elif isinstance(value, (list, tuple)):
                found.update(v for v in value if isinstance(v, ReceiptStatus))

    assert found == SETTLED, f"집계 대상이 다르다: {sorted(s.name for s in found)}"


def test_refunded_and_invalid_are_excluded(captured):
    """환불·검증실패는 '이번 달 구매'에 들어가면 안 된다."""
    found = set()
    for compiled in _compiled(captured):
        for value in compiled.params.values():
            if isinstance(value, (list, tuple)):
                found.update(v for v in value if isinstance(v, ReceiptStatus))
            elif isinstance(value, ReceiptStatus):
                found.add(value)

    for status in (
        ReceiptStatus.INVALID,
        ReceiptStatus.REFUNDED_BY_ADMIN,
        ReceiptStatus.REFUNDED_BY_BUYER,
    ):
        assert status not in found, f"{status.name}이 집계에 포함돼 있다"
