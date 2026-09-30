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


# ── 지출 판정용 좁은 상태 집합 ────────────────────────────────────────────────
#   보유 판정(재구매 차단)은 결제 진행 중(INIT/VALIDATION_REQUEST)도 "샀음"으로 봐야 맞다.
#   하지만 **보상을 주는** 지출 판정은 스토어 검증이 끝난 VALID 만 세야 한다 — 검증 전
#   영수증을 세면 가짜 영수증을 넣고 검증이 끝나기 전에 수령하는 경로가 열린다.


def _statuses_in(conditions):
    found = set()
    for compiled in _compiled(conditions):
        for value in compiled.params.values():
            if isinstance(value, ReceiptStatus):
                found.add(value)
            elif isinstance(value, (list, tuple)):
                found.update(v for v in value if isinstance(v, ReceiptStatus))
    return found


def test_statuses_override_narrows_to_exactly_that_set():
    session = _CapturingSession()
    Receipt.get_user_receipts_by_month(
        session,
        agent_addr="0x0000000000000000000000000000000000000000",
        year=2026,
        month=10,
        statuses=(ReceiptStatus.VALID,),
    )
    assert _statuses_in(session.conditions) == {ReceiptStatus.VALID}


def test_default_statuses_unchanged_for_ownership_checks(captured):
    """기본값은 보유 판정용 집합 그대로 — 좁히면 결제 중인 유저가 패스를 또 살 수 있다."""
    assert _statuses_in(captured) == SETTLED


def test_empty_statuses_is_rejected():
    """빈 집합은 '아무것도 안 셈'이 아니라 호출 실수다 — 조용히 0건을 돌려주지 않는다."""
    with pytest.raises(ValueError):
        Receipt.get_user_receipts_by_month(
            _CapturingSession(),
            agent_addr="0x0000000000000000000000000000000000000000",
            year=2026,
            month=10,
            statuses=(),
        )


# ── 스토어 필터(지출 판정용) ──────────────────────────────────────────────────
from shared.enums import Store  # noqa: E402
from shared.models.receipt import spend_counted_stores  # noqa: E402


def _stores_in(conditions):
    found = set()
    for compiled in _compiled(conditions):
        for value in compiled.params.values():
            if isinstance(value, Store):
                found.add(value)
            elif isinstance(value, (list, tuple)):
                found.update(v for v in value if isinstance(v, Store))
    return found


def test_stores_filter_is_applied_when_given():
    session = _CapturingSession()
    Receipt.get_user_receipts_by_month(
        session, agent_addr="0x0000000000000000000000000000000000000000", year=2026, month=10,
        stores=(Store.GOOGLE, Store.APPLE),
    )
    assert _stores_in(session.conditions) == {Store.GOOGLE, Store.APPLE}


def test_no_store_filter_by_default(captured):
    """보유 판정 등 기존 호출부는 스토어를 거르지 않는다(동작 불변)."""
    assert _stores_in(captured) == set()


def test_spend_stores_mainnet_are_real_payments_only():
    """메인넷: 쿠폰(REDEEM)·테스트 스토어는 '지출'이 아니다 — 세면 쿠폰이 환전 가능 포인트가 된다."""
    for stage in ("mainnet", "production"):
        assert set(spend_counted_stores(stage)) == {Store.APPLE, Store.GOOGLE, Store.WEB, Store.ONESTORE}


def test_spend_stores_non_prod_include_test_stores_but_never_redeem():
    """인터널 QA 는 WEB_TEST/TEST 로 결제한다 — 막으면 결제 미션을 시험할 수 없다. REDEEM 은 어디서도 안 센다."""
    got = set(spend_counted_stores("internal"))
    assert {Store.TEST, Store.WEB_TEST, Store.GOOGLE_TEST, Store.APPLE_TEST, Store.GOOGLE, Store.APPLE, Store.WEB, Store.ONESTORE} <= got
    assert Store.REDEEM not in got
