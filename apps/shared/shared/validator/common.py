from datetime import datetime, timezone
from typing import Tuple, Union

from shared.enums import Store
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema

def get_order_data(
    receipt_data: Union[ReceiptSchema, SimpleReceiptSchema],
) -> Tuple[str, Union[str, int], datetime]:
    """
    Returns order_id, product_id, purchased_at from receipt data by store
    :param receipt_data:
    :return:
    """
    if receipt_data.store == Store.TEST:
        order_id = receipt_data.data.get("orderId")
        product_id = receipt_data.data.get("productId")
        purchased_at = datetime.fromtimestamp(receipt_data.data.get("purchaseTime"), tz=timezone.utc)
    elif receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        order_id = receipt_data.order.get("orderId")
        product_id = receipt_data.order.get("productId")
        purchased_at = datetime.fromtimestamp(
            receipt_data.order.get("purchaseTime") // 1000,
            tz=timezone.utc
        )  # Remove millisecond
    elif receipt_data.store == Store.ONESTORE:
        # 봉투가 Google 과 같아 구매 데이터는 `order` 에 들어 있다(schemas/receipt.py).
        # order_id 로 `purchaseId` 를 쓰는 이유: 원스토어 구매 조회 응답에 `orderId` 가
        #   없어서 대조가 안 된다. purchaseId 는 응답에 있고, 클라이언트도 봉투의
        #   TransactionID 로 같은 값을 보낸다(Apple 이 TransactionID 를 쓰는 것과 같은 자리).
        order_id = receipt_data.order.get("purchaseId")
        product_id = receipt_data.order.get("productId")
        purchased_at = datetime.fromtimestamp(
            receipt_data.order.get("purchaseTime") // 1000,
            tz=timezone.utc
        )  # Google 과 같이 밀리초로 온다
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        order_id = receipt_data.data.get("TransactionID")
        # product_id = receipt_data.data.get("productId")
        # Apple does not provide productId in receipt data
        product_id = 0
        purchased_at = datetime.now(timezone.utc)
    elif receipt_data.store in (Store.WEB, Store.WEB_TEST):
        order_id = receipt_data.data.get("orderId")
        product_id = receipt_data.data.get("productId")
        # Web payment data should include purchaseDate (from Stripe validation) or purchaseTime (from client)
        purchase_time = receipt_data.data.get("purchaseDate") or receipt_data.data.get("purchaseTime")
        if isinstance(purchase_time, (int, float)):
            purchased_at = datetime.fromtimestamp(purchase_time, tz=timezone.utc)
        else:
            purchased_at = datetime.now(timezone.utc)
    else:
        raise ValueError(f"{receipt_data.store.name} is unsupported store.")

    return order_id, product_id, purchased_at
