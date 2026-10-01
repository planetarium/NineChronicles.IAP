"""시즌패스 SKU 판정 — 영수증 집계 패턴과 상품 등록 가드.

배경: 시즌패스 SKU 를 시즌마다 바꾸지 않는 **고정 SKU**(예: `g_pkg_couragepasspremium`)로 갈
예정이다(docs/specs/2026-09-18-season-pass-fixed-sku.md). 그런데
  · admin.py 의 유저 영수증 집계 5곳이 `...pass\\d+premium` 으로 숫자를 **요구**해서, 고정 SKU 는
    매치 실패 → 빈 결과로 조용히 틀린다(보유 판정 오답 = 중복 결제 통과, 지출 판정에 패스 포함).
  · purchase.py 는 시즌 번호를 SKU 의 숫자에서 읽는다 — 숫자가 없으면 season_index=0 으로
    시즌패스 서버를 불러 **결제는 되고 패스는 안 켜진다.**
그래서 집계 패턴은 지금 고정 SKU 를 받도록 풀고, 등록은 결제 경로가 준비될 때까지 막는다.

아래 LIVE_SHAPES 는 2026-09-30 메인넷·인터널 product.google_sku 에서 'pass' 가 든 것의 형식 전부다
(두 환경 동일, 6 종). 이 중 하나라도 등록 가드에 막히면 기존 시트 재임포트가 깨진다.
"""
import pytest

from shared.models.product import (
    ADVENTURE_BOSS_PASS_SKU_PATTERN,
    COURAGE_PASS_SKU_PATTERN,
    SPEND_EXCLUDED_PASS_SKU_PATTERNS,
    SeasonPassSkuError,
    assert_season_pass_sku_registrable,
    sku_matches,
)

LIVE_SHAPES = [
    "g_pkg_adventurebosspass15premium",
    "g_pkg_couragepass27premium",
    "g_pkg_seasonpass3",
    "g_pkg_seasonpassall3",
    "g_pkg_seasonpassplus3",
    "g_pkg_worldclearpass1premium",
]
FIXED_COURAGE = "g_pkg_couragepasspremium"
FIXED_ADVENTURE = "g_pkg_adventurebosspasspremium"


# ── 집계 패턴 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sku", ["g_pkg_couragepass27premium", "g_pkg_couragepass35premium", FIXED_COURAGE])
def test_courage_pattern_matches_legacy_and_fixed(sku):
    assert sku_matches(COURAGE_PASS_SKU_PATTERN, sku)


@pytest.mark.parametrize("sku", ["g_pkg_adventurebosspass15premium", "g_pkg_adventurebosspass23premium", FIXED_ADVENTURE])
def test_adventure_boss_pattern_matches_legacy_and_fixed(sku):
    assert sku_matches(ADVENTURE_BOSS_PASS_SKU_PATTERN, sku)


def test_kinds_do_not_cross():
    """종류 구분이 소멸하면 어드벤처보스 구매가 커리지패스 보유로 잡힌다."""
    assert not sku_matches(COURAGE_PASS_SKU_PATTERN, FIXED_ADVENTURE)
    assert not sku_matches(COURAGE_PASS_SKU_PATTERN, "g_pkg_adventurebosspass23premium")
    assert not sku_matches(ADVENTURE_BOSS_PASS_SKU_PATTERN, FIXED_COURAGE)
    assert not sku_matches(ADVENTURE_BOSS_PASS_SKU_PATTERN, "g_pkg_couragepass35premium")


def test_spend_exclusion_covers_both_kinds_but_not_world_clear():
    """월드클리어패스는 결제 미션 누적에 **포함**한다(2026-09-30 기획 결정)."""
    def excluded(sku):
        return any(sku_matches(p, sku) for p in SPEND_EXCLUDED_PASS_SKU_PATTERNS)

    for sku in ("g_pkg_couragepass35premium", "g_pkg_adventurebosspass23premium", FIXED_COURAGE, FIXED_ADVENTURE):
        assert excluded(sku), sku
    assert not excluded("g_pkg_worldclearpass1premium")
    assert not excluded("g_pkg_essone")


# ── 등록 가드 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sku", LIVE_SHAPES + ["g_pkg_essone", "g_single_golddust01", "", None])
def test_live_skus_and_non_pass_skus_are_registrable(sku):
    assert_season_pass_sku_registrable(sku)


@pytest.mark.parametrize("sku", [FIXED_COURAGE, FIXED_ADVENTURE, "g_pkg_worldclearpasspremium"])
def test_fixed_sku_registrable_now_that_purchase_path_supports_it(sku):
    """결제 경로가 시즌 번호를 시즌패스에서, 구성품을 회차 행에서 읽게 된 뒤 허용했다."""
    assert_season_pass_sku_registrable(sku)


def test_fixed_pass_kind_and_component_sku():
    from shared.models.product import (
        fixed_pass_display_name,
        fixed_pass_kind,
        season_component_sku,
    )

    kind = fixed_pass_kind(FIXED_COURAGE)
    assert kind.pass_type == "CouragePass"
    assert season_component_sku(FIXED_COURAGE, 36) == "g_pkg_couragepass36premium"
    # 클라 GetProductKey 와 바이트 단위로 같아야 한다(DB 의 회차 행 name 실측과 동일 형식).
    assert fixed_pass_display_name(kind, 35) == "COURAGEPASS35Premium"
    adv = fixed_pass_kind(FIXED_ADVENTURE)
    assert fixed_pass_display_name(adv, 23) == "ADVENTUREBOSSPASS23Premium"
    wcp = fixed_pass_kind("g_pkg_worldclearpasspremium")
    assert fixed_pass_display_name(wcp, 1) == "WORLDCLEARPASS1Premium"
    # 회차 SKU·일반 SKU 는 고정이 아니다.
    assert fixed_pass_kind("g_pkg_couragepass35premium") is None
    assert fixed_pass_kind("g_pkg_daily01") is None
    assert fixed_pass_kind(None) is None


@pytest.mark.parametrize(
    "sku",
    [
        "g_pkg_CouragePass36premium",   # 대문자 — purchase.py 의 'pass' in sku 는 대소문자 구분이라 일반 상품으로 새 나간다
        "g_pkg_couragepass_36premium",  # 오타 — 어느 집계 패턴에도 안 걸린다
        "g_pkg_petpass1premium",        # 모르는 종류 — purchase.py 가 pass_type=None 으로 보낸다
        "g_pkg_couragepass36",          # premium 접미어 누락 — 집계 패턴 불일치
    ],
)
def test_unknown_or_malformed_pass_skus_are_rejected(sku):
    with pytest.raises(SeasonPassSkuError):
        assert_season_pass_sku_registrable(sku)


@pytest.mark.parametrize("sku", [" g_pkg_couragepass36premium", "g_pkg_couragepass36premium\n"])
def test_whitespace_around_pass_sku_is_rejected_with_its_own_reason(sku):
    with pytest.raises(SeasonPassSkuError, match="공백"):
        assert_season_pass_sku_registrable(sku)
