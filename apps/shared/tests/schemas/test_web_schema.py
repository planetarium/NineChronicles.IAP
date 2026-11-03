"""WebPurchaseSchema — a Stripe payment_intent as the web store sees it.

productId comes from the intent metadata (int), amount is in cents (int).
"""
from datetime import datetime, timezone

import pytest

from shared.schemas.receipt import WebPurchaseSchema

WHEN = datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def purchase(**kw):
    data = dict(orderId="pi_test123", productId=320, purchaseDate=WHEN, amount=1299, currency="usd", status="succeeded")
    data.update(kw)
    return WebPurchaseSchema(**data)


def test_creation_with_all_fields():
    p = purchase(paymentMethod="pm_123", metadata={"productId": "320", "avatarAddress": "0x1234"}, livemode=True)
    assert (p.orderId, p.productId, p.purchaseDate, p.amount, p.currency, p.status) == (
        "pi_test123", 320, WHEN, 1299, "usd", "succeeded")
    assert p.paymentMethod == "pm_123"
    assert p.metadata["avatarAddress"] == "0x1234"
    assert p.livemode is True


def test_defaults():
    p = purchase()
    assert (p.paymentMethod, p.metadata, p.livemode) == (None, {}, False)


def test_numeric_strings_are_coerced():
    p = purchase(productId="320", amount="1299")   # Stripe metadata values are strings
    assert (p.productId, p.amount) == (320, 1299)


def test_json_data_uses_timestamp():
    data = purchase().json_data
    assert data["purchaseDate"] == 1640995200.0
    assert (data["orderId"], data["productId"], data["amount"]) == ("pi_test123", 320, 1299)


@pytest.mark.parametrize(
    "bad",
    [
        dict(purchaseDate="invalid_date"),
        dict(amount=9.99),                 # cents only — a float price is a caller bug
        dict(amount="invalid_amount"),
        dict(productId="web_product_456"),  # must be the numeric product id
    ],
)
def test_invalid_values_are_rejected(bad):
    with pytest.raises(ValueError):
        purchase(**bad)


@pytest.mark.parametrize("missing", ["orderId", "productId", "purchaseDate", "amount", "currency", "status"])
def test_required_fields(missing):
    data = dict(orderId="pi_test123", productId=320, purchaseDate=WHEN, amount=1299, currency="usd", status="succeeded")
    data.pop(missing)
    with pytest.raises(ValueError):
        WebPurchaseSchema(**data)
