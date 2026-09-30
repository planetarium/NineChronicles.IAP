"""지출(보상) 판정 엔드포인트는 VALID 영수증만 센다.

`/api/admin/user-receipts/non-pass-amount`·`non-pass-count` 는 포탈이 **환전 가능한 보상**
(월간·애니버서리 결제 미션)을 줄지 판정하는 데 쓴다. 여기서 INIT/VALIDATION_REQUEST 를
세면, 가짜 영수증을 제출하고 스토어 검증이 끝나기 전 몇 초 안에 수령하는 경로가 열린다.

반대로 패스 보유 판정(courage-pass 등)은 재구매 차단용이라 결제 진행 중도 세야 맞다 —
그쪽은 기본 상태 집합을 그대로 써야 한다(좁히면 결제 중 중복 구매가 열린다).
"""
from decimal import Decimal

import pytest

from shared.enums import ReceiptStatus
from shared.models.receipt import Receipt

import app.api.admin as admin

AGENT = "0x" + "a" * 40
AVATAR = "0x" + "b" * 40


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(*args, **kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(Receipt, "get_user_receipts_by_month", staticmethod(fake))
    return seen


def test_non_pass_amount_counts_valid_only(calls):
    admin.check_non_pass_purchase_amount(
        agent_address=AGENT, avatar_address=AVATAR, year=2026, month=10,
        amount_threshold=Decimal("1.9"), planet_id=None, sess=object(),
    )
    assert calls and tuple(calls[0]["statuses"]) == (ReceiptStatus.VALID,)


def test_non_pass_count_counts_valid_only(calls):
    admin.check_non_pass_purchase_count(
        agent_address=AGENT, avatar_address=AVATAR, year=2026, month=10,
        count_threshold=1, planet_id=None, sess=object(),
    )
    assert calls and tuple(calls[0]["statuses"]) == (ReceiptStatus.VALID,)


@pytest.mark.parametrize(
    "endpoint",
    ["check_courage_pass_purchases", "check_courage_pass_count", "check_adventure_boss_pass_purchases"],
)
def test_pass_ownership_endpoints_keep_default_statuses(calls, endpoint):
    """보유 판정은 좁히면 안 된다 — 결제 진행 중인 유저가 같은 달 패스를 또 살 수 있게 된다."""
    try:
        getattr(admin, endpoint)(
            agent_address=AGENT, avatar_address=AVATAR, year=2026, month=10,
            planet_id=None, sess=object(),
        )
    except Exception:
        # 빈 결과 이후의 응답 조립은 이 테스트의 관심사가 아니다 — 호출 인자만 본다.
        pass
    assert calls, f"{endpoint} 가 월별 조회를 안 불렀다"
    assert calls[0].get("statuses") is None


# ── 시즌패스 SKU 패턴은 shared 상수 한 곳에서 온다 ─────────────────────────────
from shared.models.product import (  # noqa: E402
    ADVENTURE_BOSS_PASS_SKU_PATTERN,
    COURAGE_PASS_SKU_PATTERN,
    SPEND_EXCLUDED_PASS_SKU_PATTERNS,
)


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("check_courage_pass_purchases", COURAGE_PASS_SKU_PATTERN),
        ("check_courage_pass_count", COURAGE_PASS_SKU_PATTERN),
        ("check_adventure_boss_pass_purchases", ADVENTURE_BOSS_PASS_SKU_PATTERN),
    ],
)
def test_pass_endpoints_use_shared_kind_patterns(calls, endpoint, expected):
    try:
        getattr(admin, endpoint)(
            agent_address=AGENT, avatar_address=AVATAR, year=2026, month=10,
            planet_id=None, sess=object(),
        )
    except Exception:
        pass
    assert calls[0]["sku_pattern"] == expected


@pytest.mark.parametrize("endpoint", ["check_non_pass_purchase_amount", "check_non_pass_purchase_count"])
def test_spend_endpoints_use_shared_exclusions(calls, endpoint):
    kwargs = dict(agent_address=AGENT, avatar_address=AVATAR, year=2026, month=10, planet_id=None, sess=object())
    kwargs["amount_threshold" if "amount" in endpoint else "count_threshold"] = Decimal("1.9") if "amount" in endpoint else 1
    getattr(admin, endpoint)(**kwargs)
    assert list(calls[0]["exclude_sku_patterns"]) == list(SPEND_EXCLUDED_PASS_SKU_PATTERNS)
