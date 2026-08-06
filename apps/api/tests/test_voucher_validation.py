"""voucher_validation 순수 검증 로직 테스트 (C1/C3-lite/fetch fail-closed)."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

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
        with patch.object(vv.requests, "get", return_value=self._resp(200, {"prizeTables": TABLES, "temporary": True})):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 409

    def test_non200_502(self):
        with patch.object(vv.requests, "get", return_value=self._resp(500)):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 502

    def test_request_exception_502(self):
        with patch.object(vv.requests, "get", side_effect=vv.requests.RequestException("boom")):
            with pytest.raises(HTTPException) as e:
                vv.fetch_live_prize_tables("http://portal/prize")
        assert e.value.status_code == 502

    def test_success_returns_tables(self):
        with patch.object(vv.requests, "get", return_value=self._resp(200, {"prizeTables": TABLES, "temporary": False})):
            out = vv.fetch_live_prize_tables("http://portal/prize")
        assert out == TABLES
