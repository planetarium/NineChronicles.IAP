"""
(PLD-1575) 지급 머니 가드의 **순수 부분** — 설정 파서 · 네임스페이스 · 상품 적격 · 알림 스로틀.

엔드포인트 수준 검증은 `test_admin_grant.py`(TestProductWhitelist/TestIssuanceCaps/…)에 있다.
여기는 `app.config` 도 DB 도 필요 없는 함수들만 본다 — `test_voucher_validation.py` 와 같은 분업.
`app.grant_guard` 를 임포트하면 `app.config` 가 딸려오지 않는다는 것 자체가 이 모듈의 계약이다
(config 가 거꾸로 이 파서를 부팅 검증에 쓰기 때문에 방향이 뒤집히면 순환 임포트가 된다).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from shared.enums import ProductType

from app.grant_guard import (
    ALERT_THROTTLE_MAX_KEYS,
    ALERT_THROTTLE_SECONDS,
    AVATAR_COLLAPSED_LABEL,
    GLOBAL_SCOPE,
    GRANT_GUARD_LOCK_KEY,
    UNREGISTERED_NAMESPACE_LABEL,
    GrantLimits,
    GrantScope,
    _alert_sent_at,
    alert_key,
    guard_now,
    lock_grant_guard,
    namespace_of,
    parse_fav_tickers,
    parse_grant_namespaces,
    parse_point_shop_grantable,
    scope_warn_key,
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

    def test_avatar_axis_and_duplicate_window_are_not_prod_required(self):
        """
        새 축은 `missing()`(=prod 503 게이트)에 **들어가지 않는다.**

        여기 이름을 추가하면 그 env 가 차트에 배선되기 전에 새 이미지가 뜨는 순간 지급 API
        전체가 503(포인트샵 정지)이 되고 화이트리스트 켜는 경로까지 막힌다. 총노출은 이미
        필수인 전역 시/일 상한이 묶으므로, 아바타 축은 그 안의 **집중도**만 좁힌다
        (미주입이 "무제한 발행"이 되지는 않는다). 중복 창은 애초에 거절하지 않는 관측 기능이다.
        """
        limits = GrantLimits(
            allowed_namespaces=frozenset({"shop"}),
            max_fav_units_per_request=1,
            max_item_units_per_request=1,
            max_grants_per_hour=1,
            max_grants_per_day=1,
            max_grants_per_namespace_per_minute=1,
        )

        assert limits.max_grants_per_avatar_per_hour is None  # 미주입 = 그 축 미적용
        assert limits.max_grants_per_avatar_per_day is None
        assert limits.duplicate_alert_window_seconds is None
        assert limits.missing() == []

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

    @pytest.mark.parametrize("raw", ["TRUE", "true", "T", "Y", "yes", "1"])
    def test_true_tokens(self, raw):
        assert parse_point_shop_grantable(raw) is True

    @pytest.mark.parametrize("raw", ["FALSE", "false", "N", "no", "0", "X", "-"])
    def test_false_tokens(self, raw):
        assert parse_point_shop_grantable(raw) is False

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_means_keep(self, raw):
        """컬럼 부재/빈칸 = 변경 없음. 여기가 2상태가 되면 포인트샵이 조용히 멈춘다."""
        assert parse_point_shop_grantable(raw) is None

    # 문자 `O` 는 True 가 아니다 — 숫자 `0`(=False) 오타를 True 로 읽으면 "끄려다 켜는" 사고다.
    @pytest.mark.parametrize("raw", ["ture", "on", "예", "2", "O"])
    def test_unknown_token_raises(self, raw):
        with pytest.raises(ValueError):
            parse_point_shop_grantable(raw)


class TestParseFavTickers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, set()),  # 미주입 = FAV 지급 금지
            ("", set()),
            ("FAV__CRYSTAL", {"FAV__CRYSTAL"}),
            (
                " FAV__CRYSTAL , FAV__RUNE_GOLDENLEAF ",
                {"FAV__CRYSTAL", "FAV__RUNE_GOLDENLEAF"},
            ),
        ],
    )
    def test_parses(self, raw, expected):
        """
        네임스페이스 파서와 달리 빈 값이 오류가 아니다 — 여기서는 빈 값이 **가장 안전한 상태**
        (FAV 지급 금지)이자 기본값이다. 화폐 발행은 "실수로 열려 있는" 상태가 없어야 한다.
        """
        assert parse_fav_tickers(raw) == frozenset(expected)


class TestAlertKey:
    ALLOWED = frozenset({"shop"})

    def test_registered_namespace_is_kept(self):
        assert alert_key("r", "shop", self.ALLOWED) == "r:shop"

    @pytest.mark.parametrize("namespace", ["promo1", "promo2", None, "x" * 120])
    def test_unregistered_namespaces_collapse_to_one_key(self, namespace):
        """
        미등록 값은 하나로 접는다. 안 접으면 호출자가 ref 만 바꿔 던져 스로틀을 무력화하고
        (요청마다 webhook POST) 스로틀 dict 도 무한 증식한다.
        """
        assert alert_key("r", namespace, self.ALLOWED) == (
            f"r:{UNREGISTERED_NAMESPACE_LABEL}"
        )


class TestGrantScope:
    """
    시간창의 축 표현. 라벨(거절 문구)·키(알림 스로틀)가 축마다 달라야 한다 — 키가 같으면
    서로 다른 아바타·상품의 경고가 한 키로 접혀 서로를 삼킨다.
    """

    AVATAR = "0x" + "ab" * 20

    def test_global_scope_reads_as_everything(self):
        assert GLOBAL_SCOPE.label == "전체"
        assert GLOBAL_SCOPE.key == "all"

    def test_namespace_scope(self):
        scope = GrantScope(namespace="shop")

        assert scope.label == "네임스페이스 'shop'"
        assert scope.key == "ns=shop"

    def test_avatar_scope(self):
        scope = GrantScope(avatar_addr=self.AVATAR)

        assert self.AVATAR in scope.label
        assert scope.key == f"avatar={self.AVATAR}"

    def test_avatar_product_scope_keys_differ_per_product(self):
        """중복 경고 키 — 같은 아바타의 다른 상품이 서로를 스로틀하면 안 된다."""
        one = GrantScope(avatar_addr=self.AVATAR, product_id=1)
        two = GrantScope(avatar_addr=self.AVATAR, product_id=2)

        assert one.key != two.key
        assert "상품 1" in one.label

    def test_scope_warn_key_follows_alert_key_convention(self):
        key = scope_warn_key("duplicate_grant_warn", GrantScope(namespace="shop").key)

        assert key == "duplicate_grant_warn:ns=shop"  # `<reason>:<스코프>`

    def test_coarse_key_folds_the_avatar_but_keeps_the_axis(self):
        """
        임박 경고용 키 — 아바타만 접고 나머지 축은 남긴다. 접지 않으면 상한 근처의 아바타
        수만큼 요청 경로에서 webhook POST 가 나가고 스로틀 저장소를 밀어낸다.
        """
        one = GrantScope(avatar_addr=self.AVATAR)
        two = GrantScope(avatar_addr="0x" + "cd" * 20)

        assert one.coarse_key == two.coarse_key == f"avatar={AVATAR_COLLAPSED_LABEL}"
        assert one.key != two.key  # 정확 키는 여전히 아바타별
        assert GLOBAL_SCOPE.coarse_key == "all"  # 아바타가 없는 축은 그대로


class TestLockGrantGuard:
    """
    SQLite 테스트에서는 no-op 이라 PG 분기 SQL 이 한 번도 실행되지 않는다 → 여기서 발행 SQL 을
    직접 확인한다(오타 하나로 경합 방어가 조용히 사라지는 걸 막는다).
    """

    def _fake_session(self, dialect_name):
        sess = MagicMock()
        sess.get_bind.return_value.dialect.name = dialect_name
        return sess

    def test_postgres_takes_xact_advisory_lock(self):
        sess = self._fake_session("postgresql")

        lock_grant_guard(sess)

        assert sess.execute.call_count == 1
        sql, params = sess.execute.call_args[0]
        assert "pg_advisory_xact_lock" in str(sql)  # xact = 커밋/롤백에서 자동 해제
        assert params == {"key": GRANT_GUARD_LOCK_KEY}

    def test_other_dialects_are_noop(self):
        sess = self._fake_session("sqlite")

        lock_grant_guard(sess)

        assert sess.execute.call_count == 0


class TestAlertThrottleBound:
    def setup_method(self):
        _alert_sent_at.clear()

    def test_state_is_bounded(self):
        """프로세스 수명이 긴 서비스에 무한 증식하는 전역 dict 를 남기지 않는다."""
        for i in range(ALERT_THROTTLE_MAX_KEYS * 2):
            should_alert(f"k{i}", now=float(i) * ALERT_THROTTLE_SECONDS)

        assert len(_alert_sent_at) <= ALERT_THROTTLE_MAX_KEYS


class TestGuardNow:
    """
    시간창 기준시각의 출처. 앱↔DB 시계 스큐로 창이 밀리면(앱이 앞서면 카운트 0) fail-open 이라
    PG 에서는 행의 `created_at` 과 **같은 시계**(DB)를 써야 한다. SQLite 분기와 함께 못박는다.
    """

    def test_postgres_uses_db_clock(self):
        sess = MagicMock()
        sess.get_bind.return_value.dialect.name = "postgresql"
        stamped = datetime(2026, 9, 9, tzinfo=timezone.utc)
        sess.scalar.return_value = stamped

        assert guard_now(sess) is stamped
        assert sess.scalar.call_count == 1

    def test_sqlite_uses_app_clock(self):
        sess = MagicMock()
        sess.get_bind.return_value.dialect.name = "sqlite"

        now = guard_now(sess)

        assert sess.scalar.call_count == 0  # 문자열을 돌려주므로 DB 시계를 못 쓴다
        assert now.tzinfo is timezone.utc
