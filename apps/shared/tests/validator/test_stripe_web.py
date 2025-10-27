import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from shared.validator.web import validate_web, validate_web_test
from shared.schemas.receipt import WebPurchaseSchema


class TestStripeValidateWeb:
    """Stripe 웹 결제 검증 테스트"""

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_success(self, mock_retrieve):
        """성공적인 Stripe 결제 검증"""
        # Mock Stripe response
        mock_payment_intent = Mock()
        mock_payment_intent.id = "pi_test123"
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1299  # $12.99
        mock_payment_intent.currency = "usd"
        mock_payment_intent.created = 1761552381
        mock_payment_intent.payment_method = "pm_123"
        mock_payment_intent.livemode = False
        mock_payment_intent.metadata = {"productId": "320", "userId": "user123"}
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is True
        assert msg == ""
        assert purchase is not None
        assert purchase.orderId == "pi_test123"
        assert purchase.productId == "320"
        assert purchase.amount == 1299
        assert purchase.status == "succeeded"

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_payment_not_succeeded(self, mock_retrieve):
        """결제가 succeeded 상태가 아닌 경우"""
        mock_payment_intent = Mock()
        mock_payment_intent.status = "requires_payment_method"
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is False
        assert "not succeeded" in msg
        assert purchase is None

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_product_id_mismatch(self, mock_retrieve):
        """metadata의 productId가 일치하지 않는 경우"""
        mock_payment_intent = Mock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.metadata = {"productId": "999"}
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is False
        assert "Product ID mismatch" in msg
        assert purchase is None

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_amount_mismatch(self, mock_retrieve):
        """금액이 일치하지 않는 경우"""
        mock_payment_intent = Mock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 999  # $9.99
        mock_payment_intent.metadata = {"productId": "320"}
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id="320",
            expected_amount=12.99,  # Expected $12.99
            db_product=Mock()
        )

        assert success is False
        assert "Amount mismatch" in msg
        assert purchase is None

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_stripe_error(self, mock_retrieve):
        """Stripe API 에러 처리"""
        from stripe import InvalidRequestError
        mock_retrieve.side_effect = InvalidRequestError(
            "Invalid payment intent id", "payment_intent_id"
        )

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="invalid_id",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is False
        assert "Invalid Stripe request" in msg
        assert purchase is None


class TestStripeValidateWebTest:
    """Stripe 테스트 모드 검증 테스트"""

    @patch('stripe.PaymentIntent.retrieve')
    def test_validate_web_test_calls_validate_web(self, mock_retrieve):
        """validate_web_test가 validate_web을 호출하는지 확인"""
        mock_payment_intent = Mock()
        mock_payment_intent.id = "pi_test123"
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1299
        mock_payment_intent.currency = "usd"
        mock_payment_intent.created = 1761552381
        mock_payment_intent.payment_method = "pm_123"
        mock_payment_intent.metadata = {"productId": "320"}
        mock_payment_intent.livemode = False
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web_test(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id="320",
            expected_amount=12.99,
            db_product=Mock()
        )

        assert success is True
        assert purchase.livemode is False
