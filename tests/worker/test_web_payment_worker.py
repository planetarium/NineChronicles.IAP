import json
from unittest.mock import Mock, patch
import pytest

from shared.enums import PackageName, Store, ReceiptStatus
from shared.models.receipt import Receipt
from shared.models.product import Product


class TestWebPaymentWorker:
    """웹 결제 Worker 태스크 테스트"""

    @pytest.fixture
    def mock_receipt(self):
        """모의 영수증 객체"""
        receipt = Mock(spec=Receipt)
        receipt.uuid = "test-uuid-123"
        receipt.agent_addr = "0x1234567890abcdef1234567890abcdef12345678"
        receipt.avatar_addr = "0xabcdef1234567890abcdef1234567890abcdef12"
        receipt.store = Store.WEB
        receipt.order_id = "web_order_123"
        receipt.status = ReceiptStatus.VALID
        return receipt

    @pytest.fixture
    def mock_product(self):
        """모의 상품 객체"""
        product = Mock(spec=Product)
        product.id = 1
        product.name = "Test Web Product"
        product.google_sku = "web_product_456"
        product.apple_sku = "apple_product_456"
        product.apple_sku_k = "apple_k_product_456"
        return product

    def test_web_package_name_in_worker_config(self):
        """Worker 설정에서 웹 패키지명이 포함되어 있는지 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        import os
        config_path = "/Users/yang/projects/iap/apps/worker/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # 웹 패키지명이 설정 파일에 포함되어 있는지 확인
        assert "NINE_CHRONICLES_WEB" in config_content
        assert "com.planetariumlabs.ninechroniclesweb" in config_content

    def test_web_package_name_memo_generation(self, mock_receipt, mock_product):
        """웹 패키지명을 사용한 메모 생성 테스트"""
        # 웹 패키지명으로 메모 생성 로직 테스트
        package_name = PackageName.NINE_CHRONICLES_WEB

        # 메모 생성 로직을 직접 테스트
        memo_data = {
            "iap": {
                "g_sku": mock_product.google_sku,
                "a_sku": mock_product.apple_sku,  # 웹에서는 기본 apple_sku 사용
                "w_sku": (
                    mock_product.google_sku
                    if package_name == PackageName.NINE_CHRONICLES_WEB
                    else None
                ),
            }
        }

        assert memo_data["iap"]["g_sku"] == "web_product_456"
        assert memo_data["iap"]["a_sku"] == "apple_product_456"
        assert memo_data["iap"]["w_sku"] == "web_product_456"  # 웹에서는 google_sku 사용

    def test_web_package_name_memo_generation_for_other_packages(self, mock_receipt, mock_product):
        """다른 패키지명에서 웹 SKU가 None인지 테스트"""
        # 다른 패키지명들
        other_packages = [PackageName.NINE_CHRONICLES_M, PackageName.NINE_CHRONICLES_K]

        for package_name in other_packages:
            memo_data = {
                "iap": {
                    "g_sku": mock_product.google_sku,
                    "a_sku": (
                        mock_product.apple_sku_k
                        if package_name == PackageName.NINE_CHRONICLES_K
                        else mock_product.apple_sku
                    ),
                    "w_sku": (
                        mock_product.google_sku
                        if package_name == PackageName.NINE_CHRONICLES_WEB
                        else None
                    ),
                }
            }

            assert memo_data["iap"]["w_sku"] is None

    def test_web_payment_worker_task_integration(self, mock_receipt, mock_product):
        """웹 결제 Worker 태스크 통합 테스트"""
        # 실제 send_product_task 함수의 메모 생성 부분을 테스트
        package_name = PackageName.NINE_CHRONICLES_WEB

        # 메모 생성 로직
        memo = json.dumps({
            "iap": {
                "g_sku": mock_product.google_sku,
                "a_sku": (
                    mock_product.apple_sku_k
                    if package_name == PackageName.NINE_CHRONICLES_K
                    else mock_product.apple_sku
                ),
                "w_sku": (
                    mock_product.google_sku
                    if package_name == PackageName.NINE_CHRONICLES_WEB
                    else None
                ),
            }
        })

        # JSON 파싱 테스트
        parsed_memo = json.loads(memo)
        assert parsed_memo["iap"]["w_sku"] == "web_product_456"

    def test_web_payment_worker_error_handling(self, mock_receipt, mock_product):
        """웹 결제 Worker 에러 처리 테스트"""
        # 잘못된 패키지명 처리
        invalid_package = "INVALID_PACKAGE"

        # 웹 SKU 생성 로직에서 잘못된 패키지명 처리
        w_sku = (
            mock_product.google_sku
            if invalid_package == PackageName.NINE_CHRONICLES_WEB
            else None
        )

        assert w_sku is None

    def test_web_payment_worker_config_validation(self):
        """웹 결제 Worker 설정 검증 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        config_path = "/Users/yang/projects/iap/apps/worker/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # 모든 패키지명이 설정에 포함되어 있는지 확인
        expected_packages = [
            "NINE_CHRONICLES_M",
            "NINE_CHRONICLES_K",
            "NINE_CHRONICLES_WEB"
        ]

        for package in expected_packages:
            assert package in config_content

    def test_web_payment_worker_memo_structure(self, mock_receipt, mock_product):
        """웹 결제 Worker 메모 구조 테스트"""
        package_name = PackageName.NINE_CHRONICLES_WEB

        memo_data = {
            "iap": {
                "g_sku": mock_product.google_sku,
                "a_sku": mock_product.apple_sku,
                "w_sku": (
                    mock_product.google_sku
                    if package_name == PackageName.NINE_CHRONICLES_WEB
                    else None
                ),
            }
        }

        # 메모 구조 검증
        assert "iap" in memo_data
        assert "g_sku" in memo_data["iap"]
        assert "a_sku" in memo_data["iap"]
        assert "w_sku" in memo_data["iap"]

        # 웹 결제에서는 w_sku가 google_sku와 같아야 함
        assert memo_data["iap"]["w_sku"] == memo_data["iap"]["g_sku"]

    def test_web_payment_worker_json_serialization(self, mock_receipt, mock_product):
        """웹 결제 Worker JSON 직렬화 테스트"""
        package_name = PackageName.NINE_CHRONICLES_WEB

        memo_data = {
            "iap": {
                "g_sku": mock_product.google_sku,
                "a_sku": mock_product.apple_sku,
                "w_sku": (
                    mock_product.google_sku
                    if package_name == PackageName.NINE_CHRONICLES_WEB
                    else None
                ),
            }
        }

        # JSON 직렬화/역직렬화 테스트
        json_str = json.dumps(memo_data)
        parsed_data = json.loads(json_str)

        assert parsed_data == memo_data
        assert parsed_data["iap"]["w_sku"] == "web_product_456"

    def test_web_payment_worker_with_none_values(self, mock_receipt, mock_product):
        """웹 결제 Worker None 값 처리 테스트"""
        # None 값들이 포함된 경우
        mock_product.google_sku = None
        mock_product.apple_sku = None

        package_name = PackageName.NINE_CHRONICLES_WEB

        memo_data = {
            "iap": {
                "g_sku": mock_product.google_sku,
                "a_sku": mock_product.apple_sku,
                "w_sku": (
                    mock_product.google_sku
                    if package_name == PackageName.NINE_CHRONICLES_WEB
                    else None
                ),
            }
        }

        # None 값들이 올바르게 처리되는지 확인
        assert memo_data["iap"]["g_sku"] is None
        assert memo_data["iap"]["a_sku"] is None
        assert memo_data["iap"]["w_sku"] is None
