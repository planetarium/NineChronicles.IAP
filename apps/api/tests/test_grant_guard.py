"""
(PLD-1575) 지급 머니 가드의 **순수 부분** — 설정 파서 · 네임스페이스 · 상품 적격 · 알림 스로틀.

엔드포인트 수준 검증은 `test_admin_grant.py`(TestProductWhitelist/TestIssuanceCaps/…)에 있다.
여기는 `app.config` 도 DB 도 필요 없는 함수들만 본다 — `test_voucher_validation.py` 와 같은 분업.
`app.grant_guard` 를 임포트하면 `app.config` 가 딸려오지 않는다는 것 자체가 이 모듈의 계약이다
(config 가 거꾸로 이 파서를 부팅 검증에 쓰기 때문에 방향이 뒤집히면 순환 임포트가 된다).
"""
import pytest
from fastapi import HTTPException
from shared.enums import ProductType

from app.grant_guard import (
    ALERT_THROTTLE_SECONDS,
    GrantLimits,
    _alert_sent_at,
    namespace_of,
    parse_grant_namespaces,
    parse_point_shop_grantable,
    should_alert,
    validate_point_shop_grantable_eligible,
)


class TestParseGrantNamespaces:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("shop", {"shop"}),
            ("shop,promo", {"shop", "promo"}),
            (" shop , promo ", {"shop", "promo"}),
            ("shop,,promo", {"shop", "promo"}),  # 빈 토큰은 무시
            ("shop,shop", {"shop"}),
            ("-", set()),  # 킬스위치
        ],
    )
    def test_parses(self, raw, expected):
        assert parse_grant_namespaces(raw) == frozenset(expected)

    @pytest.mark.parametrize(
        "raw",
        [
            None,  # 미주입
            "",  # 빈 값 — 오타와 구분되지 않으므로 킬스위치로 취급하지 않는다
            " , ",
            "shop:1",  # 구분자(:)는 네임스페이스에 못 들어간다
            "shop%",  # LIKE prefix 카운트에 쓰이는 값이라 와일드카드 배제
            "shop promo",
            "_shop",  # 첫 글자는 영숫자
            "-,shop",  # 킬스위치는 단독만
            "x" * 33,
        ],
    )
    def test_rejects(self, raw):
        """fail-closed — 해석 불가는 부팅 실패(ValueError)여야 한다."""
        with pytest.raises(ValueError):
            parse_grant_namespaces(raw)


class TestNamespaceOf:
    @pytest.mark.parametrize(
        "ref,expected",
        [
            ("shop:order-1", "shop"),
            ("shop:a:b", "shop"),  # 첫 `:` 만 구분자
            ("order-1", None),  # 네임스페이스 없음
            (":order-1", None),  # 빈 네임스페이스
        ],
    )
    def test_extracts(self, ref, expected):
        assert namespace_of(ref) == expected


class TestGrantLimits:
    def test_missing_lists_unset_caps(self):
        limits = GrantLimits(allowed_namespaces=frozenset({"shop"}))

        assert limits.missing() == [
            "max_fav_units_per_request",
            "max_item_units_per_request",
            "max_grants_per_hour",
            "max_grants_per_day",
            "max_grants_per_namespace_per_minute",
        ]

    def test_zero_is_a_real_value_not_missing(self):
        """0 = "발행 금지"는 유효한 설정이다 — None(미주입)과 섞이면 킬스위치를 못 쓴다."""
        limits = GrantLimits(
            allowed_namespaces=frozenset({"shop"}),
            max_fav_units_per_request=0,
            max_item_units_per_request=0,
            max_grants_per_hour=0,
            max_grants_per_day=0,
            max_grants_per_namespace_per_minute=0,
        )

        assert limits.missing() == []


class TestPointShopEligibility:
    def test_free_product_is_eligible(self):
        validate_point_shop_grantable_eligible(1, ProductType.FREE, "sku_free")

    def test_mileage_product_is_eligible(self):
        validate_point_shop_grantable_eligible(1, ProductType.MILEAGE, "sku_mileage")

    def test_cash_product_is_rejected(self):
        with pytest.raises(HTTPException) as e:
            validate_point_shop_grantable_eligible(1, ProductType.IAP, "sku_cash")
        assert e.value.status_code == 400

    def test_season_pass_sku_is_rejected(self):
        with pytest.raises(HTTPException) as e:
            validate_point_shop_grantable_eligible(
                1, ProductType.FREE, "g_pkg_couragepass01"
            )
        assert e.value.status_code == 400

    @pytest.mark.parametrize("product_type", [None, "NOPE", ProductType])
    def test_unknown_type_is_rejected(self, product_type):
        """미지 유형·오전달은 조용히 통과하지 않는다(voucher C6 와 같은 fail-closed)."""
        with pytest.raises(HTTPException):
            validate_point_shop_grantable_eligible(1, product_type, None)


class TestAlertThrottle:
    def setup_method(self):
        _alert_sent_at.clear()

    def test_first_alert_passes_then_throttles(self):
        assert should_alert("k", now=0.0) is True
        assert should_alert("k", now=1.0) is False
        assert should_alert("k", now=ALERT_THROTTLE_SECONDS + 0.1) is True

    def test_keys_are_independent(self):
        assert should_alert("a", now=0.0) is True
        assert should_alert("b", now=0.0) is True


class TestCsvGrantableColumn:
    """
    상품 CSV 의 `point_shop_grantable` 컬럼 파서 — **화이트리스트를 켜는 정상 경로**.

    이 파서가 3상태를 잃고 2상태로 퇴화하면, 컬럼 없는 기존 시트 임포트 한 번에 전 상품의
    화이트리스트가 꺼진다(= 포인트샵 전면 중단). 그래서 계약을 여기서 못박는다.
    """

    @pytest.mark.parametrize("raw", ["TRUE", "true", "T", "Y", "yes", "1", "O"])
    def test_true_tokens(self, raw):
        assert parse_point_shop_grantable(raw) is True

    @pytest.mark.parametrize("raw", ["FALSE", "false", "N", "no", "0", "X", "-"])
    def test_false_tokens(self, raw):
        assert parse_point_shop_grantable(raw) is False

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_means_keep(self, raw):
        """컬럼 부재/빈칸 = 변경 없음. 여기가 2상태가 되면 포인트샵이 조용히 멈춘다."""
        assert parse_point_shop_grantable(raw) is None

    @pytest.mark.parametrize("raw", ["ture", "on", "예", "2"])
    def test_unknown_token_raises(self, raw):
        with pytest.raises(ValueError):
            parse_point_shop_grantable(raw)
