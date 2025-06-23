from typing import Tuple, Optional

from shared.enums import GooglePurchaseState, PackageName
from shared.utils.google import get_google_client
from shared.schemas.receipt import GooglePurchaseSchema


def ack_google(credential: str, package_name: PackageName, sku: str, token: str):
    client = get_google_client(credential)
    try:
        (
            client.purchases()
            .products()
            .acknowledge(packageName=package_name.value, productId=sku, token=token)
            .execute()
        )
    except Exception as e:
        print(e)


def validate_google(
    credential: str, package_name: str, order_id: str, sku: str, token: str
) -> Tuple[bool, str, Optional[GooglePurchaseSchema]]:
    client = get_google_client(credential)
    try:
        resp = GooglePurchaseSchema(
            **(
                client.purchases()
                .products()
                .get(packageName=package_name, productId=sku, token=token)
                .execute()
            )
        )
        if resp.purchaseState != GooglePurchaseState.PURCHASED:
            return (
                False,
                f"Purchase state of this receipt is not valid: {resp.purchaseState.name}",
                resp,
            )
        if resp.orderId != order_id:
            return (
                False,
                f"Order ID mismatch from request and token: {order_id} :: {resp.orderId}",
                resp,
            )
        return True, "", resp

    except Exception as e:
        return False, f"Error occurred validating google receipt: {e}", None
