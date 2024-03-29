from typing import Tuple, Optional

from common import logger
from common.enums import GooglePurchaseState
from common.utils.google import get_google_client
from iap import settings
from iap.schemas.receipt import GooglePurchaseSchema


def validate_google(order_id: str, sku: str, token: str) -> Tuple[bool, str, Optional[GooglePurchaseSchema]]:
    client = get_google_client(settings.GOOGLE_CREDENTIAL)
    try:
        resp = GooglePurchaseSchema(
            **(client.purchases().products()
               .get(packageName=settings.GOOGLE_PACKAGE_NAME, productId=sku, token=token)
               .execute())
        )
        if resp.purchaseState != GooglePurchaseState.PURCHASED:
            return False, f"Purchase state of this receipt is not valid: {resp.purchaseState.name}", resp
        if resp.orderId != order_id:
            return False, f"Order ID mismatch from request and token: {order_id} :: {resp.orderId}", resp
        return True, "", resp

    except Exception as e:
        logger.warning(e)
        return False, f"Error occurred validating google receipt: {e}", None
