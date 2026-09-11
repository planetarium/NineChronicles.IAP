"""
(PLD-1562) 뽑기 — 추첨 로직 + 지급 요청 배선.

여기서 못박는 불변식은 네 가지고, 전부 **돈이 새는 방향**으로만 깨진다:

  ① **재추첨 불가** — 같은 external_ref 재요청이 같은 결과를 돌려준다. 앱 규약이 아니라
     `grant_outbox.external_ref` UNIQUE 가 강제한다.
  ② **머니 가드가 뽑기에도 걸린다** — 뽑기 상품은 `fav_list`/`fungible_item_list` 가 비어
     있어 발행량이 (0,0) 으로 계산된다. 그대로 두면 수량 상한이 뽑기에만 통째로 꺼진다.
  ③ **지급은 동결된 결과로** — 추첨 뒤에 풀을 고쳐도 이미 뽑힌 주문의 지급은 안 바뀐다.
     (안 그러면 표를 고치는 것이 곧 뒷문 재추첨이다.)
  ④ **분포가 가중치를 따른다** — 경계값에서 칸이 밀리지 않는다.
"""

from decimal import Decimal

import pytest

from app.grant_guard import GrantGuardViolation, check_fav_tickers, grant_units
from shared.utils.gacha import (
    GACHA_RESULT_VERSION,
    GachaPoolError,
    build_gacha_result,
    claim_from_result,
    draw_entry,
)


class FakeEntry:
    """ProductGachaEntry 의 추첨에 필요한 면만. DB 없이 분포·경계를 본다."""

    def __init__(
        self, id, weight, ticker="Item_NT_400000", amount=1, name=None,
        kind="ITEM", decimal_places=0,
    ):
        self.id = id
        self.weight = weight
        self.kind = kind
        self.ticker = ticker
        self.decimal_places = decimal_places
        self.sheet_item_id = 400000 if kind == "ITEM" else None
        self.amount = amount
        self.name = name or f"entry{id}"


def fav_entry(id, weight, ticker="FAV__RUNESTONE_HP", amount=1, **kw):
    """룬스톤·소울스톤·크리스탈은 전부 이 축이다."""
    return FakeEntry(id, weight, ticker=ticker, amount=amount, kind="FAV", **kw)


# ── ④ 분포·경계 ───────────────────────────────────────────────────────────────
class TestDrawDistribution:
    def test_구간_경계에서_칸이_밀리지_않는다(self):
        # weight 1/2/3 → 구간 [0,1) [1,3) [3,6). 경계 난수마다 정확히 어느 칸인지 못박는다.
        pool = [FakeEntry(1, 1), FakeEntry(2, 2), FakeEntry(3, 3)]
        expected = {0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 3}
        for roll, entry_id in expected.items():
            picked = draw_entry(pool, rand_below=lambda _n, r=roll: r)
            assert picked.id == entry_id, f"roll={roll}"

    def test_모든_칸이_도달_가능하다(self):
        # 가중치를 준 칸이 실제로 나올 수 있어야 한다("넣었는데 안 나오는 칸" 방지).
        pool = [FakeEntry(i, 1) for i in range(1, 6)]
        seen = {draw_entry(pool, rand_below=lambda _n, r=r: r).id for r in range(5)}
        assert seen == {1, 2, 3, 4, 5}

    def test_행_순서가_결과를_바꾸지_않는다(self):
        # DB 는 행 순서를 보장하지 않는다. 같은 난수면 같은 결과여야 감사·재현이 된다.
        pool = [FakeEntry(1, 1), FakeEntry(2, 2), FakeEntry(3, 3)]
        for roll in range(6):
            a = draw_entry(pool, rand_below=lambda _n, r=roll: r).id
            b = draw_entry(list(reversed(pool)), rand_below=lambda _n, r=roll: r).id
            assert a == b, f"roll={roll}: {a} != {b}"

    def test_실제_난수로도_가중치를_따른다(self):
        # secrets 기본 난수원으로 돌려 대략적인 분포를 본다(구현 교체 시 회귀 감지).
        pool = [FakeEntry(1, 1), FakeEntry(2, 9)]
        counts = {1: 0, 2: 0}
        for _ in range(2000):
            counts[draw_entry(pool).id] += 1
        # 기대 10% / 90%. 넉넉한 구간이라 정상 구현이면 플레이키하지 않다.
        assert 100 < counts[1] < 300, counts
        assert counts[1] + counts[2] == 2000


