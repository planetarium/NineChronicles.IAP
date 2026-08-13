import json
from datetime import datetime, timezone
from typing import Tuple, Union

from shared.enums import Store
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema


def build_google_receipt_data(
    order_id: str, sku: str, purchase_token: str, purchase_time_millis: Union[str, int]
) -> str:
    """구글 결제 조회 결과로 클라이언트가 보냈을 영수증 payload를 합성한다.

    `get_order_data`의 역함수다. 클라이언트가 `/api/purchase/request`를 보내지
    못했을 때 서버가 스토어 조회 결과만으로 같은 경로를 태우기 위해 쓴다.
    `SimpleReceiptSchema`가 파싱하는 형태와 정확히 같아야 한다: `Payload`는 JSON
    문자열이고 그 안의 `json`이 다시 JSON 문자열이다.

    :param source: 합성 출처. 영수증 data에 그대로 저장되어 사후 구분에 쓰인다.
    """
    order = {
        "orderId": order_id,
        "productId": sku,
        "purchaseTime": int(purchase_time_millis),
        "purchaseToken": purchase_token,
    }
    return json.dumps(
        {
            "Store": "GooglePlay",
            "TransactionID": purchase_token,
            "Payload": json.dumps({"json": json.dumps(order), "signature": ""}),
        }
    )


def build_apple_receipt_data(transaction_id: str) -> str:
    """애플 트랜잭션 ID로 영수증 payload를 합성한다.

    애플 검증은 transaction ID로 스토어에 직접 조회하므로 이것만 있으면 된다.
    """
    return json.dumps(
        {
            "Store": "AppleAppStore",
            "TransactionID": transaction_id,
        }
    )


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
