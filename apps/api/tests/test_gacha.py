"""
(PLD-1562) 뽑기 — 추첨 로직 + 지급 요청 배선.

여기서 못박는 불변식은 네 가지고, 전부 **돈이 새는 방향**으로만 깨진다:

  ① **재추첨 불가** — 같은 external_ref 재요청이 같은 결과를 돌려준다. 앱 규약이 아니라
     `grant_outbox.external_ref` UNIQUE 가 강제한다.
  ② **동결된 claim 이 형식 검증을 지난다** — 워커가 체인에 싣는 게 그 값이고, 자릿수를
     재는 검사가 여기 말고는 없다(`claim_from_result`).
  ③ **지급은 동결된 결과로** — 추첨 뒤에 풀을 고쳐도 이미 뽑힌 주문의 지급은 안 바뀐다.
     (안 그러면 표를 고치는 것이 곧 뒷문 재추첨이다.)
  ④ **분포가 가중치를 따른다** — 경계값에서 칸이 밀리지 않는다.
"""


import pytest

from shared.utils.gacha import (
    GACHA_RESULT_VERSION,
    GachaPoolError,
    build_gacha_result,
    claim_from_result,
    draw_entries,
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
        assert result["draws"][0]["entryId"] == 1
        assert result["version"] == GACHA_RESULT_VERSION
        assert result["drawnAt"]

    def test_claim_이_지급_명령_모양이다(self):
        picked = FakeEntry(7, 1, ticker="Item_NT_500000", amount=3)
        result = build_gacha_result([picked], picked)
        assert result["claim"] == [
            {"kind": "ITEM", "ticker": "Item_NT_500000", "decimalPlaces": 0, "amount": 3}
        ]
        assert result["drawCount"] == 1
        assert [d["entryName"] for d in result["draws"]] == [picked.name]
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
            # kind 가 없거나 모르는 값이면 지급 tx 의 FAV/아이템 분기가 추측 위에 선다.
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


class FakeProduct:
    def __init__(self, fav_list=None, fungible_item_list=None):
        self.id = 1
        self.fav_list = fav_list or []
        self.fungible_item_list = fungible_item_list or []


# ── 룬스톤·소울스톤·크리스탈 = FAV 축 ─────────────────────────────────────────
#
# v1 을 아이템 전용으로 좁힌 건 잘못된 범위였다. 고정 상품은 `fav_list` 로 이미 FAV 를
# 주고, 뽑기라고 상금 종류가 좁을 이유가 없다. 풀이 FAV 를 담고 추첨·동결까지 가는지를
# 여기서 못박는다(수량 상한·티커 얼로우리스트는 제거됐다 — grant_guard.py 도커스트링).
class TestFavPrizes:
    def test_FAV_칸은_자릿수를_그대로_싣는다(self):
        # 아이템과 달리 FAV 는 0 이 아닌 자릿수를 가질 수 있다(CRYSTAL dp=18).
        picked = fav_entry(1, 1, ticker="FAV__CRYSTAL", amount=5, decimal_places=18)
        result = build_gacha_result([picked], picked)
        assert result["claim"] == [
            {"kind": "FAV", "ticker": "FAV__CRYSTAL", "decimalPlaces": 18, "amount": 5}
        ]
        assert claim_from_result(result) == result["claim"]

    @pytest.mark.parametrize("places", [19, 180, -1, None, "18", True])
    def test_FAV_자릿수는_0에서_18_사이_정수여야_한다(self, places):
        # 실발행량이 `amount * 10**places` 라 자릿수가 곧 배율인데(180 이면 10^180 배),
        #   이 축을 재는 검사가 **여기 말고는 없다**(CSV 임포트·CHECK 제약 어디도 안 본다).
        #   오타 하나가 그대로 체인에 나가므로 여기가 유일한 방어선이다.
        with pytest.raises(GachaPoolError, match="decimalPlaces"):
            claim_from_result({
                "version": GACHA_RESULT_VERSION,
                "claim": [{
                    "kind": "FAV", "ticker": "FAV__CRYSTAL",
                    "decimalPlaces": places, "amount": 1,
                }],
            })

    def test_FAV_자릿수_18_은_통과한다(self):
        # lib9c 통화의 최대 자릿수. 경계를 막아 버리면 CRYSTAL 을 못 넣는다.
        assert claim_from_result({
            "version": GACHA_RESULT_VERSION,
            "claim": [{
                "kind": "FAV", "ticker": "FAV__CRYSTAL",
                "decimalPlaces": 18, "amount": 1,
            }],
        })

    def test_룬스톤_칸이_통과한다(self):
        picked = fav_entry(1, 1, ticker="FAV__RUNESTONE_GOLDENTHOR", amount=100)
        result = build_gacha_result([picked], picked)
        assert claim_from_result(result)[0]["ticker"] == "FAV__RUNESTONE_GOLDENTHOR"

    def test_아이템과_FAV_를_섞은_풀도_뽑힌다(self):
        pool = [FakeEntry(1, 1), fav_entry(2, 1)]
        picked = {draw_entry(pool, rand_below=lambda _n, r=r: r).kind for r in range(2)}
        assert picked == {"ITEM", "FAV"}


# ── 10연뽑 ────────────────────────────────────────────────────────────────────
class TestMultiDraw:
    def test_N회_독립_추첨이다_복원추출(self):
        # 비복원이면 10연이 "서로 다른 10종 보장" 이 되어 공시 확률과 실제 분포가 갈린다.
        pool = [FakeEntry(1, 1), FakeEntry(2, 1)]
        picks = draw_entries(pool, 4, rand_below=lambda _n: 0)  # 항상 첫 칸
        assert [p.id for p in picks] == [1, 1, 1, 1]

    def test_회차마다_난수를_새로_뽑는다(self):
        # 한 번 뽑아 재사용하면 10연이 같은 칸 10개가 된다.
        pool = [FakeEntry(1, 1), FakeEntry(2, 1)]
        seq = iter([0, 1, 0, 1])
        picks = draw_entries(pool, 4, rand_below=lambda _n: next(seq))
        assert [p.id for p in picks] == [1, 2, 1, 2]

    @pytest.mark.parametrize("count", [0, -1, 1.5, None, True])
    def test_잘못된_횟수는_거부(self, count):
        with pytest.raises(GachaPoolError, match="횟수"):
            draw_entries([FakeEntry(1, 1)], count)

    def test_같은_칸이_여러_번_나오면_claim_에서_합산된다(self):
        # 합치지 않으면 같은 통화 항목이 tx 에 10줄 들어간다.
        pool = [FakeEntry(1, 1, amount=3)]
        result = build_gacha_result(pool, draw_entries(pool, 10))
        assert result["claim"] == [
            {"kind": "ITEM", "ticker": "Item_NT_400000", "decimalPlaces": 0, "amount": 30}
        ]
        assert result["drawCount"] == 10

    def test_회차별_원본은_버리지_않는다(self):
        # 합산본만 남기면 "10연에서 뭐가 몇 번 나왔나"를 화면도 감사도 재현할 수 없다.
        a, b = FakeEntry(1, 1, ticker="Item_NT_400000"), FakeEntry(2, 1, ticker="Item_NT_500000")
        seq = iter([0, 1, 0])
        result = build_gacha_result([a, b], draw_entries([a, b], 3, rand_below=lambda _n: next(seq)))
        assert [d["entryId"] for d in result["draws"]] == [1, 2, 1]
        assert result["drawCount"] == 3

    def test_서로_다른_칸은_합산되지_않는다(self):
        a = FakeEntry(1, 1, ticker="Item_NT_400000", amount=3)
        b = fav_entry(2, 1, ticker="FAV__RUNESTONE_HP", amount=200)
        result = build_gacha_result([a, b], [a, b, a])
        by_ticker = {c["ticker"]: c for c in result["claim"]}
        assert by_ticker["Item_NT_400000"]["amount"] == 6
        assert by_ticker["FAV__RUNESTONE_HP"]["amount"] == 200
        assert by_ticker["FAV__RUNESTONE_HP"]["kind"] == "FAV"




# ── FAV 자릿수 = 발행 배율 (리뷰에서 나온 🔴) ─────────────────────────────────
#
# `GrantItems` 는 통화의 자릿수를 **lib9c 가 정한 값**으로 쓰고 발행량(raw)은 우리가 보낸
# `amount × 10**decimal_places` 를 그대로 쓴다(Lib9c/Action/GrantItems.cs:209-214,
# `FungibleAssetValue.FromRawValue`). 그래서 우리 쪽 자릿수가 그 통화의 실제 자릿수와
# 다르면 **그 차이가 그대로 배율**이다 — 룬스톤(실제 0)에 18 을 적으면 1 개가 10^18 개다.
#
# 예전 검사는 전부 "0 이상" 또는 "0~18" 이었다. 티커를 안 보는 상한이라 이 사고를 하나도
# 못 막았고, CSV 임포트·DB CHECK·추첨 검증 세 겹이 전부 dp=18 을 통과시켰다.
#
# lib9c 실측(Lib9c/Currencies.cs): CRYSTAL·GARAGE = 18, GetRune·GetSoulStone = 0.

import pytest

from shared.utils.fav_currency import (
    FavCurrencyError,
    assert_fav_decimal_places,
    decimal_places_of,
)


@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("FAV__CRYSTAL", 18),
        ("FAV__GARAGE", 18),
        ("FAV__RUNE_GOLDENLEAF", 0),
        ("FAV__RUNESTONE_HP", 0),
        ("FAV__SOULSTONE_1001", 0),
        # 접두어 없이도 같은 답이어야 한다(호출부가 벗겨서 넘길 수 있다).
        ("SOULSTONE_1001", 0),
    ],
)
def test_lib9c_decimal_places(ticker, expected):
    assert decimal_places_of(ticker) == expected