class TestDrawRejects:
    def test_빈_풀은_거부(self):
        with pytest.raises(GachaPoolError, match="빈 풀"):
            draw_entry([])

    @pytest.mark.parametrize("weight", [0, -1, 1.5, True, None])
    def test_잘못된_가중치는_거부(self, weight):
        with pytest.raises(GachaPoolError, match="weight"):
            draw_entry([FakeEntry(1, weight)])

    def test_계약을_어긴_난수원은_거부한다_클램프하지_않는다(self):
        # 클램프하면 경계 칸이 과대 선택된다. 조용히 치우치느니 멈춘다.
        pool = [FakeEntry(1, 1), FakeEntry(2, 1)]
        for bad in (-1, 2, 99):
            with pytest.raises(GachaPoolError, match="난수"):
                draw_entry(pool, rand_below=lambda _n, b=bad: b)


# ── ③ 동결 ────────────────────────────────────────────────────────────────────
class TestFrozenResult:
    def test_결과에_풀_스냅샷이_남는다(self):
        # 표를 나중에 바꾸면 "그때 확률이 얼마였나"를 재현할 수 없다 — 분쟁의 유일한 증거.
        pool = [FakeEntry(1, 1), FakeEntry(2, 9)]
        result = build_gacha_result(pool, pool[0])
        assert result["totalWeight"] == 10
        assert [(p["entryId"], p["weight"]) for p in result["pool"]] == [(1, 1), (2, 9)]
        assert result["entryId"] == 1
        assert result["version"] == GACHA_RESULT_VERSION
        assert result["drawnAt"]

    def test_claim_이_지급_명령_모양이다(self):
        picked = FakeEntry(7, 1, ticker="Item_NT_500000", amount=3)
        result = build_gacha_result([picked], picked)
        assert result["claim"] == [
            {"kind": "ITEM", "ticker": "Item_NT_500000", "decimalPlaces": 0, "amount": 3}
        ]
        assert claim_from_result(result) == result["claim"]


class TestClaimFromResultFailsClosed:
    """지급 tx 는 되돌릴 수 없다 — "이상하면 일단 준다"가 없어야 한다."""

    def test_모르는_버전은_거부(self):
        with pytest.raises(GachaPoolError, match="버전"):
            claim_from_result({"version": 999, "claim": [
                {"kind": "ITEM", "ticker": "a", "decimalPlaces": 0, "amount": 1}]})

    @pytest.mark.parametrize(
        "claim",
        [
            [],
            None,
            "not-a-list",
            [{"kind": "ITEM", "ticker": "", "decimalPlaces": 0, "amount": 1}],
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": 0, "amount": 0}],
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": 0, "amount": -1}],
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": 0, "amount": 1.5}],
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": -1, "amount": 1}],
            # 아이템 자릿수는 항상 0. 0 이 아니면 amount * 10**places 로 부풀려 발행된다.
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": 18, "amount": 1}],
            [{"kind": "ITEM", "ticker": "a", "decimalPlaces": 1, "amount": 1}],
            # kind 가 없거나 모르는 값이면 머니 가드의 FAV/아이템 분기가 추측 위에 선다.
            [{"ticker": "a", "decimalPlaces": 0, "amount": 1}],
            [{"kind": "COIN", "ticker": "a", "decimalPlaces": 0, "amount": 1}],
            [{"amount": 1}],
            ["not-a-dict"],
        ],
    )
    def test_망가진_claim_은_거부(self, claim):
        with pytest.raises(GachaPoolError):
            claim_from_result({"version": GACHA_RESULT_VERSION, "claim": claim})

    def test_빈_결과는_거부(self):
        with pytest.raises(GachaPoolError):
            claim_from_result(None)


# ── ② 머니 가드 ───────────────────────────────────────────────────────────────
class FakeProduct:
    def __init__(self, fav_list=None, fungible_item_list=None):
        self.id = 1
        self.fav_list = fav_list or []
        self.fungible_item_list = fungible_item_list or []


