"""voucher_validation 순수 검증 로직 테스트 (C1/C3-lite/fetch fail-closed)."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from shared.enums import ProductType

from app import voucher_validation as vv

TABLES = {
    "STANDARD": [
        {"rank": "1등", "ncg": 2000, "prob": 0.01},
        {"rank": "꽝", "ncg": 0, "prob": 0.99},
    ],
    "PREMIUM": [{"rank": "1등", "ncg": 20000, "prob": 1}],
}


class TestValidateMapping:
    def test_valid_no_raise(self):
        vv.validate_voucher_mapping("STANDARD", 2, TABLES, None)

    def test_unknown_ticket_type_409(self):
        with pytest.raises(HTTPException) as e:
            vv.validate_voucher_mapping("NOPE", 1, TABLES, None)
        assert e.value.status_code == 409

    def test_empty_tiers_409(self):
        with pytest.raises(HTTPException) as e:
            vv.validate_voucher_mapping("EMPTY", 1, {"EMPTY": []}, None)
        assert e.value.status_code == 409

    @pytest.mark.parametrize("count", [0, -1, 1.5, "2"])
    def test_bad_count_400(self, count):
        with pytest.raises(HTTPException) as e:
            vv.validate_voucher_mapping("STANDARD", count, TABLES, None)
        assert e.value.status_code == 400

    def test_c3lite_exceeds_cap_400(self):
        # STANDARD 최대상금 2000 × 6 = 12000 > cap 10000 → 거부
        with pytest.raises(HTTPException) as e:
            vv.validate_voucher_mapping("STANDARD", 6, TABLES, 10000)
        assert e.value.status_code == 400

    def test_c3lite_within_cap_ok(self):
        vv.validate_voucher_mapping("STANDARD", 5, TABLES, 10000)  # 2000×5=10000 ≤ cap

    def test_c3lite_cap_none_skips(self):
        vv.validate_voucher_mapping("PREMIUM", 100, TABLES, None)  # cap 없으면 통과


class TestFetchLivePrizeTables:
    def _resp(self, status=200, body=None):
        r = MagicMock()
        r.status_code = status
        r.json = MagicMock(return_value=body if body is not None else {})
        return r

    def test_no_url_503(self):
        with pytest.raises(HTTPException) as e:
            vv.fetch_live_prize_tables(None)
        assert e.value.status_code == 503

    def test_temporary_409(self):
        with patch.object(
            vv.requests,
            "get",
            return_value=self._resp(200, {"prizeTables": TABLES, "temporary": True}),
        ):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 409

    def test_non200_502(self):
        with patch.object(vv.requests, "get", return_value=self._resp(500)):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 502

    def test_request_exception_502(self):
        with patch.object(
            vv.requests, "get", side_effect=vv.requests.RequestException("boom")
        ):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 502

    def test_success_returns_tables(self):
        with patch.object(
            vv.requests,
            "get",
            return_value=self._resp(200, {"prizeTables": TABLES, "temporary": False}),
        ):
            out = vv.fetch_live_prize_tables("http://portal/prize")
        assert out == TABLES


class TestParseVoucherColumns:
    # pairs = [(type_i, count_i), ...] (고정 슬롯 원본 문자열)
    def test_all_blank_is_none(self):
        assert (
            vv.parse_voucher_columns([("", ""), ("  ", None), (None, "")], TABLES, None)
            is None
        )

    def test_dash_alone_is_clear(self):
        assert (
            vv.parse_voucher_columns([("-", ""), ("", ""), ("", "")], TABLES, None)
            == {}
        )

    def test_single(self):
        assert vv.parse_voucher_columns(
            [("STANDARD", "2"), ("", ""), ("", "")], TABLES, None
        ) == {"STANDARD": 2}

    def test_multi_pairs(self):
        out = vv.parse_voucher_columns(
            [("STANDARD", "1"), ("PREMIUM", "3"), ("", "")], TABLES, None
        )
        assert out == {"STANDARD": 1, "PREMIUM": 3}

    def test_count_defaults_to_1(self):
        assert vv.parse_voucher_columns(
            [("STANDARD", ""), ("", ""), ("", "")], TABLES, None
        ) == {"STANDARD": 1}

    def test_bad_count_400(self):
        with pytest.raises(HTTPException) as e:
            vv.parse_voucher_columns([("STANDARD", "x")], TABLES, None)
        assert e.value.status_code == 400

    def test_unknown_type_propagates_409(self):
        with pytest.raises(HTTPException) as e:
            vv.parse_voucher_columns([("NOPE", "1")], TABLES, None)
        assert e.value.status_code == 409

    def test_c3lite_propagates_400(self):
        with pytest.raises(HTTPException) as e:
            vv.parse_voucher_columns(
                [("STANDARD", "6")], TABLES, 10000
            )  # 2000×6 > 10000
        assert e.value.status_code == 400

    def test_duplicate_type_400(self):
        with pytest.raises(HTTPException) as e:
            vv.parse_voucher_columns(
                [("STANDARD", "1"), ("STANDARD", "9")], TABLES, None
            )
        assert e.value.status_code == 400

    def test_dash_with_others_400(self):
        # '-'(전체 제거)는 단독으로만 — 다른 종류와 섞으면 거부.
        with pytest.raises(HTTPException) as e:
            vv.parse_voucher_columns([("-", ""), ("STANDARD", "1")], TABLES, None)
        assert e.value.status_code == 400

class TestProductTypeAllowlist:
    """(C6) 바우처 매핑 가능 상품유형 — 결제 상품(IAP)만 통과."""

    def test_iap_enum_passes(self):
        vv.validate_product_voucher_eligible(3, ProductType.IAP)

    def test_iap_string_passes(self):
        vv.validate_product_voucher_eligible(3, "IAP")

    @pytest.mark.parametrize(
        "ptype",
        [
            ProductType.FREE,
            ProductType.MILEAGE,
            "FREE",
            "MILEAGE",
            "free",  # 소문자 — 정규화 후 판정
            " FREE ",  # 공백
            None,  # 미지값은 통과시키지 않는다(fail-closed)
            "",
            123,
        ],
    )
    def test_everything_else_400(self, ptype):
        with pytest.raises(HTTPException) as e:
            vv.validate_product_voucher_eligible(111, ptype)
        assert e.value.status_code == 400

    def test_orm_class_attribute_is_rejected(self):
        """`product.product_type`(정상) 과 `Product.product_type`(오전달)은 한 글자 차이 — 후자는 막아야."""
        from shared.models.product import Product

        with pytest.raises(HTTPException) as e:
            vv.validate_product_voucher_eligible(111, Product.product_type)
        assert e.value.status_code == 400

    def test_free_detail_mentions_iap(self):
        with pytest.raises(HTTPException) as e:
            vv.validate_product_voucher_eligible(111, ProductType.FREE)
        assert "IAP" in e.value.detail

    # CSV 경로(_apply_voucher_row)는 여기서 테스트하지 않는다 — `app.utils` 임포트가
    # app.config.Settings() 를 즉시 평가해서 전체 런타임 설정 없이는 임포트 자체가 실패한다.
    # 해당 경로는 위 순수 가드 + import_utils 의 배선(리뷰 대상)으로 커버한다.
