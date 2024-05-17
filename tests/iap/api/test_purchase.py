import pytest

from iap.validator.apple import validate_apple
from iap.validator.google import validate_google

# Both purchases are test purchase.
TEST_APPLE_ORDER_DATA = {
    'packageName': 'com.planetariumlabs.ninechroniclesmobile',
    "orderId": '2000000458219693'
}
TEST_GOOGLE_ORDER_DATA = {
    'packageName': 'com.planetariumlabs.ninechroniclesmobile',
    'orderId': 'GPA.3392-3387-9900-22421',
    'productId': 'g_single_golddust07',
    'purchaseToken': 'kgdnggbbfpmihiefjmfcgcnc.AO-J1OwoOqlGYPprvDHfRbKNDdvVnsLux3XJldQUIdjsP1lvVAxNmgqofJPgHboMoAaTqL8TjTKMlwlwGxcWVoZLkqbr5VAb6aqXFdZ17_zTuS9tDujCQNqYo6J_oAu_axlHBBCxgUtO',
}
TEST_GOOGLE_FAKE_ORDER_ID = "FKE.1234-1234-1234-00000"


def test_apple_verify_success():
    success, message, data = validate_apple(TEST_APPLE_ORDER_DATA["packageName"], TEST_APPLE_ORDER_DATA["orderId"])
    assert success is True


@pytest.mark.parametrize("order_id", [f"{TEST_APPLE_ORDER_DATA['orderId']}#1", f"{TEST_APPLE_ORDER_DATA['orderId']}&1"])
def test_apple_verify_failure_with_fragment(order_id):
    success, message, data = validate_apple(TEST_APPLE_ORDER_DATA["packageName"], order_id)
    assert success is False


def test_google_verify_success():
    success, message, data = validate_google(
        TEST_GOOGLE_ORDER_DATA["packageName"],
        TEST_GOOGLE_ORDER_DATA["orderId"],
        TEST_GOOGLE_ORDER_DATA["productId"],
        TEST_GOOGLE_ORDER_DATA["purchaseToken"],
    )
    assert success is True


def test_google_verify_failure_with_fake_order_id():
    success, message, data = validate_google(
        TEST_GOOGLE_ORDER_DATA["packageName"],
        TEST_GOOGLE_FAKE_ORDER_ID,
        TEST_GOOGLE_ORDER_DATA["productId"],
        TEST_GOOGLE_ORDER_DATA["purchaseToken"],
    )
    assert success is False
