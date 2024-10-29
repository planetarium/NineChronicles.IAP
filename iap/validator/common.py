from datetime import datetime
from typing import Tuple, Union

from common.enums import Store
from iap.schemas.receipt import ReceiptSchema, SimpleReceiptSchema


def get_order_data(receipt_data: Union[ReceiptSchema, SimpleReceiptSchema]) -> Tuple[str, Union[str, int], datetime]:
    """
    Returns order_id, product_id, purchased_at from receipt data by store
    :param receipt_data:
    :return:
    """
    if receipt_data.store == Store.TEST:
        order_id = receipt_data.data.get("orderId")
        product_id = receipt_data.data.get("productId")
        purchased_at = datetime.fromtimestamp(receipt_data.data.get("purchaseTime"))
    elif receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        order_id = receipt_data.order.get("orderId")
        product_id = receipt_data.order.get("productId")
        purchased_at = datetime.fromtimestamp(receipt_data.order.get("purchaseTime") // 1000)  # Remove millisecond
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        order_id = receipt_data.data.get("TransactionID")
        # product_id = receipt_data.data.get("productId")
        # Apple does not provide productId in receipt data
        product_id = 0
        purchased_at = datetime.utcnow()
    else:
        raise ValueError(f"{receipt_data.store.name} is unsupported store.")

    return order_id, product_id, purchased_at
