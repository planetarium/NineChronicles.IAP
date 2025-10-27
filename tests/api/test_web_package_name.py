import pytest
from shared.enums import PackageName, Store
from shared.schemas.receipt import ReceiptSchema


class TestWebPackageName:
    def test_web_package_name_enum(self):
        """Test that NINE_CHRONICLES_WEB package name is properly defined"""
        assert PackageName.NINE_CHRONICLES_WEB.value == "com.planetariumlabs.ninechroniclesweb"
        assert str(PackageName.NINE_CHRONICLES_WEB.value) == "com.planetariumlabs.ninechroniclesweb"

    def test_web_package_name_in_receipt_schema(self):
        """Test that web package name can be used in receipt schema"""
        receipt_data = {
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
            "planetId": "0x000000000000"
        }

        receipt_schema = ReceiptSchema(**receipt_data)

        # Test that the schema can be created with web store
        assert receipt_schema.store == Store.WEB
        assert receipt_schema.data["orderId"] == "web_order_123"

    def test_web_test_package_name_in_receipt_schema(self):
        """Test that web test package name can be used in receipt schema"""
        receipt_data = {
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
            "planetId": "0x000000000000"
        }

        receipt_schema = ReceiptSchema(**receipt_data)

        # Test that the schema can be created with web test store
        assert receipt_schema.store == Store.WEB_TEST
        assert receipt_schema.data["orderId"] == "web_test_order_123"

    def test_package_name_comparison(self):
        """Test package name comparisons work correctly"""
        assert PackageName.NINE_CHRONICLES_WEB != PackageName.NINE_CHRONICLES_M
        assert PackageName.NINE_CHRONICLES_WEB != PackageName.NINE_CHRONICLES_K
        assert PackageName.NINE_CHRONICLES_WEB == PackageName.NINE_CHRONICLES_WEB

    def test_package_name_string_representation(self):
        """Test package name string representation"""
        assert str(PackageName.NINE_CHRONICLES_WEB) == "PackageName.NINE_CHRONICLES_WEB"
        assert repr(PackageName.NINE_CHRONICLES_WEB) == "<PackageName.NINE_CHRONICLES_WEB: 'com.planetariumlabs.ninechroniclesweb'>"
