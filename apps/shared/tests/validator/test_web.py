from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pytest
import requests

from shared.enums import Store
from shared.schemas.receipt import WebPurchaseSchema
from shared.validator.web import validate_web, validate_web_test


class TestValidateWeb:
    @patch('shared.validator.web.requests.post')
    def test_validate_web_success(self, mock_post):
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orderId": "web_order_123",
            "productId": "web_product_456",
            "purchaseDate": "2022-01-01T00:00:00Z",
            "amount": 9.99,
            "currency": "USD",
            "status": "completed",
            "paymentMethod": "credit_card",
            "transactionId": "tx_123456",
            "customerId": "customer_789"
        }
        mock_post.return_value = mock_response

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is True
        assert msg == ""
        assert isinstance(purchase, WebPurchaseSchema)
        assert purchase.orderId == "web_order_123"
        assert purchase.productId == "web_product_456"
        assert purchase.amount == 9.99
        assert purchase.currency == "USD"
        assert purchase.status == "completed"

    @patch('shared.validator.web.requests.post')
    def test_validate_web_api_error(self, mock_post):
        # Mock API error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid payment data"
        mock_post.return_value = mock_response

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is False
        assert "Payment validation failed with status 400" in msg
        assert purchase is None

    @patch('shared.validator.web.requests.post')
    def test_validate_web_payment_not_completed(self, mock_post):
        # Mock API response with non-completed status
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orderId": "web_order_123",
            "productId": "web_product_456",
            "purchaseDate": "2022-01-01T00:00:00Z",
            "amount": 9.99,
            "currency": "USD",
            "status": "pending",
            "paymentMethod": "credit_card"
        }
        mock_post.return_value = mock_response

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is False
        assert "Payment status is not completed: pending" in msg
        assert purchase is None

    @patch('shared.validator.web.requests.post')
    def test_validate_web_order_id_mismatch(self, mock_post):
        # Mock API response with different order ID
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orderId": "different_order_456",
            "productId": "web_product_456",
            "purchaseDate": "2022-01-01T00:00:00Z",
            "amount": 9.99,
            "currency": "USD",
            "status": "completed",
            "paymentMethod": "credit_card"
        }
        mock_post.return_value = mock_response

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is False
        assert "Order ID mismatch: expected web_order_123, got different_order_456" in msg
        assert purchase is None

    @patch('shared.validator.web.requests.post')
    def test_validate_web_timeout(self, mock_post):
        # Mock timeout exception
        mock_post.side_effect = requests.exceptions.Timeout()

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is False
        assert "Payment validation request timed out" in msg
        assert purchase is None

    @patch('shared.validator.web.requests.post')
    def test_validate_web_request_exception(self, mock_post):
        # Mock request exception
        mock_post.side_effect = requests.exceptions.RequestException("Connection error")

        success, msg, purchase = validate_web(
            "https://api.payment.com/validate",
            "test_credential",
            "web_order_123",
            "web_product_456",
            {"amount": 9.99, "currency": "USD"}
        )

        assert success is False
        assert "Payment validation request failed: Connection error" in msg
        assert purchase is None


class TestValidateWebTest:
    def test_validate_web_test_success(self):
        success, msg, purchase = validate_web_test(
            "test_order_123",
            "test_product_456",
            {
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "test_card",
                "customerId": "test_customer_789"
            }
        )

        assert success is True
        assert "Test web payment validation successful" in msg
        assert isinstance(purchase, WebPurchaseSchema)
        assert purchase.orderId == "test_order_123"
        assert purchase.productId == "test_product_456"
        assert purchase.amount == 9.99
        assert purchase.currency == "USD"
        assert purchase.status == "completed"
        assert purchase.paymentMethod == "test_card"
        assert purchase.transactionId == "test_tx_test_order_123"
        assert purchase.customerId == "test_customer_789"

    def test_validate_web_test_minimal_data(self):
        success, msg, purchase = validate_web_test(
            "test_order_456",
            "test_product_789",
            {}
        )

        assert success is True
        assert "Test web payment validation successful" in msg
        assert isinstance(purchase, WebPurchaseSchema)
        assert purchase.orderId == "test_order_456"
        assert purchase.productId == "test_product_789"
        assert purchase.amount == 0.0
        assert purchase.currency == "USD"
        assert purchase.status == "completed"
        assert purchase.paymentMethod == "test"
        assert purchase.transactionId == "test_tx_test_order_456"
        assert purchase.customerId is None

    def test_validate_web_test_exception_handling(self):
        # Test with invalid data that might cause an exception
        # This test verifies that the function handles exceptions gracefully
        # We'll test with a different approach by mocking the WebPurchaseSchema creation
        with patch('shared.validator.web.WebPurchaseSchema') as mock_schema:
            mock_schema.side_effect = Exception("Test exception")

            success, msg, purchase = validate_web_test(
                "test_order_123",
                "test_product_456",
                {"amount": 9.99}
            )

            assert success is False
            assert "Error occurred validating test web payment: Test exception" in msg
            assert purchase is None
