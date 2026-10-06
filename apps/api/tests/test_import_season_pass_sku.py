"""상품 CSV 임포트가 시즌패스 SKU 등록 가드를 탄다(상품이 들어오는 유일한 경로다)."""
import pytest

from app.utils.import_utils import process_csv_row


def _row(sku):
    return {
        "id": "999", "name": "X", "google_sku": sku, "apple_sku": "", "apple_sku_k": "",
        "daily_limit": "", "weekly_limit": "", "account_limit": "", "order": "", "active": "TRUE",
        "open_timestamp": "", "close_timestamp": "", "discount": "", "rarity": "", "size": "",
        "product_type": "IAP", "mileage": "", "mileage_price": "", "required_level": "",
        "popup_path_key": "",
    }


def test_live_pass_sku_imports():
    assert process_csv_row(_row("g_pkg_couragepass36premium"), is_internal=False)["google_sku"] == "g_pkg_couragepass36premium"


def test_fixed_pass_sku_imports():
    assert process_csv_row(_row("g_pkg_couragepasspremium"), is_internal=False)["google_sku"] == "g_pkg_couragepasspremium"


def test_malformed_pass_sku_rejected_at_import():
    with pytest.raises(ValueError, match="알려진 형식이 아니다"):
        process_csv_row(_row("g_pkg_couragepass_36premium"), is_internal=False)
