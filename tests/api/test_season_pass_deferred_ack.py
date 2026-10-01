"""시즌패스 결제의 스토어 확정(ack) 시점 회귀 테스트.

실행: 리포 루트에서 `pytest tests/api/test_season_pass_deferred_ack.py`
(`test_purchase_retry.py` 와 같은 import 전략. CI 는 이미지 빌드만 하므로 수동/로컬 전용.)

## 고정하는 계약

- Google 시즌패스 결제는 **시즌패스 지급 결과를 본 뒤에** ack 한다. 일반 상품은 예전처럼
  검증 직후에 ack 한다.
- 시즌패스가 "지급이 없었음이 확실한" 거절(4xx, 중복 구매 등)을 주면 Google/원스토어
  영수증은 INVALID 로 닫고 ack 하지 않는다 → 스토어 자동환불, 재진입은 dedup 게이트가 400.
- 지급 여부가 불확실하면(그 밖의 5xx, 연결 오류) 예전과 같이 결제를 확정한다 —
  무료 지급을 막는 쪽.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from shared.enums import PackageName, PlanetID, ProductType, ReceiptStatus, Store
from shared.models.product import Product
from shared.schemas.receipt import ReceiptSchema

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

ORDER_ID = "GPA.0000-0000-0000-00000"
TOKEN = "test-purchase-token"
PASS_SKU = "g_pkg_couragepass33premium"
NORMAL_SKU = "g_pkg_daily01"

DUPLICATED = (
    '"Avatar 0x0987654321098765432109876543210987654321 already purchased same or '
    'inclusive product. Duplicated purchase."'
)


@pytest.fixture(scope="module")
def purchase_api():
    for key in REQUIRED_SETTINGS:
        os.environ.setdefault(f"API_{key}", "test")

    sys.path.insert(0, API_ROOT)
    try:
        from app.api import purchase
    finally:
        sys.path.remove(API_ROOT)
    return purchase


class FakeSession:
    """scalar 는 순서대로 돌려준다: dedup 조회(None) → 상품 조회."""

    def __init__(self, product, events):
        self._scalars = [None, product]
        self.events = events
        self.added = []

    def scalar(self, *_a, **_kw):
        return self._scalars.pop(0) if self._scalars else None

    def execute(self, *_a, **_kw):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        pass

    def refresh(self, *_a, **_kw):
        pass

    @property
    def receipt(self):
        return self.added[0]


class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def make_product(sku, **overrides):
    kwargs = dict(
        id=1,
        name="test",
        google_sku=sku,
        product_type=ProductType.IAP,
        open_timestamp=None,
        close_timestamp=None,
        daily_limit=None,
        weekly_limit=None,
        account_limit=None,
        fav_list=[],
        fungible_item_list=[],
    )
    kwargs.update(overrides)
    return Product(**kwargs)


def make_schema(store=Store.GOOGLE, sku=PASS_SKU):
    order = {
        "orderId": ORDER_ID,
        "productId": sku,
        "purchaseTime": 1754800000000,
        "purchaseToken": TOKEN,
        "purchaseId": ORDER_ID,
    }
    payload = {"json": json.dumps(order), "signature": "test-signature"}
    return ReceiptSchema(
        store=store,
        agentAddress="0x1234567890123456789012345678901234567890",
        avatarAddress="0x0987654321098765432109876543210987654321",
        planetId=PlanetID.ODIN,
        data=json.dumps(
            {
                "Store": {Store.ONESTORE: "OneStore", Store.APPLE: "AppleAppStore"}.get(
                    store, "GooglePlay"
                ),
                "TransactionID": ORDER_ID,
                "Payload": json.dumps(payload),
            }
        ),
    )


@pytest.fixture
def env(purchase_api, monkeypatch):
    """외부 호출을 전부 막고 호출 순서를 events 에 기록한다."""
    events = []
    state = {"sp": FakeResp(200, "{}")}

    def fake_post(url, *_a, **_kw):
        events.append("sp_post")
        sp = state["sp"]
        if isinstance(sp, Exception):
            raise sp
        return sp

    monkeypatch.setattr(purchase_api.requests, "post", fake_post)
    monkeypatch.setattr(
        purchase_api, "validate_google", lambda *_a, **_kw: (True, "", None)
    )
    monkeypatch.setattr(
        purchase_api, "ack_google", lambda *_a, **_kw: events.append("google_ack")
    )
    class OneStorePurchase:
        purchaseTime = 1754800000000
        json_data = {}

    monkeypatch.setattr(
        purchase_api,
        "validate_onestore",
        lambda *_a, **_kw: (True, "", OneStorePurchase()),
    )
    monkeypatch.setattr(
        purchase_api,
        "acknowledge_onestore",
        lambda *_a, **_kw: (events.append("onestore_ack"), (True, ""))[1],
    )
    monkeypatch.setattr(purchase_api, "is_onestore_configured", lambda *_a: True)

    class ApplePurchase:
        json_data = {}
        originalPurchaseDate = datetime(2026, 10, 1, tzinfo=timezone.utc)
        productId = "a_pkg_pass"

    monkeypatch.setattr(
        purchase_api, "validate_apple", lambda *_a, **_kw: (True, "", ApplePurchase())
    )
    monkeypatch.setattr(purchase_api, "get_jwt", lambda *_a, **_kw: "jwt")
    monkeypatch.setattr(
        purchase_api.config, "apple_credential", "eA==", raising=False
    )
    monkeypatch.setattr(purchase_api, "create_season_pass_jwt", lambda: "jwt")
    monkeypatch.setattr(purchase_api, "check_required_level", lambda s, r, p: r)
    monkeypatch.setattr(
        purchase_api, "check_purchase_limit", lambda s, r, *_a, **_kw: r
    )
    monkeypatch.setattr(purchase_api, "upsert_mileage", lambda s, p, r: r)
    monkeypatch.setattr(
        purchase_api,
        "send_to_worker",
        lambda *_a, **_kw: events.append("send_to_worker"),
    )
    return events, state


def call(purchase_api, sess, store=Store.GOOGLE, sku=PASS_SKU):
    return purchase_api.request_product(
        make_schema(store, sku), x_iap_packagename=PackageName.NINE_CHRONICLES_M, sess=sess
    )


class TestGoogleSeasonPass:
    def test_지급_성공_뒤에_ack_한다(self, purchase_api, env):
        events, _ = env
        sess = FakeSession(make_product(PASS_SKU), events)

        receipt = call(purchase_api, sess)

        assert receipt.status == ReceiptStatus.VALID
        assert events.count("google_ack") == 1
        # 지급 → 커밋 → ack. 커밋 전에 ack 하면 advisory 락을 쥔 채 외부 왕복을 한다.
        assert events.index("sp_post") < events.index("google_ack")
        assert events[-1] == "google_ack"
        assert events[-2] == "commit"

    @pytest.mark.parametrize(
        "resp",
        [
            pytest.param(FakeResp(500, DUPLICATED), id="duplicated-500"),
            pytest.param(FakeResp(404, '"season not found"'), id="season-404"),
            pytest.param(FakeResp(422, "{}"), id="schema-422"),
        ],
    )
    def test_지급_전_거절이면_INVALID_로_닫고_ack_안_한다(
        self, purchase_api, env, resp
    ):
        events, state = env
        state["sp"] = resp
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(ValueError, match="SeasonPass Upgrade Failed"):
            call(purchase_api, sess)

        assert sess.receipt.status == ReceiptStatus.INVALID
        assert sess.receipt.msg.startswith(f"{resp.status_code} ::")
        assert "google_ack" not in events

    @pytest.mark.parametrize(
        "resp",
        [
            pytest.param(FakeResp(500, '"connection to redis failed"'), id="other-500"),
            pytest.param(FakeResp(502, "bad gateway"), id="502"),
            pytest.param(FakeResp(204, ""), id="read-timeout-204"),
        ],
    )
    def test_지급_여부가_불확실하면_예전처럼_확정한다(self, purchase_api, env, resp):
        events, state = env
        state["sp"] = resp
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(Exception, match="SeasonPass Upgrade Failed") as ei:
            call(purchase_api, sess)

        assert not isinstance(ei.value, ValueError)  # 400 이 아니라 500
        assert sess.receipt.status == ReceiptStatus.VALID
        assert sess.receipt.msg  # /retry 가 msg 를 보고 거절한다
        assert events.count("google_ack") == 1
        assert events.index("commit", events.index("sp_post")) < events.index(
            "google_ack"
        )

    def test_연결_오류면_ack_하고_예외를_그대로_올린다(self, purchase_api, env):
        events, state = env
        state["sp"] = requests.ConnectionError("reset by peer")
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(requests.ConnectionError):
            call(purchase_api, sess)

        assert events.count("google_ack") == 1

    def test_판매기간_밖이면_ack_안_한다(self, purchase_api, env):
        """시즌패스 호출 전 거절(TIME_LIMIT 등)은 이제 자동환불 대상으로 남는다."""
        events, _ = env
        past = datetime.now(timezone.utc) - timedelta(days=1)
        sess = FakeSession(make_product(PASS_SKU, close_timestamp=past), events)

        with pytest.raises(ValueError, match="opening time"):
            call(purchase_api, sess)

        assert sess.receipt.status == ReceiptStatus.TIME_LIMIT
        assert "sp_post" not in events
        assert "google_ack" not in events


    def test_GOOGLE_TEST_도_같은_규칙이다(self, purchase_api, env):
        events, state = env
        state["sp"] = FakeResp(500, DUPLICATED)
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(ValueError):
            call(purchase_api, sess, store=Store.GOOGLE_TEST)

        assert sess.receipt.status == ReceiptStatus.INVALID
        assert "google_ack" not in events


class TestUnchanged:
    def test_일반_상품은_검증_직후에_ack_한다(self, purchase_api, env):
        events, _ = env
        sess = FakeSession(make_product(NORMAL_SKU), events)

        call(purchase_api, sess, sku=NORMAL_SKU)

        assert events.count("google_ack") == 1
        assert events.index("google_ack") < events.index("send_to_worker")

    def test_원스토어_시즌패스_중복구매는_INVALID_로_닫는다(self, purchase_api, env):
        events, state = env
        state["sp"] = FakeResp(500, DUPLICATED)
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(ValueError, match="SeasonPass Upgrade Failed"):
            call(purchase_api, sess, store=Store.ONESTORE)

        assert sess.receipt.status == ReceiptStatus.INVALID
        assert "onestore_ack" not in events

    def test_원스토어_시즌패스_불확실하면_확정한다(self, purchase_api, env):
        events, state = env
        state["sp"] = FakeResp(502, "bad gateway")
        sess = FakeSession(make_product(PASS_SKU), events)

        with pytest.raises(Exception, match="SeasonPass Upgrade Failed"):
            call(purchase_api, sess, store=Store.ONESTORE)

        assert sess.receipt.status == ReceiptStatus.VALID
        assert events.count("onestore_ack") == 1

    @pytest.mark.parametrize(
        "resp",
        [
            pytest.param(FakeResp(500, DUPLICATED), id="duplicated-500"),
            pytest.param(FakeResp(404, "{}"), id="404"),
        ],
    )
    def test_Apple_시즌패스_실패는_예전처럼_VALID_msg(self, purchase_api, env, resp):
        """Apple 은 자동환불이 없다 — INVALID(400)로 닫으면 결제만 계속 재전달된다."""
        events, state = env
        state["sp"] = resp
        sess = FakeSession(make_product(PASS_SKU, apple_sku="a_pkg_pass"), events)

        with pytest.raises(Exception, match="SeasonPass Upgrade Failed") as ei:
            call(purchase_api, sess, store=Store.APPLE)

        assert not isinstance(ei.value, ValueError)
        assert sess.receipt.status == ReceiptStatus.VALID
        assert sess.receipt.msg

    def test_원스토어_시즌패스_성공은_예전처럼_커밋_뒤_ack(self, purchase_api, env):
        events, _ = env
        sess = FakeSession(make_product(PASS_SKU), events)

        call(purchase_api, sess, store=Store.ONESTORE)

        assert events.count("onestore_ack") == 1
        assert "google_ack" not in events


@pytest.mark.parametrize(
    "status_code,text,expected",
    [
        (404, "", True),
        (401, "", True),
        (422, "", True),
        (500, DUPLICATED, True),
        (500, '"Avatar 0x.. is not in premium and doesn\'t request premium."', True),
        (
            500,
            '"Neither premium nor premium_plus requested. Please request at least one."',
            True,
        ),
        (500, '"psycopg2.OperationalError"', False),
        (500, "", False),
        (500, None, False),
        (502, DUPLICATED, False),
        (503, "", False),
        (204, "", False),
    ],
)
def test_season_pass_rejected_before_grant(purchase_api, status_code, text, expected):
    assert (
        purchase_api.season_pass_rejected_before_grant(status_code, text) is expected
    )