@pytest.mark.parametrize(
    "ticker",
    [
        # NCG 는 minter 가 있어 GetMinterlessCurrency 가 거절한다 = 발행 자체가 불가능.
        "FAV__NCG",
        # 접두어가 없으면 lib9c 가 모르는 티커다.
        "FAV__RUNESTONEX",
        "FAV__SOMETHING",
        # 접두어만 있고 알맹이가 없는 것도 통화가 아니다.
        "FAV__RUNESTONE_",
        "FAV__",
        "",
    ],
)
def test_unknown_tickers_are_rejected(ticker):
    with pytest.raises(FavCurrencyError):
        decimal_places_of(ticker)


def test_wrong_decimal_places_is_rejected():
    """이 한 줄이 10^18 배 발행을 막는다."""
    with pytest.raises(FavCurrencyError) as e:
        assert_fav_decimal_places("FAV__RUNESTONE_HP", 18)
    assert "0" in str(e.value) and "18" in str(e.value)

    # 반대 방향도 사고다 — 크리스탈에 0 을 적으면 10^-18 배로 나간다.
    with pytest.raises(FavCurrencyError):
        assert_fav_decimal_places("FAV__CRYSTAL", 0)

    # 맞으면 통과.
    assert_fav_decimal_places("FAV__RUNESTONE_HP", 0)
    assert_fav_decimal_places("FAV__CRYSTAL", 18)


def test_claim_from_result_rejects_wrong_decimal_places():
    """직접 INSERT 경로(임포트를 우회)를 닫는 이중 방어."""
    from shared.utils.gacha import GachaPoolError, claim_from_result

    def result(ticker, places):
        return {
            "version": 2,
            "claim": [
                {
                    "ticker": ticker,
                    "amount": 1,
                    "decimalPlaces": places,
                    "kind": "FAV",
                }
            ],
        }

    with pytest.raises(GachaPoolError):
        claim_from_result(result("FAV__RUNESTONE_HP", 18))
    with pytest.raises(GachaPoolError):
        claim_from_result(result("FAV__NCG", 0))
    # 맞는 조합은 통과해야 한다(방어가 정상 지급을 막으면 안 된다).
    assert claim_from_result(result("FAV__RUNESTONE_HP", 0))
    assert claim_from_result(result("FAV__CRYSTAL", 18))
