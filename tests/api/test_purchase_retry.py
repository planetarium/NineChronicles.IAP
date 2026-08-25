"""`POST /api/purchase/retry` 회귀 테스트.

실행: 리포 루트에서 `pytest tests/api/test_purchase_retry.py`
(import 준비는 아래 모듈 상단에서 자체 처리한다. CI는 이미지 빌드만 하므로
이 테스트는 수동/로컬 실행 전용이다.)

다루는 회귀 셋:

1. `retry_product`는 라우트 핸들러인 `request_product`를 파이썬 함수로 직접 호출한다.
   이때 `sess=Depends(session)` 기본값은 FastAPI가 해결해주지 않으므로 세션을 명시적으로
   넘겨야 한다. 넘기지 않으면 `AttributeError: 'Depends' object has no attribute
   'scalar'` 로 500이 난다. 이 버그는 재시도가 "정말 처리해야 하는" 경우에만 터진다
   (이미 처리된 영수증은 조기 반환되므로). 특히 패스류 상품은 지급이 온체인 tx가 아니라
   시즌패스 경유라 `tx_status`가 영구히 NULL이어서 항상 이 경로를 탄다.
2. 지급에 실패한 영수증은 200으로 돌려주면 안 된다. 클라이언트가 결제를 consume
   (= acknowledge)해버려 스토어 자동환불까지 막히고 유저는 돈만 잃는다.
3. 같은 규칙이 `POST /api/purchase/request`의 멱등 조기반환에도 필요하지만, 거절 기준은
   훨씬 좁다: **"지급이 없었음이 확실한가"**. 틀렸을 때 양방향 다 되돌릴 수 없기 때문이다
   (지급된 결제를 환불 / 지급 없이 confirm). 그래서 INVALID 만 거절한다.
   - `msg`는 실패 신호가 아니다 — tracker가 성공 tx에도 "[null, ...]"을 쓴다.
   - INIT/VALIDATION_REQUEST는 지급 없음을 증명하지 않는다. status=VALID 대입과 commit
     사이에 지급 부수효과가 있어, 지급 후 죽으면 DB에 INIT이 남는다.
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import create_autospec

import pytest
from shared.enums import PackageName, PlanetID, ReceiptStatus, Store, TxStatus
from shared.models.receipt import Receipt
from shared.schemas.receipt import ReceiptSchema, SimpleReceiptSchema

API_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api")

# `apps/api`에 필요한 설정 항목. `app.config.Settings`는 import 시점에 평가된다.
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


@pytest.fixture(scope="module")
def purchase_api():
    """`apps/api`의 purchase 모듈을 부작용 없이 가져온다.

    `apps/api` 내부 모듈은 서로를 top-level `app` 패키지로 import하는데
    `tests/conftest.py`는 `apps/shared`까지만 sys.path에 올린다. 이걸 모듈 상단에서
    처리하면 수집 단계에서 sys.path가 바뀌어 다른 테스트 파일의 import 결과까지
    바꿔버리므로, 실행 시점에만 잠깐 손댔다가 되돌린다.

    되돌아오는 건 `sys.path`뿐이다. `sys.modules["app"]`은 세션이 끝날 때까지
    `apps/api`의 패키지로 남으므로, 나중에 worker 쪽 테스트가 top-level `app`을
    import하면 조용히 이쪽을 집게 된다(현재는 그런 테스트가 없다).
    """
    for key in REQUIRED_SETTINGS:
        os.environ.setdefault(f"API_{key}", "test")

    sys.path.insert(0, API_ROOT)
    try:
        from app.api import purchase
    finally:
        sys.path.remove(API_ROOT)
    return purchase


ORDER_ID = "GPA.0000-0000-0000-00000"
GOOGLE_SKU = "g_pkg_couragepass33premium"


class FakeSession:
    """`sess.scalar()` / `sess.execute()` 만 쓰는 코드 경로를 위한 최소 스텁."""

    def __init__(self, receipt):
        self._receipt = receipt
        self.scalar_calls = 0
        self.execute_calls = []

    def scalar(self, *_args, **_kwargs):
        self.scalar_calls += 1
        return self._receipt

    def execute(self, statement, params=None, *_args, **_kwargs):
        # 중복 검사 앞의 pg_advisory_xact_lock. 스텁은 락을 흉내내지 않고
        #   호출됐다는 사실만 기록한다(직렬화 자체는 실 Postgres 로 검증한다).
        self.execute_calls.append((str(statement), params))
        return None


def make_receipt(**overrides) -> Receipt:
    """지급은 끝났지만 tx_status가 없는 패스 상품 영수증(= 재시도 대상)."""
    kwargs = dict(
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
        msg=None,
    )
    kwargs.update(overrides)
    return Receipt(**kwargs)


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


def call_retry(purchase_api, receipt_data, sess):
    return purchase_api.retry_product(
        receipt_data,
        x_iap_packagename=PackageName.NINE_CHRONICLES_K,
        sess=sess,
    )


def test_retry_returns_receipt_instead_of_raising(purchase_api, receipt_data):
    """세션이 전달되지 않으면 이 호출은 AttributeError로 터진다."""
    receipt = make_receipt()
    sess = FakeSession(receipt)

    assert call_retry(purchase_api, receipt_data, sess) is receipt
    # SELECT 2번(retry_product + 위임받은 request_product)이 전부다:
    # 위임은 기존 영수증을 되돌려줄 뿐 재지급을 트리거하지 않는다.
    assert sess.scalar_calls == 2


def test_retry_forwards_same_session(monkeypatch, purchase_api, receipt_data):
    """위임 시 세션이 그대로 넘어가는지(기본값 Depends가 아닌지) 고정.

    `create_autospec`이라 `request_product` 시그니처가 바뀌면 여기서 잡힌다.
    """
    receipt = make_receipt()
    sess = FakeSession(receipt)
    spy = create_autospec(purchase_api.request_product, return_value=receipt)
    monkeypatch.setattr(purchase_api, "request_product", spy)

    call_retry(purchase_api, receipt_data, sess)

    assert spy.call_args.kwargs["sess"] is sess
    assert spy.call_args.kwargs["x_iap_packagename"] is PackageName.NINE_CHRONICLES_K
    assert spy.call_args.args[0].planetId is PlanetID.ODIN


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": ReceiptStatus.INIT}, id="not-validated"),
        pytest.param({"status": ReceiptStatus.INVALID}, id="invalid"),
        pytest.param({"status": ReceiptStatus.REQUIRED_LEVEL}, id="required-level"),
        pytest.param(
            {"status": ReceiptStatus.PURCHASE_LIMIT_EXCEED}, id="limit-exceeded"
        ),
        # 환불된 결제를 다시 확정시키는 게 결과적으로 가장 나쁘다.
        pytest.param(
            {"status": ReceiptStatus.REFUNDED_BY_BUYER}, id="refunded-by-buyer"
        ),
        pytest.param(
            {"status": ReceiptStatus.REFUNDED_BY_ADMIN}, id="refunded-by-admin"
        ),
        pytest.param(
            {"msg": '500 :: "SeasonPass Upgrade Failed"'}, id="valid-but-failed"
        ),
    ],
)
def test_retry_refuses_undelivered_receipt(purchase_api, receipt_data, overrides):
    """지급 실패 영수증은 200이 아니라 400(ValueError)으로 끝나야 한다.

    200을 주면 클라가 결제를 consume → acknowledge까지 되어 스토어 자동환불이 막힌다.
    """
    sess = FakeSession(make_receipt(**overrides))

    with pytest.raises(ValueError):
        call_retry(purchase_api, receipt_data, sess)


def test_retry_returns_already_handled_receipt(purchase_api, receipt_data):
    """tx가 이미 붙은 영수증은 위임 없이 그대로 반환(기존 동작 고정)."""
    receipt = make_receipt(tx_status=TxStatus.SUCCESS)
    sess = FakeSession(receipt)

    assert call_retry(purchase_api, receipt_data, sess) is receipt
    assert sess.scalar_calls == 1


# --- `POST /api/purchase/request` 의 멱등 조기반환 ------------------------------
#
# 거절 기준은 "지급이 없었음이 확실한가". 확실하지 않으면 전부 200이다.


def request_schema(store=Store.GOOGLE):
    order = {
        "orderId": ORDER_ID,
        "productId": GOOGLE_SKU,
        "purchaseTime": 1754800000000,
        "purchaseToken": "test-purchase-token",
    }
    payload = {"json": json.dumps(order), "signature": "test-signature"}
    return ReceiptSchema(
        store=store,
        agentAddress="0x1234567890123456789012345678901234567890",
        avatarAddress="0x0987654321098765432109876543210987654321",
        planetId=PlanetID.ODIN,
        data=json.dumps(
            {
                "Store": "GooglePlay",
                "TransactionID": "test-purchase-token",
                "Payload": json.dumps(payload),
            }
        ),
    )


def call_request(purchase_api, sess, store=Store.GOOGLE):
    return purchase_api.request_product(
        request_schema(store),
        x_iap_packagename=PackageName.NINE_CHRONICLES_K,
        sess=sess,
    )


# `msg`는 성공 tx에도 붙는다(tracker가 exceptionNames를 무조건 기록).
# 메인넷 실측: status=VALID 732,293건 중 720,143건(98.3%)이 msg를 갖고 있다.
DELIVERED_MSG = '\n[null, null, null, null]'


@pytest.mark.parametrize(
    "overrides",
    [
        # 지급 완료의 대다수 형태. msg를 실패로 읽으면 이게 거절된다.
        pytest.param(
            {"tx_status": TxStatus.SUCCESS, "msg": DELIVERED_MSG}, id="tx-success-msg"
        ),
        pytest.param({"tx_status": TxStatus.SUCCESS}, id="tx-success"),
        # tx가 붙었으면 실패 tx도 조기반환한다(main과 동일. 자동 재지급 경로는 없다).
        pytest.param({"tx_status": TxStatus.FAILURE}, id="tx-failure"),
        pytest.param({"tx_status": TxStatus.STAGED}, id="tx-staged"),
        # 패스 상품: tx가 영구히 없다.
        pytest.param({"status": ReceiptStatus.VALID}, id="pass-delivered"),
        # 패스 지급이 실패해 msg가 남은 형태. /retry 는 이걸 거절하지만 여기선 통과시킨다
        # (지급 여부가 불확실하고, WEB이면 400이 자동환불로 이어진다).
        pytest.param(
            {"msg": '500 :: Internal Server Error'}, id="pass-failed-msg"
        ),
        # 지급 후 commit 전에 죽으면 DB에 INIT이 남는다. 인터널 id=9010 실물 사례.
        pytest.param({"status": ReceiptStatus.INIT}, id="init-may-be-delivered"),
        pytest.param(
            {"status": ReceiptStatus.VALIDATION_REQUEST}, id="validation-request"
        ),
        # ack_google 이후 상태 — 거절해도 환불이 돌아오지 않는다.
        pytest.param(
            {"status": ReceiptStatus.PURCHASE_LIMIT_EXCEED}, id="limit-exceeded"
        ),
        pytest.param({"status": ReceiptStatus.REQUIRED_LEVEL}, id="required-level"),
        pytest.param({"status": ReceiptStatus.TIME_LIMIT}, id="time-limit"),
        # 운영자/유저 환불은 해소 경로로 남긴다.
        pytest.param(
            {"status": ReceiptStatus.REFUNDED_BY_ADMIN}, id="refunded-by-admin"
        ),
        pytest.param(
            {"status": ReceiptStatus.REFUNDED_BY_BUYER}, id="refunded-by-buyer"
        ),
    ],
)
def test_request_returns_receipt_unless_certainly_undelivered(purchase_api, overrides):
    """지급이 없었음이 확실하지 않으면 200이다."""
    receipt = make_receipt(**overrides)
    sess = FakeSession(receipt)

    assert call_request(purchase_api, sess) is receipt
    assert sess.scalar_calls == 1  # 조기반환 — 상품 조회/영수증 생성까지 가지 않는다


@pytest.mark.parametrize(
    "store",
    [
        pytest.param(Store.GOOGLE, id="google"),
        pytest.param(Store.APPLE, id="apple"),
        pytest.param(Store.WEB, id="web"),
    ],
)
def test_request_refuses_invalid(purchase_api, store):
    """INVALID 만 거절한다. 이 함수의 INVALID 대입은 전부 지급 부수효과 앞이다.

    200을 주면 클라가 결제를 consume(= acknowledge)해 스토어 자동환불이 사라진다.
    스토어와 무관하게 같은 판정이어야 한다.
    """
    sess = FakeSession(make_receipt(status=ReceiptStatus.INVALID, tx_status=None))

    with pytest.raises(ValueError, match="is not deliverable"):
        call_request(purchase_api, sess, store)


def test_request_takes_advisory_lock_before_dedup_check(purchase_api):
    """중복 검사 앞에서 (store, order_id) 로 advisory lock 을 잡는지 고정.

    (store, order_id) 에 unique 제약이 없어서, 이 락이 빠지면 동시 요청 둘이
    같이 통과해 영수증이 두 개 만들어지고 지급도 두 번 나간다.
    """
    sess = FakeSession(make_receipt(tx_status=TxStatus.SUCCESS))

    call_request(purchase_api, sess)

    sqls = [sql for sql, _ in sess.execute_calls]
    assert any("SET LOCAL lock_timeout" in s for s in sqls), "대기를 유한하게 묶어야 한다"

    locks = [(sql, params) for sql, params in sess.execute_calls
             if "pg_advisory_xact_lock" in sql]
    assert len(locks) == 1, "락을 정확히 한 번 잡아야 한다"
    # 키에 store 와 order_id 가 모두 들어가야 서로 다른 주문이 직렬화되지 않는다.
    assert locks[0][1]["key"] == f"{Store.GOOGLE.value}:{ORDER_ID}"
