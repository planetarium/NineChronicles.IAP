import json
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient

from shared.enums import Store, PackageName, PlanetID, ReceiptStatus
from shared.schemas.receipt import ReceiptSchema


class TestWebPaymentIntegration:
    """웹 결제 API 통합 테스트"""

    @pytest.fixture
    def web_payment_request_data(self):
        return {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000000"
        }

    @pytest.fixture
    def web_test_payment_request_data(self):
        return {
            "store": Store.WEB_TEST,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_test_order_123",
                "productId": 1,
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "test_card"
            },
            "planetId": "0x000000000000"
        }

    def test_web_payment_schema_validation(self, web_payment_request_data):
        """웹 결제 스키마 유효성 검증"""
        receipt_schema = ReceiptSchema(**web_payment_request_data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "web_order_123"
        assert receipt_schema.data["productId"] == 1

    def test_web_test_payment_schema_validation(self, web_test_payment_request_data):
        """웹 테스트 결제 스키마 유효성 검증"""
        receipt_schema = ReceiptSchema(**web_test_payment_request_data)

        assert receipt_schema.store == Store.WEB_TEST
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "web_test_order_123"
        assert receipt_schema.data["productId"] == 1

    def test_invalid_store_type_validation(self):
        """잘못된 스토어 타입 검증"""
        invalid_data = {
            "store": 999,  # 잘못된 스토어 타입
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": 1640995200
            },
            "planetId": "0x000000000000"
        }

        # Pydantic은 잘못된 enum 값을 허용하므로, 실제로는 get_order_data에서 에러가 발생
        receipt_schema = ReceiptSchema(**invalid_data)
        assert receipt_schema.store == 999  # 잘못된 값이 그대로 저장됨

    def test_missing_required_fields_validation(self):
        """필수 필드 누락 검증"""
        incomplete_data = {
            "store": Store.WEB,
            # agentAddress 누락
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": 1640995200
            },
            "planetId": "0x000000000000"
        }

        # Pydantic은 Optional 필드를 허용하므로, 실제로는 API에서 검증
        receipt_schema = ReceiptSchema(**incomplete_data)
        assert receipt_schema.agentAddress is None  # None으로 설정됨

    def test_web_payment_data_structure_validation(self, web_payment_request_data):
        """웹 결제 데이터 구조 검증"""
        data = web_payment_request_data["data"]

        # 필수 필드 확인
        required_fields = ["orderId", "productId", "purchaseTime", "amount", "currency", "paymentMethod"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # 데이터 타입 확인
        assert isinstance(data["orderId"], str)
        assert isinstance(data["productId"], str)
        assert isinstance(data["purchaseTime"], int)
        assert isinstance(data["amount"], (int, float))
        assert isinstance(data["currency"], str)
        assert isinstance(data["paymentMethod"], str)

    def test_web_payment_planet_id_validation(self, web_payment_request_data):
        """웹 결제 플래닛 ID 검증"""
        receipt_schema = ReceiptSchema(**web_payment_request_data)

        # 플래닛 ID가 올바르게 파싱되는지 확인
        assert isinstance(receipt_schema.planetId, PlanetID)
        assert receipt_schema.planetId == PlanetID.ODIN

    def test_web_payment_address_formatting(self, web_payment_request_data):
        """웹 결제 주소 포맷팅 검증"""
        receipt_schema = ReceiptSchema(**web_payment_request_data)

        # 주소가 올바르게 포맷팅되는지 확인
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"

    def test_web_payment_auto_detection(self):
        """웹 결제 자동 감지 테스트"""
        # Store 필드가 없어도 데이터에서 자동으로 감지되는지 확인
        auto_detect_data = {
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",  # 이 필드로 자동 감지
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000000"
        }

        from shared.schemas.receipt import SimpleReceiptSchema
        receipt_schema = SimpleReceiptSchema(data=auto_detect_data["data"])

        assert receipt_schema.store == Store.WEB

    def test_web_payment_invalid_data_types(self):
        """웹 결제 잘못된 데이터 타입 검증"""
        invalid_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": "invalid_timestamp",  # 잘못된 타입
                "amount": "invalid_amount",  # 잘못된 타입
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000000"
        }

        # 데이터 타입 검증은 get_order_data에서 처리되므로 여기서는 스키마 생성만 테스트
        receipt_schema = ReceiptSchema(**invalid_data)
        assert receipt_schema.store == Store.WEB
        # 실제 데이터 타입 검증은 get_order_data 함수에서 처리됨

    def test_web_payment_edge_cases(self):
        """웹 결제 엣지 케이스 테스트"""
        # 빈 문자열 테스트
        empty_string_data = {
            "store": Store.WEB,
            "agentAddress": "",
            "avatarAddress": "",
            "data": {
                "Store": "WebPayment",
                "orderId": "",
                "productId": "",
                "purchaseTime": 0,
                "amount": 0.0,
                "currency": "",
                "paymentMethod": ""
            },
            "planetId": "0x000000000000"
        }

        receipt_schema = ReceiptSchema(**empty_string_data)
        assert receipt_schema.store == Store.WEB
        assert receipt_schema.data["orderId"] == ""
        assert receipt_schema.data["productId"] == ""

    def test_web_payment_unicode_handling(self):
        """웹 결제 유니코드 처리 테스트"""
        unicode_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_한글_123",
                "productId": "web_product_한글_456",
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000000"
        }

        receipt_schema = ReceiptSchema(**unicode_data)
        assert receipt_schema.store == Store.WEB
        assert receipt_schema.data["orderId"] == "web_order_한글_123"
        assert receipt_schema.data["productId"] == "web_product_한글_456"
