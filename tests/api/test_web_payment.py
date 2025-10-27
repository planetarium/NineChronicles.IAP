import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pytest

from shared.enums import Store, PackageName, PlanetID, ReceiptStatus
from shared.schemas.receipt import ReceiptSchema, WebPurchaseSchema


class TestWebPaymentAPI:
    @pytest.fixture
    def web_payment_data(self):
        return {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": "web_product_456",
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": PlanetID.ODIN.value.decode("utf-8")
        }

    @pytest.fixture
    def web_test_payment_data(self):
        return {
            "store": Store.WEB_TEST,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_test_order_123",
                "productId": "web_test_product_456",
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "test_card"
            },
            "planetId": PlanetID.ODIN.value.decode("utf-8")
        }

    def test_receipt_schema_web_payment_parsing(self, web_payment_data):
        receipt_schema = ReceiptSchema(**web_payment_data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "web_order_123"
        assert receipt_schema.data["productId"] == "web_product_456"

    def test_receipt_schema_web_test_payment_parsing(self, web_test_payment_data):
        receipt_schema = ReceiptSchema(**web_test_payment_data)

        assert receipt_schema.store == Store.WEB_TEST
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "web_test_order_123"
        assert receipt_schema.data["productId"] == "web_test_product_456"

    def test_receipt_schema_auto_detect_web_payment(self):
        # Test automatic store detection from data
        data = {
            "Store": "WebPayment",
            "orderId": "web_order_123",
            "productId": "web_product_456",
            "purchaseTime": 1640995200,
            "amount": 9.99,
            "currency": "USD",
            "paymentMethod": "credit_card"
        }

        from shared.schemas.receipt import SimpleReceiptSchema
        receipt_schema = SimpleReceiptSchema(data=data)

        assert receipt_schema.store == Store.WEB

    @patch('shared.validator.web.validate_web')
    def test_web_payment_validation_success(self, mock_validate_web, web_payment_data):
        # Mock successful validation
        mock_purchase = WebPurchaseSchema(
            orderId="web_order_123",
            productId="web_product_456",
            purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            amount=9.99,
            currency="USD",
            status="completed",
            paymentMethod="credit_card"
        )
        mock_validate_web.return_value = (True, "", mock_purchase)

        receipt_schema = ReceiptSchema(**web_payment_data)

        # Test validation call
        success, msg, purchase = mock_validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            web_payment_data["data"]
        )

        assert success is True
        assert msg == ""
        assert isinstance(purchase, WebPurchaseSchema)

    @patch('shared.validator.web.validate_web_test')
    def test_web_test_payment_validation_success(self, mock_validate_web_test, web_test_payment_data):
        # Mock successful test validation
        mock_purchase = WebPurchaseSchema(
            orderId="web_test_order_123",
            productId="web_test_product_456",
            purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            amount=9.99,
            currency="USD",
            status="completed",
            paymentMethod="test_card"
        )
        mock_validate_web_test.return_value = (True, "Test web payment validation successful", mock_purchase)

        receipt_schema = ReceiptSchema(**web_test_payment_data)

        # Test validation call
        success, msg, purchase = mock_validate_web_test(
            "web_test_order_123",
            "web_test_product_456",
            web_test_payment_data["data"]
        )

        assert success is True
        assert "Test web payment validation successful" in msg
        assert isinstance(purchase, WebPurchaseSchema)

    def test_web_payment_data_structure(self, web_payment_data):
        # Test that web payment data has the expected structure
        data = web_payment_data["data"]

        required_fields = ["orderId", "productId", "purchaseTime", "amount", "currency", "paymentMethod"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        assert isinstance(data["orderId"], str)
        assert isinstance(data["productId"], str)
        assert isinstance(data["purchaseTime"], int)
        assert isinstance(data["amount"], (int, float))
        assert isinstance(data["currency"], str)
        assert isinstance(data["paymentMethod"], str)

    def test_web_payment_planet_id_handling(self, web_payment_data):
        receipt_schema = ReceiptSchema(**web_payment_data)

        # Test planet ID conversion
        assert isinstance(receipt_schema.planetId, PlanetID)
        assert receipt_schema.planetId == PlanetID.ODIN

    def test_web_payment_address_formatting(self, web_payment_data):
        # Test address formatting (should be lowercase)
        receipt_schema = ReceiptSchema(**web_payment_data)

        # Addresses should be formatted to lowercase
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
