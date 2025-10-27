from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from shared.enums import Store
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema
from shared.validator.common import get_order_data


class TestGetOrderData:
    def test_get_order_data_test_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.TEST
        receipt_data.data = {
            "orderId": "test_order_123",
            "productId": "test_product_456",
            "purchaseTime": 1640995200,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "test_order_123"
        assert product_id == "test_product_456"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_google_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.GOOGLE
        receipt_data.order = {
            "orderId": "google_order_789",
            "productId": "google_product_101",
            "purchaseTime": 1640995200000,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "google_order_789"
        assert product_id == "google_product_101"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_google_test_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.GOOGLE_TEST
        receipt_data.order = {
            "orderId": "google_test_order_456",
            "productId": "google_test_product_789",
            "purchaseTime": 1640995200000,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "google_test_order_456"
        assert product_id == "google_test_product_789"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_apple_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.APPLE
        receipt_data.data = {"TransactionID": "apple_transaction_123"}

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "apple_transaction_123"
        assert product_id == 0
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_get_order_data_apple_test_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.APPLE_TEST
        receipt_data.data = {"TransactionID": "apple_test_transaction_456"}

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "apple_test_transaction_456"
        assert product_id == 0
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_get_order_data_unsupported_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = 999

        with pytest.raises(AttributeError):
            get_order_data(receipt_data)

    def test_get_order_data_with_simple_receipt_schema(self):
        receipt_data = Mock(spec=SimpleReceiptSchema)
        receipt_data.store = Store.TEST
        receipt_data.data = {
            "orderId": "simple_order_123",
            "productId": "simple_product_456",
            "purchaseTime": 1640995200,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "simple_order_123"
        assert product_id == "simple_product_456"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_missing_data_keys(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.TEST
        receipt_data.data = {}

        with pytest.raises(TypeError):
            get_order_data(receipt_data)

    def test_get_order_data_google_missing_order_keys(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.GOOGLE
        receipt_data.order = {}

        with pytest.raises(TypeError):
            get_order_data(receipt_data)

    def test_get_order_data_google_missing_purchase_time(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.GOOGLE
        receipt_data.order = {
            "orderId": "google_order_789",
            "productId": "google_product_101",
        }

        with pytest.raises(TypeError):
            get_order_data(receipt_data)

    def test_get_order_data_apple_missing_transaction_id(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.APPLE
        receipt_data.data = {}

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id is None
        assert product_id == 0
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_get_order_data_web_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": "web_product_456",
            "purchaseTime": 1640995200,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "web_order_123"
        assert product_id == "web_product_456"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_web_test_store(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.WEB_TEST
        receipt_data.data = {
            "orderId": "web_test_order_789",
            "productId": "web_test_product_101",
            "purchaseTime": 1640995200,
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "web_test_order_789"
        assert product_id == "web_test_product_101"
        assert purchased_at == datetime.fromtimestamp(1640995200, tz=timezone.utc)

    def test_get_order_data_web_store_missing_purchase_time(self):
        receipt_data = Mock(spec=ReceiptSchema)
        receipt_data.store = Store.WEB
        receipt_data.data = {
            "orderId": "web_order_123",
            "productId": "web_product_456",
        }

        order_id, product_id, purchased_at = get_order_data(receipt_data)

        assert order_id == "web_order_123"
        assert product_id == "web_product_456"
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc
