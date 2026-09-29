"""원스토어 fail-closed 순서 회귀 테스트.

실행: 리포 루트에서 `pytest tests/api/test_onestore_fail_closed.py`
(`test_purchase_retry.py` 와 같은 import 전략을 쓴다. CI 는 이미지 빌드만 하므로
이 테스트는 수동/로컬 실행 전용이다.)

## 고정하는 계약

원스토어 경로 전체가 이 한 가지 성질에 얹혀 있다 —
**시크릿이나 필수 필드가 없으면 `receipt` 행이 만들어지기 전에 끝난다.**

행을 만들어 두고 아래 검증에서 실패하면 그 영수증은 `INVALID` 로 굳는데, dedup 게이트가
`INVALID` 를 종단으로 취급한다(`purchase.py` 의 prev_receipt 주석). 그러면 나중에 시크릿을
배선해도 **그 사이 들어온 실제 결제는 영영 지급되지 않는다.** 아직 아무것도 저장하지 않은
시점에 끝내야 클라이언트가 결제를 consume 하지 않고 다음 회수에서 그대로 재시도한다.

이 성질은 지금까지 주석에만 있었다. 누가 게이트를 `Receipt(...)` 아래로 옮겨도 기존
테스트는 전부 통과한다 — 그래서 여기서 못 박는다.
"""

import json
import os
import sys

import pytest
from shared.enums import PackageName, Store

API_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api")

REQUIRED_SETTINGS = (
    "BACKOFFICE_JWT_SECRET",
    "SEASON_PASS_HOST",
    "SEASON_PASS_JWT_SECRET",
    "GOOGLE_CREDENTIAL",
    "APPLE_CREDENTIAL",
    "APPLE_BUNDLE_ID",
    "APPLE_KEY_ID",
    "APPLE_ISSUER_ID",
    "APPLE_VALIDATION_URL",
    "STRIPE_SECRET_KEY",
    "STRIPE_TEST_SECRET_KEY",
    "CLOUDFLARE_API_KEY",
    "CLOUDFLARE_ASSETS_K_ZONE_ID",
    "CLOUDFLARE_ASSETS_ZONE_ID",
    "CLOUDFLARE_EMAIL",
    "R2_ACCESS_KEY_ID",
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_SECRET_ACCESS_KEY",
    "S3_BUCKET",
    "CLOUDFRONT_DISTRIBUTION_1",
    "CLOUDFRONT_DISTRIBUTION_2",
    "REDEEM_API_BASE_URL",
)

PURCHASE_TOKEN = "onestore-token-0000"
PURCHASE_ID = "PID-0000-0000"
SKU = "g_pkg_couragepass33premium"


@pytest.fixture(scope="module")
def purchase_api():
    """`apps/api` 의 purchase 모듈을 부작용 없이 가져온다(test_purchase_retry 와 동일 전략)."""
    for key in REQUIRED_SETTINGS:
        os.environ.setdefault(f"API_{key}", "test")

    sys.path.insert(0, API_ROOT)
    try:
        from app.api import purchase
    finally:
        sys.path.remove(API_ROOT)
    return purchase


class RecordingSession:
    """`sess.add` 가 **한 번이라도** 불렸는지만 본다. 그게 이 테스트의 전부다."""

    def __init__(self):
        self.added = []
        self.committed = 0

    def scalar(self, *_a, **_kw):
        # 상품 조회. 여기서 None 을 돌려줘도 원스토어 게이트가 그보다 먼저 끝난다.
        return None

    def execute(self, *_a, **_kw):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def refresh(self, *_a, **_kw):
        pass


def make_onestore_receipt_schema(purchase_api, **order_overrides):
    """원스토어 봉투. 클라이언트가 Google 과 **같은 모양**으로 만들어 보낸다."""
    order = {
        "productId": SKU,
        "purchaseId": PURCHASE_ID,
        "purchaseToken": PURCHASE_TOKEN,
        # get_order_data 가 // 1000 을 하므로 없으면 게이트에 닿기도 전에 TypeError 다.
        "purchaseTime": 1790000000000,
    }
    order.update(order_overrides)
    from shared.schemas.receipt import ReceiptSchema

    return ReceiptSchema(
        store=Store.ONESTORE,
        agentAddress="0x1234567890123456789012345678901234567890",
        avatarAddress="0x0987654321098765432109876543210987654321",
        data=json.dumps(
            {
                "Store": "OneStore",
                "TransactionID": PURCHASE_ID,
                "Payload": json.dumps(
                    {"json": json.dumps(order), "signature": "sig"}
                ),
            }
        ),
    )


def _clear_onestore_config(purchase_api, monkeypatch):
    for attr in ("onestore_host", "onestore_client_id", "onestore_client_secret"):
        monkeypatch.setattr(purchase_api.config, attr, None, raising=False)


class TestOneStoreFailClosed:
    def test_시크릿_미배선이면_영수증을_만들지_않는다(self, purchase_api, monkeypatch):
        """이 PR 설계의 핵심 불변식. 행이 생기면 그 결제는 영구 미지급이 된다."""
        _clear_onestore_config(purchase_api, monkeypatch)
        sess = RecordingSession()

        with pytest.raises(ValueError, match="ONE Store credentials are not configured"):
            purchase_api.request_product(
                make_onestore_receipt_schema(purchase_api),
                PackageName.NINE_CHRONICLES_M,
                sess,
            )

        assert sess.added == [], (
            "시크릿이 없는데 영수증 행이 만들어졌다 — dedup 게이트가 INVALID 를 종단으로 "
            "취급하므로 그 결제는 시크릿을 나중에 배선해도 영영 지급되지 않는다"
        )
        assert sess.committed == 0

    @pytest.mark.parametrize("missing", ["purchaseToken", "purchaseId", "productId"])
    def test_필수_필드가_없어도_영수증을_만들지_않는다(
        self, purchase_api, monkeypatch, missing
    ):
        """시크릿은 있지만 봉투가 부실한 경우. 같은 이유로 저장 전에 끝나야 한다."""
        for attr, val in (
            ("onestore_host", "https://iap-apis.onestore.net"),
            ("onestore_client_id", "cid"),
            ("onestore_client_secret", "secret"),
        ):
            monkeypatch.setattr(purchase_api.config, attr, val, raising=False)
        sess = RecordingSession()

        schema = make_onestore_receipt_schema(purchase_api, **{missing: ""})
        with pytest.raises(ValueError, match="must be present in receipt data"):
            purchase_api.request_product(
                schema, PackageName.NINE_CHRONICLES_M, sess
            )

        assert sess.added == []
        assert sess.committed == 0

    def test_게이트가_Receipt_생성보다_앞에_있다(self, purchase_api):
        """
        순서 자체를 소스에서 확인한다.

        위 두 테스트는 "행이 안 생겼다" 는 결과를 보지만, 누가 게이트를 옮기면서 다른 이유로
        예외가 먼저 나면 여전히 통과할 수 있다. 원인 쪽도 같이 고정한다.
        """
        import inspect

        src = inspect.getsource(purchase_api.request_product)
        gate = src.index("ONESTORE_NOT_CONFIGURED")
        create = src.index("receipt = Receipt(")
        assert gate < create, (
            "원스토어 시크릿 게이트가 Receipt 생성보다 뒤로 갔다 — fail-closed 가 깨진다"
        )
