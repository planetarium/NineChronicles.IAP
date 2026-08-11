"""`POST /api/purchase/retry` 회귀 테스트.

`retry_product`는 라우트 핸들러인 `request_product`를 파이썬 함수로 직접 호출한다.
이때 `sess=Depends(session)` 기본값은 FastAPI가 해결해주지 않으므로 세션을 명시적으로
넘겨야 한다. 넘기지 않으면 `request_product` 안에서
`AttributeError: 'Depends' object has no attribute 'scalar'` 가 나면서 500이 된다.

이 버그는 재시도가 "정말 처리해야 하는" 경우에만 터진다(이미 처리된 영수증은 조기
반환되므로). 특히 패스류 상품은 지급이 온체인 tx가 아니라 시즌패스 경유라 `tx_status`가
영구히 NULL이어서 항상 이 경로를 탄다.
"""

import json
import os
from datetime import datetime, timezone

import pytest

# `app.config.Settings`는 import 시점에 평가되므로 필수 값들을 먼저 채워둔다.
for _key in (
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
):
    os.environ.setdefault(f"API_{_key}", "test")

from app.api import purchase as purchase_api  # noqa: E402
from shared.enums import PackageName, PlanetID, ReceiptStatus, Store  # noqa: E402
from shared.models.receipt import Receipt  # noqa: E402
from shared.schemas.receipt import SimpleReceiptSchema  # noqa: E402

ORDER_ID = "GPA.0000-0000-0000-00000"
GOOGLE_SKU = "g_pkg_couragepass33premium"


class FakeSession:
    """`sess.scalar()`만 쓰는 코드 경로를 위한 최소 스텁."""

    def __init__(self, receipt):
        self._receipt = receipt
        self.scalar_calls = 0

    def scalar(self, *_args, **_kwargs):
        self.scalar_calls += 1
        return self._receipt


@pytest.fixture
def receipt_data():
    order = {
        "orderId": ORDER_ID,
        "productId": GOOGLE_SKU,
        "purchaseTime": 1754800000000,
        "purchaseToken": "test-purchase-token",
    }
    payload = {"json": json.dumps(order), "signature": "test-signature"}
    return SimpleReceiptSchema(
        data=json.dumps(
            {
                "Store": "GooglePlay",
                "TransactionID": "test-purchase-token",
                "Payload": json.dumps(payload),
            }
        )
    )


@pytest.fixture
def pending_receipt():
    """지급은 끝났지만 tx_status가 없는 패스 상품 영수증(= 재시도 대상)."""
    return Receipt(
        store=Store.GOOGLE,
        order_id=ORDER_ID,
        package_name=PackageName.NINE_CHRONICLES_K.value,
        data={},
        status=ReceiptStatus.VALID,
        purchased_at=datetime.now(tz=timezone.utc),
        agent_addr="0x1234567890123456789012345678901234567890",
        avatar_addr="0x0987654321098765432109876543210987654321",
        planet_id=PlanetID.ODIN.value,
        tx_status=None,
    )


def test_retry_returns_receipt_instead_of_raising(receipt_data, pending_receipt):
    """세션이 전달되지 않으면 이 호출은 AttributeError로 터진다."""
    sess = FakeSession(pending_receipt)

    result = purchase_api.retry_product(
        receipt_data,
        x_iap_packagename=PackageName.NINE_CHRONICLES_K,
        sess=sess,
    )

    assert result is pending_receipt
    # retry_product에서 한 번, 위임받은 request_product에서 한 번.
    assert sess.scalar_calls == 2


def test_retry_forwards_same_session(monkeypatch, receipt_data, pending_receipt):
    """위임 시 세션이 그대로 넘어가는지(기본값 Depends가 아닌지) 고정."""
    sess = FakeSession(pending_receipt)
    captured = {}

    def fake_request_product(receipt_schema, x_iap_packagename=None, sess=None):
        captured["sess"] = sess
        captured["x_iap_packagename"] = x_iap_packagename
        return pending_receipt

    monkeypatch.setattr(purchase_api, "request_product", fake_request_product)

    purchase_api.retry_product(
        receipt_data,
        x_iap_packagename=PackageName.NINE_CHRONICLES_K,
        sess=sess,
    )

    assert captured["sess"] is sess
    assert captured["x_iap_packagename"] is PackageName.NINE_CHRONICLES_K
