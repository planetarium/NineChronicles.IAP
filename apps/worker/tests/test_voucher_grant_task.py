from unittest.mock import MagicMock, patch

import pytest

from app.tasks import voucher_grant_task as vg
from shared.enums import ProductType, Store


class TestPlatformForStore:
    @pytest.mark.parametrize(
        "store,expected",
        [
            (Store.WEB, "PC"),
            (Store.WEB_TEST, "PC"),
            (Store.APPLE, "MOBILE"),
            (Store.APPLE_TEST, "MOBILE"),
            (Store.GOOGLE, "MOBILE"),
            (Store.GOOGLE_TEST, "MOBILE"),
            (Store.TEST, None),  # 디버그 — 바우처 대상 아님
            (Store.REDEEM, None),  # 코드 리딤 — 결제 아님
        ],
    )
    def test_mapping(self, store, expected):
        assert vg.platform_for_store(store) == expected


class TestPlanetStr:
    def test_bytes(self):
        assert vg._planet_str(b"0x000000000000") == "0x000000000000"

    def test_memoryview(self):
        assert vg._planet_str(memoryview(b"0x000000000001")) == "0x000000000001"

    def test_str_passthrough(self):
        assert vg._planet_str("0x000000000000") == "0x000000000000"


class TestTicketsForProduct:
    def _sess_with(self, rows):
        sess = MagicMock()
        sess.execute.return_value.scalars.return_value.all.return_value = rows
        return sess

    def _row(self, ticket_type, count):
        r = MagicMock()
        r.ticket_type = ticket_type
        r.count = count
        return r

    def test_returns_ticket_list(self):
        sess = self._sess_with([self._row("STANDARD", 3), self._row("PREMIUM", 1)])
        assert vg.tickets_for_product(sess, 1) == [
            {"ticketType": "STANDARD", "count": 3},
            {"ticketType": "PREMIUM", "count": 1},
        ]

    def test_empty_when_no_mapping(self):
        assert vg.tickets_for_product(self._sess_with([]), 1) == []

    def test_skips_nonpositive_count(self):
        sess = self._sess_with([self._row("STANDARD", 0), self._row("PREMIUM", 2)])
        assert vg.tickets_for_product(sess, 1) == [{"ticketType": "PREMIUM", "count": 2}]


class TestPostGrant:
    """포탈 grant 응답 분류: (terminal_ok, ref, transient)."""

    def _resp(self, status, body=None):
        r = MagicMock()
        r.status_code = status
        r.text = "err-body"
        r.json = MagicMock(return_value=body if body is not None else {})
        return r

    def _run(self, resp):
        with patch.object(vg.config, "portal_grant_url", "http://portal/api/voucher/grant"), \
            patch.object(vg.config, "portal_iap_jwt_secret", "secret"), \
            patch.object(vg.requests, "post", return_value=resp) as post:
            return vg._post_grant({"iapUuid": "x"}), post

    def test_success_is_terminal(self):
        (ok, ref, transient), post = self._run(
            self._resp(200, {"message": "success", "granted": 2})
        )
        assert ok is True and transient is False and "granted=2" in ref
        # Authorization: Bearer <jwt> 헤더 부착 확인
        assert post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")

    def test_already_granted_is_terminal(self):
        (ok, ref, transient), _ = self._run(
            self._resp(200, {"message": "already granted", "granted": 3})
        )
        assert ok is True and transient is False

    def test_amount_too_small_is_terminal(self):
        (ok, ref, transient), _ = self._run(
            self._resp(200, {"message": "no voucher (amount too small)", "granted": 0})
        )
        assert ok is True and transient is False

    def test_voucher_disabled_is_transient(self):
        # 킬스위치 off — 활성화 후 재발급해야 하므로 재시도(PENDING 유지).
        (ok, ref, transient), _ = self._run(
            self._resp(200, {"message": "voucher disabled", "granted": 0})
        )
        assert ok is False and transient is True

    def test_5xx_is_transient(self):
        (ok, ref, transient), _ = self._run(self._resp(500))
        assert ok is False and transient is True

    def test_auth_and_ratelimit_are_transient(self):
        # 인증(401/403)·레이트리밋(429)·타임아웃(408)은 회복 가능 → 재시도(종단 아님).
        for status in (401, 403, 408, 429):
            (ok, ref, transient), _ = self._run(self._resp(status))
            assert ok is False and transient is True, f"status {status} should be transient"

    def test_4xx_is_terminal_failure(self):
        # 검증오류(400 등) — 재시도해도 동일 → FAILED.
        (ok, ref, transient), _ = self._run(self._resp(400, {}))
        assert ok is False and transient is False and ref.startswith("400")

    def test_retryable_flag_is_transient(self):
        # (R2) 포탈이 body.retryable=true로 표시한 설정 불일치(409 ERR-TICKET-TYPE-UNKNOWN)
        #   → 종단 아니라 재시도(정책 일관 시 self-heal). 상태코드 관례가 아니라 플래그로 판정.
        (ok, ref, transient), _ = self._run(
            self._resp(409, {"code": "ERR-TICKET-TYPE-UNKNOWN", "retryable": True})
        )
        assert ok is False and transient is True and "retryable" in ref

    def test_409_without_retryable_is_terminal(self):
        # retryable 플래그 없는 4xx는 여전히 종단(플래그 기반 판정).
        (ok, ref, transient), _ = self._run(self._resp(409, {"message": "conflict"}))
        assert ok is False and transient is False

    def test_non_object_body_is_terminal(self):
        (ok, ref, transient), _ = self._run(self._resp(200, [1, 2, 3]))
        assert ok is False and transient is False


