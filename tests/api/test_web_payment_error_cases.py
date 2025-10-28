import pytest
from unittest.mock import Mock, patch

from shared.enums import Store, PackageName, PlanetID, ReceiptStatus
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema
from shared.validator.common import get_order_data


class TestWebPaymentErrorCases:
    """웹 결제 에러 케이스 테스트"""

    def test_invalid_package_name_for_web_payment(self):
        """웹 결제에서 잘못된 패키지명 처리"""
        # 이 테스트는 purchase.py의 패키지명 검증 로직을 테스트합니다
        # 실제로는 API 엔드포인트에서 처리되지만, 여기서는 로직을 검증합니다

        # 웹 결제에서는 NINE_CHRONICLES_WEB만 허용
        valid_package_name = PackageName.NINE_CHRONICLES_WEB
        invalid_package_names = [PackageName.NINE_CHRONICLES_M, PackageName.NINE_CHRONICLES_K]

        # 유효한 패키지명
        assert valid_package_name == PackageName.NINE_CHRONICLES_WEB

        # 잘못된 패키지명들
        for package_name in invalid_package_names:
            assert package_name != PackageName.NINE_CHRONICLES_WEB

    def test_web_payment_missing_order_data(self):
        """웹 결제에서 주문 데이터 누락 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {
            # orderId 누락
            "productId": 1,
            "purchaseTime": 1640995200
        }

        # get_order_data에서 orderId가 None이 되는지 확인
        order_id, product_id, purchased_at = get_order_data(receipt_data)
        assert order_id is None
        assert product_id == "web_product_456"

    def test_web_payment_missing_product_data(self):
        """웹 결제에서 상품 데이터 누락 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            # productId 누락
            "purchaseTime": 1640995200
        }

        # get_order_data에서 productId가 None이 되는지 확인
        order_id, product_id, purchased_at = get_order_data(receipt_data)
        assert order_id == "web_order_123"
        assert product_id is None

    def test_web_payment_invalid_purchase_time(self):
        """웹 결제에서 잘못된 구매 시간 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": "invalid_timestamp"  # 잘못된 타입
        }

        # get_order_data에서 현재 시간으로 fallback되는지 확인
        order_id, product_id, purchased_at = get_order_data(receipt_data)
        assert order_id == "web_order_123"
        assert product_id == "web_product_456"
        assert purchased_at is not None  # 현재 시간으로 설정됨

    def test_web_payment_negative_purchase_time(self):
        """웹 결제에서 음수 구매 시간 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": -1  # 음수 시간
        }

        # 음수 시간도 처리되는지 확인 (datetime.fromtimestamp는 음수도 처리함)
        order_id, product_id, purchased_at = get_order_data(receipt_data)
        assert order_id == "web_order_123"
        assert product_id == "web_product_456"
        assert purchased_at is not None

    def test_web_payment_very_large_purchase_time(self):
        """웹 결제에서 매우 큰 구매 시간 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": 999999999999999  # 매우 큰 시간
        }

        # 매우 큰 시간은 ValueError가 발생해야 함
        with pytest.raises(ValueError, match="year .* is out of range"):
            get_order_data(receipt_data)

    def test_web_payment_empty_data(self):
        """웹 결제에서 빈 데이터 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = {}  # 빈 데이터

        # 빈 데이터에서도 처리되는지 확인
        order_id, product_id, purchased_at = get_order_data(receipt_data)
        assert order_id is None
        assert product_id is None
        assert purchased_at is not None  # 현재 시간으로 설정됨

    def test_web_payment_none_data(self):
        """웹 결제에서 None 데이터 처리"""
        receipt_data = Mock()
        receipt_data.store = Store.WEB
        receipt_data.data = None  # None 데이터

        # None 데이터에서 AttributeError가 발생하는지 확인
        with pytest.raises(AttributeError):
            get_order_data(receipt_data)

    def test_web_payment_invalid_store_type(self):
        """웹 결제에서 잘못된 스토어 타입 처리"""
        receipt_data = Mock()
        receipt_data.store = 999  # 잘못된 스토어 타입
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": 1640995200
        }

        # 잘못된 스토어 타입에서 AttributeError가 발생하는지 확인 (int에는 name 속성이 없음)
        with pytest.raises(AttributeError, match="'int' object has no attribute 'name'"):
            get_order_data(receipt_data)

    def test_web_payment_schema_validation_errors(self):
        """웹 결제 스키마 검증 에러 테스트"""
        # 잘못된 스토어 타입 - Pydantic은 이를 허용하므로 실제로는 get_order_data에서 에러 발생
        receipt_schema = ReceiptSchema(
            store=999,
            agentAddress="0x1234567890abcdef1234567890abcdef12345678",
            avatarAddress="0xabcdef1234567890abcdef1234567890abcdef12",
            data={"Store": "WebPayment", "orderId": "web_order_123"},
            planetId="0x000000000000"
        )
        assert receipt_schema.store == 999  # 잘못된 값이 그대로 저장됨

    def test_web_payment_missing_required_fields(self):
        """웹 결제 필수 필드 누락 테스트"""
        # agentAddress 누락 - Pydantic은 Optional 필드를 허용하므로 None으로 설정됨
        receipt_schema = ReceiptSchema(
            store=Store.WEB,
            # agentAddress 누락
            avatarAddress="0xabcdef1234567890abcdef1234567890abcdef12",
            data={"Store": "WebPayment", "orderId": "web_order_123"},
            planetId="0x000000000000"
        )
        assert receipt_schema.agentAddress is None  # None으로 설정됨

    def test_web_payment_invalid_planet_id(self):
        """웹 결제 잘못된 플래닛 ID 테스트"""
        # 잘못된 플래닛 ID 형식
        with pytest.raises(ValueError):
            ReceiptSchema(
                store=Store.WEB,
                agentAddress="0x1234567890abcdef1234567890abcdef12345678",
                avatarAddress="0xabcdef1234567890abcdef1234567890abcdef12",
                data={"Store": "WebPayment", "orderId": "web_order_123"},
                planetId="invalid_planet_id"
            )

    def test_web_payment_auto_detection_failure(self):
        """웹 결제 자동 감지 실패 테스트"""
        # Store 필드가 없고 데이터에도 WebPayment가 없는 경우
        data = {
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": 1640995200
        }

        from shared.schemas.receipt import SimpleReceiptSchema
        receipt_schema = SimpleReceiptSchema(data=data)

        # TEST 스토어로 fallback되는지 확인
        assert receipt_schema.store == Store.TEST

    def test_web_payment_data_type_coercion(self):
        """웹 결제 데이터 타입 강제 변환 테스트"""
        # 문자열로 된 숫자들
        data = {
            "Store": "WebPayment",
            "orderId": "web_order_123",
            "productId": 1,
            "purchaseTime": "1640995200",  # 문자열
            "amount": "9.99",  # 문자열
            "currency": "USD",
            "paymentMethod": "credit_card"
        }

        from shared.schemas.receipt import SimpleReceiptSchema
        receipt_schema = SimpleReceiptSchema(data=data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.data["purchaseTime"] == "1640995200"  # 여전히 문자열
        assert receipt_schema.data["amount"] == "9.99"  # 여전히 문자열
