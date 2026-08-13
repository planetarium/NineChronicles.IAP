"""합성한 영수증 payload가 실제 파서를 그대로 통과하는지 고정.

클라이언트가 `/api/purchase/request`를 못 보낸 건을 서버가 대신 완결시킬 때,
서명된 원본 payload가 없으므로 스토어 조회 결과로 payload를 합성한다. 그 형태가
`SimpleReceiptSchema`/`get_order_data`가 기대하는 것과 어긋나면 리컨실이 조용히
전부 실패하므로, 빌더와 파서를 왕복으로 묶어둔다.
"""

from datetime import timezone

from shared.enums import Store
from shared.schemas.receipt import SimpleReceiptSchema
from shared.validator.common import (
    build_apple_receipt_data,
    build_google_receipt_data,
    get_order_data,
)

ORDER_ID = "GPA.1234-5678-9012-34567"
SKU = "g_pkg_couragepass33premium"
TOKEN = "abcdefghijklmnop.AO-J1OxTESTTOKEN"
PURCHASE_TIME_MILLIS = "1786242210269"


def test_google_payload_round_trips_through_parser():
    data = build_google_receipt_data(ORDER_ID, SKU, TOKEN, PURCHASE_TIME_MILLIS)

    receipt_data = SimpleReceiptSchema(data=data)
    assert receipt_data.store == Store.GOOGLE

    order_id, product_id, purchased_at = get_order_data(receipt_data)
    assert order_id == ORDER_ID
    assert product_id == SKU
    # 밀리초를 초로 내려 UTC로 해석한다.
    assert purchased_at.tzinfo == timezone.utc
    assert int(purchased_at.timestamp()) == int(PURCHASE_TIME_MILLIS) // 1000


def test_google_payload_keeps_token_where_reconciler_looks_for_it():
    """영수증 매칭이 `data->>'TransactionID'`에 의존한다."""
    receipt_data = SimpleReceiptSchema(
        data=build_google_receipt_data(ORDER_ID, SKU, TOKEN, PURCHASE_TIME_MILLIS)
    )

    assert receipt_data.data["TransactionID"] == TOKEN
    assert receipt_data.order["purchaseToken"] == TOKEN


def test_google_payload_accepts_int_millis():
    data = build_google_receipt_data(ORDER_ID, SKU, TOKEN, int(PURCHASE_TIME_MILLIS))

    order_id, _, _ = get_order_data(SimpleReceiptSchema(data=data))
    assert order_id == ORDER_ID


def test_apple_payload_round_trips_through_parser():
    transaction_id = "370002861954273"

    receipt_data = SimpleReceiptSchema(data=build_apple_receipt_data(transaction_id))
    assert receipt_data.store == Store.APPLE

    order_id, product_id, _ = get_order_data(receipt_data)
    assert order_id == transaction_id
    # 애플 영수증엔 상품 ID가 없어 검증 단계에서 채운다.
    assert product_id == 0