class TestGrantableStores:
    def test_production_excludes_sandbox(self):
        with patch.object(vg.config, "stage", "production"):
            s = vg._grantable_stores()
        assert Store.APPLE in s and Store.GOOGLE in s and Store.WEB in s
        assert Store.APPLE_TEST not in s and Store.WEB_TEST not in s

    def test_mainnet_excludes_sandbox(self):
        # 🔴 이 저장소의 실제 어휘는 "mainnet" 이다(라이브 파드 API_STAGE=mainnet).
        #   "production" 만 보면 메인넷에서 샌드박스 영수증이 진짜 NCG 바우처를 받는다.
        with patch.object(vg.config, "stage", "mainnet"):
            s = vg._grantable_stores()
        assert s == {Store.APPLE, Store.GOOGLE, Store.WEB}

    def test_nonprod_includes_sandbox(self):
        with patch.object(vg.config, "stage", "development"):
            s = vg._grantable_stores()
        assert Store.APPLE_TEST in s and Store.WEB_TEST in s and Store.GOOGLE_TEST in s

    def test_default_stage_is_not_production(self):
        # 배선 함정 고정: STAGE env 가 없으면 기본값 "development" 라 샌드박스가 열린다.
        #   즉 코드 수정만으로는 메인넷이 닫히지 않는다(WORKER_STAGE=mainnet 배선 필요).
        assert "development" not in vg._PROD_STAGES


class TestGrantVouchersGating:
    def test_disabled_returns_early(self):
        with patch.object(vg.config, "voucher_grant_enabled", False):
            assert vg.grant_vouchers.run() == "voucher grant disabled"

    def test_not_configured_returns_early(self):
        with patch.object(vg.config, "voucher_grant_enabled", True), \
            patch.object(vg.config, "portal_grant_url", None), \
            patch.object(vg.config, "portal_iap_jwt_secret", None):
            assert vg.grant_vouchers.run() == "not configured"


class TestProductTypeAllowlist:
    """(C6) 발급 대상 상품유형 — 결제 상품(IAP)만. FREE/MILEAGE 는 결제 0원 사슬이라 제외."""

    def test_grantable_subquery_filters_product_type(self):
        """프로덕션 헬퍼의 SQL 을 검사한다(테스트에서 재구성하면 tautology 가 된다)."""
        sql = str(vg.grantable_product_ids().compile(compile_kwargs={"literal_binds": True}))
        flat = " ".join(sql.split())
        assert "JOIN product ON product.id = product_voucher_grant.product_id" in flat
        assert "product_voucher_grant.active IS true" in flat
        # 얼로우리스트여야 한다 — `!= 'FREE'` 면 MILEAGE 가 통과하고 NULL 에 fail-open 한다.
        assert "product.product_type = 'IAP'" in flat
        assert "!=" not in flat

    def test_tickets_for_product_joins_product_type(self):
        """dispatch 단계도 같은 조건을 본다(enroll 이후 타입 플립 방어)."""
        sess = MagicMock()
        sess.execute.return_value.scalars.return_value.all.return_value = []
        assert vg.tickets_for_product(sess, 111) == []
        stmt = sess.execute.call_args[0][0]
        flat = " ".join(str(stmt.compile(compile_kwargs={"literal_binds": True})).split())
        assert "JOIN product" in flat
        assert "product.product_type = 'IAP'" in flat

    def test_ineligible_mappings_reports_type(self):
        sess = MagicMock()
        sess.execute.return_value.all.return_value = [
            (111, "g_pkg_freedaily200", ProductType.FREE)
        ]
        assert vg.ineligible_active_mappings(sess) == [
            (111, "g_pkg_freedaily200", "FREE")
        ]

    def test_ineligible_mappings_empty(self):
        sess = MagicMock()
        sess.execute.return_value.all.return_value = []
        assert vg.ineligible_active_mappings(sess) == []

    def test_has_active_mapping_true(self):
        """(C6) dispatch 가 "매핑 없음" 과 "유형 부적격" 을 구분하는 근거."""
        sess = MagicMock()
        sess.execute.return_value.first.return_value = (1,)
        assert vg._has_active_mapping(sess, 111) is True
        flat = " ".join(
            str(
                sess.execute.call_args[0][0].compile(
                    compile_kwargs={"literal_binds": True}
                )
            ).split()
        )
        # 유형 조건이 **없어야** 한다 — 있으면 타입 플립 케이스를 못 잡는다.
        assert "product.product_type" not in flat

    def test_has_active_mapping_false(self):
        sess = MagicMock()
        sess.execute.return_value.first.return_value = None
        assert vg._has_active_mapping(sess, 111) is False

    def test_has_active_mapping_no_product_id(self):
        sess = MagicMock()
        assert vg._has_active_mapping(sess, None) is False
        sess.execute.assert_not_called()


