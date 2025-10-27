import requests
from typing import Tuple, Optional
from shared.schemas.receipt import WebPurchaseSchema


def validate_web(
    api_url: str,
    credential: str,
    order_id: str,
    product_id: str,
    payment_data: dict
) -> Tuple[bool, str, Optional[WebPurchaseSchema]]:
    """
    Validate web payment receipt through external payment service API

    Args:
        api_url: External payment service API URL
        credential: API authentication credential
        order_id: Order ID to validate
        product_id: Product ID to validate
        payment_data: Additional payment data for validation

    Returns:
        Tuple of (success, message, WebPurchaseSchema)
    """
    try:
        headers = {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json"
        }

        payload = {
            "orderId": order_id,
            "productId": product_id,
            "paymentData": payment_data
        }

        response = requests.post(api_url, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            return (
                False,
                f"Payment validation failed with status {response.status_code}: {response.text}",
                None
            )

        data = response.json()

        # Check if payment is successful
        if data.get("status") != "completed":
            return (
                False,
                f"Payment status is not completed: {data.get('status')}",
                None
            )

        # Validate order ID matches
        if data.get("orderId") != order_id:
            return (
                False,
                f"Order ID mismatch: expected {order_id}, got {data.get('orderId')}",
                None
            )

        # Create WebPurchaseSchema from response
        web_purchase = WebPurchaseSchema(
            orderId=data["orderId"],
            productId=data["productId"],
            purchaseDate=data["purchaseDate"],
            amount=data["amount"],
            currency=data["currency"],
            status=data["status"],
            paymentMethod=data["paymentMethod"],
            transactionId=data.get("transactionId"),
            customerId=data.get("customerId")
        )

        return True, "", web_purchase

    except requests.exceptions.Timeout:
        return False, "Payment validation request timed out", None
    except requests.exceptions.RequestException as e:
        return False, f"Payment validation request failed: {str(e)}", None
    except Exception as e:
        return False, f"Error occurred validating web payment: {str(e)}", None


def validate_web_test(
    order_id: str,
    product_id: str,
    payment_data: dict
) -> Tuple[bool, str, Optional[WebPurchaseSchema]]:
    """
    Validate web payment receipt for test environment (mock validation)

    Args:
        order_id: Order ID to validate
        product_id: Product ID to validate
        payment_data: Additional payment data for validation

    Returns:
        Tuple of (success, message, WebPurchaseSchema)
    """
    try:
        # Mock validation for test environment
        from datetime import datetime

        web_purchase = WebPurchaseSchema(
            orderId=order_id,
            productId=product_id,
            purchaseDate=datetime.now(),
            amount=payment_data.get("amount", 0.0),
            currency=payment_data.get("currency", "USD"),
            status="completed",
            paymentMethod=payment_data.get("paymentMethod", "test"),
            transactionId=f"test_tx_{order_id}",
            customerId=payment_data.get("customerId")
        )

        return True, "Test web payment validation successful", web_purchase

    except Exception as e:
        return False, f"Error occurred validating test web payment: {str(e)}", None
