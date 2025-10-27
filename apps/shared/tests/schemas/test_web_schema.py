from datetime import datetime, timezone
import pytest

from shared.schemas.receipt import WebPurchaseSchema


class TestWebPurchaseSchema:
    def test_web_purchase_schema_creation(self):
        purchase = WebPurchaseSchema(
            orderId="web_order_123",
            productId="web_product_456",
            purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            amount=9.99,
            currency="USD",
            status="completed",
            paymentMethod="credit_card",
            transactionId="tx_123456",
            customerId="customer_789"
        )

        assert purchase.orderId == "web_order_123"
        assert purchase.productId == "web_product_456"
        assert purchase.purchaseDate == datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert purchase.amount == 9.99
        assert purchase.currency == "USD"
        assert purchase.status == "completed"
        assert purchase.paymentMethod == "credit_card"
        assert purchase.transactionId == "tx_123456"
        assert purchase.customerId == "customer_789"

    def test_web_purchase_schema_minimal_data(self):
        purchase = WebPurchaseSchema(
            orderId="web_order_123",
            productId="web_product_456",
            purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            amount=9.99,
            currency="USD",
            status="completed",
            paymentMethod="credit_card"
        )

        assert purchase.orderId == "web_order_123"
        assert purchase.productId == "web_product_456"
        assert purchase.amount == 9.99
        assert purchase.currency == "USD"
        assert purchase.status == "completed"
        assert purchase.paymentMethod == "credit_card"
        assert purchase.transactionId is None
        assert purchase.customerId is None

    def test_web_purchase_schema_json_data(self):
        purchase = WebPurchaseSchema(
            orderId="web_order_123",
            productId="web_product_456",
            purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            amount=9.99,
            currency="USD",
            status="completed",
            paymentMethod="credit_card",
            transactionId="tx_123456",
            customerId="customer_789"
        )

        json_data = purchase.json_data

        assert json_data["orderId"] == "web_order_123"
        assert json_data["productId"] == "web_product_456"
        assert json_data["purchaseDate"] == 1640995200.0  # timestamp
        assert json_data["amount"] == 9.99
        assert json_data["currency"] == "USD"
        assert json_data["status"] == "completed"
        assert json_data["paymentMethod"] == "credit_card"
        assert json_data["transactionId"] == "tx_123456"
        assert json_data["customerId"] == "customer_789"

    def test_web_purchase_schema_validation(self):
        # Test with invalid data types
        with pytest.raises(ValueError):
            WebPurchaseSchema(
                orderId="web_order_123",
                productId="web_product_456",
                purchaseDate="invalid_date",  # Should be datetime
                amount=9.99,
                currency="USD",
                status="completed",
                paymentMethod="credit_card"
            )

        with pytest.raises(ValueError):
            WebPurchaseSchema(
                orderId="web_order_123",
                productId="web_product_456",
                purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                amount="invalid_amount",  # Should be float
                currency="USD",
                status="completed",
                paymentMethod="credit_card"
            )

    def test_web_purchase_schema_required_fields(self):
        # Test missing required fields
        with pytest.raises(ValueError):
            WebPurchaseSchema(
                # Missing orderId
                productId="web_product_456",
                purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                amount=9.99,
                currency="USD",
                status="completed",
                paymentMethod="credit_card"
            )

        with pytest.raises(ValueError):
            WebPurchaseSchema(
                orderId="web_order_123",
                # Missing productId
                purchaseDate=datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                amount=9.99,
                currency="USD",
                status="completed",
                paymentMethod="credit_card"
            )