class TestStageDiscriminator:
    """(C6/stage) 미배선 감지의 판별자가 실제 Settings 기본값과 묶여 있어야 한다."""

    def test_default_stage_matches_settings_default(self):
        """
        `_DEFAULT_STAGE` 는 "STAGE env 가 안 들어왔다"를 판정하는 유일한 근거다.
        Settings 의 기본값이 바뀌면 이 상수도 같이 바뀌어야 하고, 아니면 미배선 경고가
        조용히 안 뜬다(경고가 안 뜨는 건 테스트 없이는 아무도 모른다).
        """
        from app.config import Settings

        assert vg._DEFAULT_STAGE == Settings.model_fields["stage"].default

    @pytest.mark.parametrize("stage", ["production", "mainnet"])
    def test_prod_stages_exclude_sandbox(self, stage):
        with patch.object(vg.config, "stage", stage):
            assert vg._grantable_stores() == set(vg._PROD_STORES)

    @pytest.mark.parametrize("stage", ["development", "internal"])
    def test_non_prod_includes_sandbox(self, stage):
        with patch.object(vg.config, "stage", stage):
            assert vg._grantable_stores() == vg._PROD_STORES | vg._TEST_STORES



class TestSeasonPassDiscriminator:
    """
    (제보) 인터널에서 시즌패스를 사도 바우처가 안 나갔다.
      원인: 시즌패스는 send_product 큐를 타지 않아 tx_status 가 영구 NULL 인데,
            enroll·dispatch 가 tx_status == SUCCESS 를 요구했다.
      마일리지는 purchase.py 안에서 동기로 주므로(조건을 안 본다) 같은 영수증에서 정상 지급됐다.
    """

    @pytest.mark.parametrize(
        "sku,expected",
        [
            ("g_pkg_couragepass34premium", True),
            ("g_pkg_adventurebosspass22premium", True),
            ("g_pkg_worldclearpass1premium", True),
            ("a_pkg_couragepass34premiumplus", True),
            # 시즌패스가 아닌 것들 — tx 를 만드는 상품이라 예외가 새면 안 된다
            ("g_single_ap01", False),
            ("g_pkg_travel01", False),
            ("g_pkg_ncuragupc", False),
            ("PLT_PACKAGE_STARTER", False),
            (None, False),  # sku 미설정
            ("", False),
        ],
    )
    def test_sku_discriminator(self, sku, expected):
        from shared.models.product import is_season_pass_product

        product = MagicMock()
        product.google_sku = sku
        assert is_season_pass_product(product) is expected

    def test_case_sensitive_matches_purchase_branch(self):
        """
        대소문자를 구분한다. purchase.py 의 분기와 **정확히 같은 집합**이어야 하는데,
        거기가 `"pass" in google_sku` 라 대문자 SKU 는 else(=tx 생성) 로 간다.
        여기서만 관대해지면 tx 를 만드는 상품에 예외가 새어나간다.
        """
        from shared.models.product import is_season_pass_product

        product = MagicMock()
        product.google_sku = "G_PKG_COURAGEPASS34PREMIUM"
        assert is_season_pass_product(product) is False

    def test_worker_sql_filter_uses_same_token(self):
        """SQL 판(season_pass_sku_filter)과 파이썬 판이 같은 토큰을 쓴다."""
        from shared.models.product import SEASON_PASS_SKU_TOKEN, season_pass_sku_filter

        assert SEASON_PASS_SKU_TOKEN == "pass"
        assert f"%{SEASON_PASS_SKU_TOKEN}%" in str(
            season_pass_sku_filter().compile(compile_kwargs={"literal_binds": True})
        )

    def test_dispatch_accepts_null_tx_for_season_pass(self):
        """dispatch 재검증도 enroll 과 같은 규칙 — 여기만 엄격하면 즉시 FAILED 종단된다."""
        sess = MagicMock()
        product = MagicMock()
        product.google_sku = "g_pkg_couragepass34premium"
        sess.get.return_value = product
        receipt = MagicMock()
        receipt.product_id = 363
        assert vg.is_season_pass_receipt(sess, receipt) is True

    def test_dispatch_rejects_null_tx_for_normal_product(self):
        """온체인 전송이 멈춘 일반 상품(NCU Pack 등 실측 4건)은 여전히 발급 대상이 아니다."""
        sess = MagicMock()
        product = MagicMock()
        product.google_sku = "g_pkg_ncuragupc"
        sess.get.return_value = product
        receipt = MagicMock()
        receipt.product_id = 999
        assert vg.is_season_pass_receipt(sess, receipt) is False

    def test_dispatch_handles_missing_product(self):
        sess = MagicMock()
        sess.get.return_value = None
        receipt = MagicMock()
        receipt.product_id = 1
        assert vg.is_season_pass_receipt(sess, receipt) is False


