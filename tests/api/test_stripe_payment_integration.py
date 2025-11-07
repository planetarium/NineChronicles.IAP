import pytest
from unittest.mock import Mock, patch

from shared.enums import Store, PackageName


class TestStripePaymentIntegration:
    """Stripe 결제 통합 테스트"""

    @patch('shared.validator.web.stripe.PaymentIntent.retrieve')
    def test_stripe_payment_success_flow(self, mock_retrieve):
        """성공적인 Stripe 결제 플로우"""
        # Mock Stripe response
        mock_payment_intent = Mock()
        mock_payment_intent.id = "pi_3SMlRZErXvjnwTCw0CKBnYet"
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1299
        mock_payment_intent.currency = "usd"
        mock_payment_intent.created = 1761552381
        mock_payment_intent.payment_method = "pm_123"
        mock_payment_intent.livemode = False
        mock_payment_intent.metadata = {
            "productId": "320",
            "avatarAddress": "0x836F6bA4C0C38d85520E6cB4f301ba1478a69837",
            "planetId": "0x000000000001"
        }
        mock_retrieve.return_value = mock_payment_intent

        # Test validation
        from shared.validator.web import validate_web

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_3SMlRZErXvjnwTCw0CKBnYet",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is True
        assert purchase.metadata["avatarAddress"] == "0x836F6bA4C0C38d85520E6cB4f301ba1478a69837"

    def test_stripe_request_format(self):
        """Stripe 결제 요청 형식 검증"""
        from shared.schemas.receipt import ReceiptSchema

        receipt_data = ReceiptSchema(
            store=Store.WEB,
            agentAddress="0x1234567890abcdef1234567890abcdef12345678",
            avatarAddress="0x836F6bA4C0C38d85520E6cB4f301ba1478a69837",
            data={
                "orderId": "pi_3SMlRZErXvjnwTCw0CKBnYet",
                "productId": "320",
                "purchaseTime": 1761552381
            },
            planetId="0x000000000001"
        )

        assert receipt_data.store == Store.WEB
        assert receipt_data.data["orderId"].startswith("pi_")