class TestGrantUnitsCountsTheDrawnEntry:
    def test_뽑기_상품은_구성품이_비어_있다(self):
        # 이게 위험의 근원이다: 그대로 세면 발행량 0 이라 모든 수량 상한을 통과한다.
        assert grant_units(FakeProduct()) == (Decimal(0), 0)

    def test_동결된_claim_의_수량으로_센다(self):
        # ⚠️ 넘기는 게 풀 행이 아니라 **동결된 claim** 이다 — 워커가 체인에 싣는 게 그 값이라
        #    "가드가 검사한 바이트"와 "체인에 나가는 바이트"가 같아야 한다.
        picked = FakeEntry(1, 1, amount=250)
        claim = build_gacha_result([picked], picked)["claim"]
        fav, items = grant_units(FakeProduct(), claim)
        assert items == 250, "뽑기가 수량 상한을 우회하면 안 된다"
        assert fav == Decimal(0), "v1 풀은 아이템 전용이라 FAV 는 0 이다"

    def test_풀_전체가_아니라_뽑힌_칸만_센다(self):
        # 풀 전체를 세면 상한이 사실상 0 이 되어 정상 뽑기가 전부 거절된다.
        pool = [FakeEntry(1, 1, amount=1), FakeEntry(2, 1, amount=9999)]
        claim = build_gacha_result(pool, pool[0])["claim"]
        _, items = grant_units(FakeProduct(), claim)
        assert items == 1


# ── 룬스톤·소울스톤·크리스탈 = FAV 축 ─────────────────────────────────────────
#
# v1 을 아이템 전용으로 좁힌 건 잘못된 범위였다. 고정 상품은 `fav_list` 로 이미 FAV 를
# 주고, 뽑기라고 상금 종류가 좁을 이유가 없다. 다만 FAV 는 **얼로우리스트와 별도 수량
# 상한**을 지나야 하므로, 그 두 가드가 풀을 실제로 본다는 걸 여기서 못박는다.
class TestFavPrizes:
    def test_FAV_칸은_자릿수를_그대로_싣는다(self):
        # 아이템과 달리 FAV 는 0 이 아닌 자릿수를 가질 수 있다(CRYSTAL dp=18).
        picked = fav_entry(1, 1, ticker="FAV__CRYSTAL", amount=5, decimal_places=18)
        result = build_gacha_result([picked], picked)
        assert result["claim"] == [
            {"kind": "FAV", "ticker": "FAV__CRYSTAL", "decimalPlaces": 18, "amount": 5}
        ]
        assert claim_from_result(result) == result["claim"]

    def test_룬스톤_칸이_통과한다(self):
        picked = fav_entry(1, 1, ticker="FAV__RUNESTONE_GOLDENTHOR", amount=100)
        result = build_gacha_result([picked], picked)
        assert claim_from_result(result)[0]["ticker"] == "FAV__RUNESTONE_GOLDENTHOR"

    def test_아이템과_FAV_를_섞은_풀도_뽑힌다(self):
        pool = [FakeEntry(1, 1), fav_entry(2, 1)]
        picked = {draw_entry(pool, rand_below=lambda _n, r=r: r).kind for r in range(2)}
        assert picked == {"ITEM", "FAV"}

    def test_수량은_축별로_따로_센다(self):
        # 합치면 FAV 상한이 아이템 상한에 흡수된다 — "물약 1,000개 상한이 곧 NCG 1,000
        #   발행 상한" 이 되는 자리다(grant_units 도커스트링).
        item = FakeEntry(1, 1, amount=500)
        fav = fav_entry(2, 1, amount=7)
        item_claim = build_gacha_result([item], item)["claim"]
        fav_claim = build_gacha_result([fav], fav)["claim"]

        assert grant_units(FakeProduct(), item_claim) == (Decimal(0), 500)
        assert grant_units(FakeProduct(), fav_claim) == (Decimal(7), 0)

    def test_뽑힌_FAV_티커가_얼로우리스트를_지난다(self):
        # 뽑기 상품은 product.fav_list 가 비어 있다. product 만 보면 룬스톤 뽑기가
        #   화폐 얼로우리스트를 통째로 우회한다.
        fav = fav_entry(1, 1, ticker="FAV__RUNESTONE_HP")
        claim = build_gacha_result([fav], fav)["claim"]

        # 허용목록 밖 → 400
        with pytest.raises(GrantGuardViolation) as denied:
            check_fav_tickers(FakeProduct(), frozenset({"FAV__CRYSTAL"}), claim)
        assert denied.value.status_code == 400

        # 허용목록이 비어 있음 → 503(배선 실수일 수 있어 재시도 가능해야 한다)
        with pytest.raises(GrantGuardViolation) as unset:
            check_fav_tickers(FakeProduct(), frozenset(), claim)
        assert unset.value.status_code == 503

        # 열려 있으면 통과
        check_fav_tickers(FakeProduct(), frozenset({"FAV__RUNESTONE_HP"}), claim)

    def test_아이템_칸은_얼로우리스트와_무관하다(self):
        item = FakeEntry(1, 1)
        claim = build_gacha_result([item], item)["claim"]
        check_fav_tickers(FakeProduct(), frozenset(), claim)  # 안 던진다
