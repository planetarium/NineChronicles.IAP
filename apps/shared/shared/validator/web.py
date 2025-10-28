import stripe
from datetime import datetime, timezone
from typing import Tuple, Optional

from shared.schemas.receipt import WebPurchaseSchema


def validate_web(
    stripe_secret_key: str,
    stripe_api_version: str,
    payment_intent_id: str,
    expected_product_id: str,
    expected_amount: float,
    db_product
) -> Tuple[bool, str, Optional[WebPurchaseSchema]]:
    """
    Stripe Python SDK로 결제 검증

    Args:
        stripe_secret_key: Stripe secret key (sk_live_xxx or sk_test_xxx)
        stripe_api_version: Stripe API version
        payment_intent_id: Payment Intent ID (pi_xxx)
        expected_product_id: 예상 상품 ID
        expected_amount: 예상 금액 (달러 단위)
        db_product: Product 모델 인스턴스

    Returns:
        (success, error_message, WebPurchaseSchema)
    """
    try:
        # Stripe SDK 설정
        stripe.api_key = stripe_secret_key
        stripe.api_version = stripe_api_version

        # PaymentIntent 조회
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        # 1. 결제 상태 확인
        if payment_intent.status != "succeeded":
            return False, f"Payment not succeeded: {payment_intent.status}", None

        # 2. metadata에서 productId 확인
        metadata = payment_intent.metadata or {}
        metadata_product_id = int(metadata.get("productId"))

        if metadata_product_id != expected_product_id:
            return False, f"Product ID mismatch: expected {expected_product_id}, got {metadata_product_id}", None

        # 3. 금액 검증 (센트 단위로 비교)
        stripe_amount = payment_intent.amount
        expected_amount_cents = int(expected_amount * 100)

        if stripe_amount != expected_amount_cents:
            return False, f"Amount mismatch: expected {expected_amount_cents}, got {stripe_amount}", None

        # 4. WebPurchaseSchema 생성
        purchase = WebPurchaseSchema(
            orderId=payment_intent.id,
            productId=metadata_product_id,
            purchaseDate=datetime.fromtimestamp(payment_intent.created, tz=timezone.utc),
            amount=stripe_amount,
            currency=payment_intent.currency,
            status=payment_intent.status,
            paymentMethod=payment_intent.payment_method,
            metadata=dict(metadata),
            livemode=payment_intent.livemode
        )

        return True, "", purchase

    except stripe.InvalidRequestError as e:
        return False, f"Invalid Stripe request: {str(e)}", None
    except stripe.AuthenticationError as e:
        return False, f"Stripe authentication failed: {str(e)}", None
    except stripe.StripeError as e:
        return False, f"Stripe API error: {str(e)}", None
    except Exception as e:
        return False, f"Error validating Stripe payment: {str(e)}", None


def validate_web_test(
    stripe_secret_key: str,
    stripe_api_version: str,
    payment_intent_id: str,
    expected_product_id: str,
    expected_amount: float,
    db_product
) -> Tuple[bool, str, Optional[WebPurchaseSchema]]:
    """
    Stripe test mode로 검증 (validate_web와 동일, test key 사용)
    """
    return validate_web(
        stripe_secret_key,
        stripe_api_version,
        payment_intent_id,
        expected_product_id,
        expected_amount,
        db_product
    )