class TestGrantableTxCondition:
    """
    enroll 의 tx 조건을 **프로덕션 헬퍼의 SQL 로** 고정한다.
      직전 판(테스트 없이 or_ 만 추가)에서는 or_ 를 지우고 원래 코드로 되돌려도 전 테스트가
      green 이었다 — 정작 회귀가 있던 지점을 아무도 안 보고 있었다.
      (테스트에서 조건을 재구성하면 tautology 가 되므로 컴파일된 SQL 을 검사한다 —
       TestProductTypeAllowlist 의 선례와 같은 방식.)
    """

    @staticmethod
    def _sql() -> str:
        cond = vg.grantable_tx_condition()
        return " ".join(
            str(cond.compile(compile_kwargs={"literal_binds": True})).split()
        )

    def test_success_leg_still_present(self):
        assert "receipt.tx_status = 'SUCCESS'" in self._sql()

    def test_season_pass_leg_requires_null_tx_and_null_msg(self):
        """
        상품만 보면 **패스 지급이 실패한 영수증까지** 통과한다(mainnet 실측 75건).
        season_pass_host non-200 경로는 msg 만 채우고 status 는 VALID, tx_status 는 NULL 이다.
        그 경로에서는 마일리지도 안 나가므로, msg 게이트 없이는 인용한 선례보다 관대해진다.
        """
        sql = self._sql()
        assert "receipt.tx_status IS NULL" in sql
        assert "receipt.msg IS NULL" in sql

    def test_season_pass_leg_scoped_to_pass_products(self):
        """NULL 을 통째로 허용하면 온체인 전송이 멈춘 일반 상품까지 새어들어간다."""
        sql = self._sql()
        assert "receipt.product_id IN" in sql
        assert "product.google_sku LIKE '%pass%'" in sql

    def test_legs_are_or_and_season_pass_leg_is_and(self):
        """구조 고정 — 두 leg 는 OR, 시즌패스 leg 내부는 AND(하나라도 OR 이면 게이트가 뚫린다)."""
        sql = self._sql()
        assert " OR " in sql
        assert sql.count(" AND ") >= 2

    def test_dispatch_mirrors_enroll(self):
        """dispatch 재검증이 enroll 과 같은 3조건을 본다 — 한쪽만 엄격하면 enroll 된 건이 죽는다."""
        import inspect

        src = inspect.getsource(vg.grant_vouchers)
        assert "r.tx_status is None" in src
        assert "r.msg is None" in src
        assert "is_season_pass_receipt(sess, r)" in src


class TestRetryerSharesSeasonPassToken:
    """
    retryer 는 시즌패스를 send_product 재전송에서 제외한다 — 하드코딩 사본이 남아 있으면
    토큰이 바뀔 때 시즌패스가 재전송되어 **패스(claim)와 온체인 아이템이 이중 지급**된다.
    """

    def test_uses_shared_token_not_hardcoded(self):
        import inspect

        import importlib

        from shared.models.product import SEASON_PASS_SKU_TOKEN

        # app.tasks.retryer 는 __init__ 에서 celery task 객체로 덮여 있어 모듈을 직접 가져온다.
        retryer_mod = importlib.import_module("app.tasks.retryer")
        src = inspect.getsource(retryer_mod.get_null_tx_status_receipts)
        assert ":season_pass_pattern" in src, "바인드 파라미터를 써야 한다"
        assert "NOT LIKE '%pass%'" not in src, "하드코딩 사본이 남았다"
        assert SEASON_PASS_SKU_TOKEN == "pass"
