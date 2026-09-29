"""원스토어 영수증 봉투 파싱.

클라이언트(`IAPStoreManager.OneStore.cs` 의 `BuildOneStoreReceipt`)가 Google 경로의
Unity IAP 영수증과 **같은 모양**으로 맞춰서 보낸다. `Store` 문자열만 `"OneStore"` 로
다르고, `Payload` 안이 `{json, signature}` 인 것까지 같다. 그래서 서버는 스토어 분기만
추가하면 Google 파싱 로직을 그대로 쓴다 — 이 파일은 그 전제를 고정한다.
"""

import json

import pytest

from shared.enums import PlanetID, Store
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema
from shared.validator.common import get_order_data

# `PurchaseData.PurchaseMeta` (OneStoreCorpPlugins) 필드 그대로.
# purchaseTime 은 Google 과 마찬가지로 밀리초다.
ONESTORE_ORDER = {
    "productId": "g_pkg_worldclearpass1premium",
    "packageName": "com.planetariumlabs.ninechroniclesmobile",
    "orderId": "OS20260902000000001",
    "purchaseId": "SANDBOX_PURCHASE_ID_0001",
    "purchaseToken": "sandbox.purchase.token.0001",
    "developerPayload": "",
    "purchaseState": 0,
    "purchaseTime": 1756800000000,
    "acknowledgeState": 0,
    "recurringState": 0,
    "quantity": 1,
}


def build_onestore_receipt(store: str = "OneStore") -> dict:
    """`BuildOneStoreReceipt` 가 만드는 봉투."""
    return {
        "Store": store,
        # 클라이언트가 TransactionID 에 PurchaseId 를 넣는다. 서버의 order_id 도 같은
        # 값을 쓴다 — 구매 조회 응답이 돌려주는 유일한 식별자라 대조가 되기 때문
        # (응답에 orderId/productId 는 없다). C# 쪽 [Obsolete] 표시와 무관하게
        # 서버 API 는 여전히 purchaseId 로 답한다.
        "TransactionID": ONESTORE_ORDER["purchaseId"],
        "Payload": json.dumps(
            {"json": json.dumps(ONESTORE_ORDER), "signature": "c2lnbmF0dXJl"}
        ),
    }


class TestOneStoreReceiptParsing:
    def test_store_inferred_from_receipt(self):
        """`Store` 를 모르면 TEST 로 떨어져 지급이 안 된다. ONESTORE 로 잡혀야 한다."""
        receipt = SimpleReceiptSchema(data=build_onestore_receipt())

        assert receipt.store == Store.ONESTORE

    def test_payload_parsed_like_google(self):
        receipt = SimpleReceiptSchema(data=build_onestore_receipt())

        assert receipt.payload["signature"] == "c2lnbmF0dXJl"
        assert receipt.order["productId"] == "g_pkg_worldclearpass1premium"
        assert receipt.order["purchaseToken"] == "sandbox.purchase.token.0001"
        assert receipt.order["orderId"] == "OS20260902000000001"
        assert receipt.order["purchaseTime"] == 1756800000000

    def test_data_given_as_json_string(self):
        """클라이언트는 봉투를 직렬화한 문자열로 보낸다."""
        receipt = SimpleReceiptSchema(data=json.dumps(build_onestore_receipt()))

        assert receipt.store == Store.ONESTORE
        assert receipt.order["purchaseToken"] == "sandbox.purchase.token.0001"

    def test_explicit_store_skips_inference(self):
        """store 를 명시로 받는 경로(`/purchase/retry`)에서도 payload 는 파싱돼야 한다."""
        receipt = SimpleReceiptSchema(
            data=build_onestore_receipt(), store=Store.ONESTORE
        )

        assert receipt.store == Store.ONESTORE
        assert receipt.order["productId"] == "g_pkg_worldclearpass1premium"

    def test_full_receipt_schema(self):
        receipt = ReceiptSchema(
            data=build_onestore_receipt(),
            agentAddress="0000000000000000000000000000000000000001",
            avatarAddress="0000000000000000000000000000000000000002",
            planetId="0x000000000000",
        )

        assert receipt.store == Store.ONESTORE
        assert receipt.agentAddress == "0x0000000000000000000000000000000000000001"
        assert receipt.avatarAddress == "0x0000000000000000000000000000000000000002"
        assert receipt.planetId == PlanetID.ODIN
        assert receipt.order["purchaseId"] == "SANDBOX_PURCHASE_ID_0001"


    def test_unknown_store_still_falls_back_to_test(self):
        """모르는 스토어는 TEST 로 떨어진다 — 원스토어 분기가 이걸 바꾸지 않는다."""
        receipt = SimpleReceiptSchema(data=build_onestore_receipt(store="onestore"))

        assert receipt.store == Store.TEST
        assert receipt.order is None


class TestDownstream:
    def test_get_order_data_reads_the_envelope(self):
        """파싱 결과가 `request_product` 첫 문장으로 그대로 흘러간다.

        `order_id` 가 `orderId` 가 아니라 `purchaseId` 인 이유는 common.py 주석 참조.
        """
        receipt = SimpleReceiptSchema(data=build_onestore_receipt())

        order_id, product_id, purchased_at = get_order_data(receipt)

        assert order_id == ONESTORE_ORDER["purchaseId"]
        assert product_id == ONESTORE_ORDER["productId"]
        assert purchased_at.timestamp() == ONESTORE_ORDER["purchaseTime"] / 1000


class TestStoreEnum:
    def test_value_is_pinned(self):
        """값이 바뀌면 이미 쌓인 영수증과 어긋난다.

        정직하게 말하면 이건 파이썬 enum 자기참조라, 진짜 결합 두 곳은 여전히 여기서
        검증되지 않는다: 클라이언트 생성 enum(`InAppPurchaseServiceClient.cs` 의 `Store`
        와 `StoreTypeConverter.InvalidEnumMapping`)과 PG `store` 타입의 라벨 집합.
        """
        assert Store.ONESTORE.value == 4

    def test_no_sandbox_twin(self):
        """`ONESTORE_TEST` 는 일부러 없다 — 세팅할 주체가 없어서다(enums.py 주석).

        되살릴 거면 95 로 되살려라. 94 는 REDEEM 이 쓰고 있다.
        """
        assert "ONESTORE_TEST" not in Store.__members__
        assert Store.REDEEM.value == 94

    def test_google_receipt_still_infers_google(self):
        receipt = SimpleReceiptSchema(data=build_onestore_receipt(store="GooglePlay"))

        assert receipt.store == Store.GOOGLE
