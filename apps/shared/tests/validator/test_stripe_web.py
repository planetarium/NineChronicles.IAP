import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from decimal import Decimal

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
        mock_payment_intent.metadata = {"productId": "1", "userId": "user123"}
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id=1,  # int 타입으로 변경
            expected_amount_cents=1299,  # $12.99를 센트 단위로
            db_product=Mock()
        )

        assert success is True
        assert msg == ""
        assert purchase is not None
        assert purchase.orderId == "pi_test123"
        assert purchase.productId == 1  # int 타입으로 변경
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
            expected_product_id=1,  # int 타입으로 변경
            expected_amount_cents=1299,  # $12.99를 센트 단위로
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
            expected_product_id=1,  # int 타입으로 변경
            expected_amount_cents=1299,  # $12.99를 센트 단위로
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
        mock_payment_intent.metadata = {"productId": "1"}
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id=1,  # productId와 일치하도록 수정
            expected_amount_cents=1299,  # Expected $12.99 in cents (but got 999)
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
            expected_amount_cents=1299,  # $12.99 in cents
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
        mock_payment_intent.metadata = {"productId": "1"}
        mock_payment_intent.livemode = False
        mock_retrieve.return_value = mock_payment_intent

        success, msg, purchase = validate_web_test(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id=1,  # int 타입으로 변경
            expected_amount_cents=1299,  # $12.99를 센트 단위로
            db_product=Mock()
        )

        assert success is True
        assert purchase.livemode is False

    @patch('stripe.PaymentIntent.retrieve')
    def test_decimal_to_cents_conversion_precision(self, mock_retrieve):
        """Decimal을 센트 단위로 변환할 때 정밀도 문제가 없는지 테스트"""
        mock_payment_intent = Mock()
        mock_payment_intent.id = "pi_test123"
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1299  # $12.99
        mock_payment_intent.currency = "usd"
        mock_payment_intent.created = 1761552381
        mock_payment_intent.payment_method = "pm_123"
        mock_payment_intent.livemode = False
        mock_payment_intent.metadata = {"productId": "1"}
        mock_retrieve.return_value = mock_payment_intent

        # Decimal에서 센트 단위로 직접 변환 (부동소수점 오차 없음)
        price_decimal = Decimal("12.99")
        expected_amount_cents = int(price_decimal * 100)

        # float 변환을 거치면 오차가 발생할 수 있지만, Decimal 직접 변환은 정확함
        assert expected_amount_cents == 1299

        success, msg, purchase = validate_web(
            stripe_secret_key="sk_test_123",
            stripe_api_version="2025-09-30.clover",
            payment_intent_id="pi_test123",
            expected_product_id=1,
            expected_amount_cents=expected_amount_cents,
            db_product=Mock()
        )

        assert success is True
        assert purchase.amount == 1299

    def test_decimal_to_cents_conversion_edge_cases(self):
        """Decimal을 센트 단위로 변환하는 엣지 케이스 테스트"""
        # 일반적인 가격
        assert int(Decimal("12.99") * 100) == 1299
        assert int(Decimal("0.99") * 100) == 99
        assert int(Decimal("100.00") * 100) == 10000

        # 소수점이 많은 경우
        assert int(Decimal("12.999") * 100) == 1299  # 반올림 없이 truncate
        assert int(Decimal("12.991") * 100) == 1299

        # 큰 금액
        assert int(Decimal("999.99") * 100) == 99999
        assert int(Decimal("1000.00") * 100) == 100000

        # float 변환과 비교 (부동소수점 오차 발생 가능)
        price_float = float(Decimal("12.99"))
        float_cents = int(price_float * 100)
        decimal_cents = int(Decimal("12.99") * 100)

        # 대부분의 경우 같지만, 일부 경우에 차이가 날 수 있음
        # Decimal 변환이 항상 정확함을 보장
        assert decimal_cents == 1299
