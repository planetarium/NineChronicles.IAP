import pytest
from unittest.mock import Mock, patch
from decimal import Decimal

from shared.models.product import Product, Price
from shared.enums import Store, ProductType
from shared.schemas.receipt import ReceiptSchema
from shared.validator.common import get_order_data

class TestWebPaymentUnit:
    def test_web_payment_product_model(self):
        """Product 모델 테스트"""
        product = Product(
            id=1,
            name="Test Web Product",
            google_sku="test_sku_320",
            apple_sku="test_apple_sku",
            apple_sku_k="test_apple_sku_k",
            product_type=ProductType.IAP,
            active=True
        )

        assert product.id == 1
        assert product.name == "Test Web Product"
        assert product.google_sku == "test_sku_320"
        assert product.active is True

    def test_web_payment_price_model(self):
        """Price 모델 테스트"""
        price = Price(
            id=1,
            product_id=1,
            price=Decimal("12.99"),  # Decimal 사용
            currency="USD",
            store=Store.WEB,
            regular_price=Decimal("15.99")
        )

        assert price.product_id == 1
        assert float(price.price) == 12.99
        assert price.currency == "USD"
        assert price.store == Store.WEB
        assert float(price.regular_price) == 15.99

    def test_web_payment_receipt_schema_parsing(self):
        """웹 결제 영수증 스키마 파싱 테스트"""
        web_payment_receipt_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "pi_test123",
                "productId": 1,  # Product.id
                "purchaseTime": 1640995200,
                "amount": 12.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "pi_test123"
        assert receipt_schema.data["productId"] == 1
        assert receipt_schema.planetId.value.decode("utf-8") == "0x000000000001"

    def test_web_payment_get_order_data(self):
        """웹 결제에서 get_order_data 함수 테스트"""
        from datetime import datetime, timezone

        web_payment_receipt_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "pi_test123",
                "productId": 1,
                "purchaseTime": 1640995200,
                "amount": 12.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)
        order_id, product_id, purchased_at = get_order_data(receipt_schema)

        assert order_id == "pi_test123"
        assert product_id == 1
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_web_payment_with_purchase_date(self):
        """Stripe 검증 후 purchaseDate가 있는 경우 테스트"""
        from datetime import datetime, timezone

        web_payment_receipt_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "pi_test123",
                "productId": 1,
                "purchaseDate": 1640995200,  # Stripe에서 온 timestamp
                "amount": 12.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)
        order_id, product_id, purchased_at = get_order_data(receipt_schema)

        assert order_id == "pi_test123"
        assert product_id == 1
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc
        # purchaseDate가 purchaseTime보다 우선적으로 사용되어야 함
        expected_time = datetime.fromtimestamp(1640995200, tz=timezone.utc)
        assert purchased_at == expected_time

    def test_web_test_payment_get_order_data(self):
        """웹 테스트 결제에서 get_order_data 함수 테스트"""
        from datetime import datetime, timezone

        web_test_receipt_data = {
            "store": Store.WEB_TEST,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "pi_test456",
                "productId": 2,
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_test_receipt_data)
        order_id, product_id, purchased_at = get_order_data(receipt_schema)

        assert order_id == "pi_test456"
        assert product_id == 2
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_price_decimal_conversion(self):
        """Decimal 가격을 float로 변환하는 테스트"""
        price = Price(
            id=1,
            product_id=1,
            price=Decimal("12.99"),
            currency="USD",
            store=Store.WEB,
            regular_price=Decimal("15.99")
        )

        # Decimal을 float로 변환
        price_float = float(price.price)
        regular_price_float = float(price.regular_price)

        assert price_float == 12.99
        assert regular_price_float == 15.99
        assert isinstance(price_float, float)
        assert isinstance(regular_price_float, float)

    def test_web_payment_store_enum_values(self):
        """웹 결제 스토어 ENUM 값 테스트"""
        assert Store.WEB == 3
        assert Store.WEB_TEST == 93
        assert Store.WEB.name == "WEB"
        assert Store.WEB_TEST.name == "WEB_TEST"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
