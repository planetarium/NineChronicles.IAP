"""`/api/purchase/log`가 결제 성공 신호를 남기는지 고정.

이 신호가 남아야 배치(`iap.reconcile_purchase_signal`)가 "결제는 성립했는데
영수증이 없는" 건을 찾아낼 수 있다. 동시에 이 엔드포인트는 로깅용이므로,
기록에 실패하더라도 클라이언트의 구매 흐름을 막아서는 안 된다.

실행: 리포 루트에서 `pytest tests/api/test_purchase_log_signal.py`
"""

import os
import sys

import pytest
from shared.enums import PurchaseSignalStatus

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

TOKEN = "abcdefghijklmnop.AO-J1OxTESTTOKEN"
SKU = "g_pkg_couragepass33premium"
PLANET = "0x000000000000"
AGENT = "0x1234567890123456789012345678901234567890"
AVATAR = "0x0987654321098765432109876543210987654321"


@pytest.fixture(scope="module")
def purchase_api():
    """`apps/api`의 purchase 모듈을 부작용 없이 가져온다.

    모듈 상단에서 sys.path를 건드리면 수집 단계에서 다른 테스트 파일의 import
    결과까지 바뀌므로 실행 시점에만 잠깐 손댔다가 되돌린다. 되돌아오는 건
    sys.path뿐이고 `sys.modules["app"]`은 세션 끝까지 남는다.
    """
    for key in REQUIRED_SETTINGS:
        os.environ.setdefault(f"API_{key}", "test")

    sys.path.insert(0, API_ROOT)
    try:
        from app.api import purchase
    finally:
        sys.path.remove(API_ROOT)
    return purchase


class FakeSession:
    """`scalar` 를 **호출 순서로** 답한다 — 핸들러가 두 번 묻기 때문이다.

      1회차: 같은 토큰의 신호가 이미 있나 (`existing_id`)
      2회차: 그 sku 가 실재 상품인가 (`known_sku` → 상품 id 또는 None)

    2회차가 생긴 건 이 엔드포인트가 **무인증 공개 GET 인데 DB 에 쓰고, 그 행이 지급 대상을
    정하기** 때문이다. 아무 sku 나 쓰게 두면 배치의 처리 창(10분당 50건 FIFO)을 쓰레기가
    채워 진짜 유실 건이 72시간 자동환불 밖으로 밀린다.
    """

    def __init__(self, existing_id=None, fail_on_commit=False, known_sku=True):
        self.existing_id = existing_id
        self.fail_on_commit = fail_on_commit
        self.known_sku = known_sku
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.scalar_calls = 0

    def scalar(self, *_args, **_kwargs):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.existing_id
        return 1 if self.known_sku else None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("db is down")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def call_log(purchase_api, sess, **overrides):
    kwargs = dict(
        planet_id=PLANET,
        agent_address=AGENT,
        avatar_address=AVATAR,
        product_id=SKU,
        order_id=TOKEN,
        data="PurchaseSuccess",
        sess=sess,
    )
    kwargs.update(overrides)
    return purchase_api.log_request_product(**kwargs)


def test_purchase_success_is_recorded(purchase_api):
    sess = FakeSession()

    response = call_log(purchase_api, sess)

    assert response.status_code == 200
    assert len(sess.added) == 1
    signal = sess.added[0]
    assert signal.purchase_token == TOKEN
    assert signal.sku == SKU
    assert signal.planet_id == PLANET
    assert signal.agent_addr == AGENT
    assert signal.avatar_addr == AVATAR
    assert signal.status == PurchaseSignalStatus.RECEIVED


def test_missing_avatar_is_still_recorded(purchase_api):
    """아바타가 없으면 자동 완결은 못 하지만, 알림을 위해 기록은 해야 한다."""
    sess = FakeSession()

    call_log(purchase_api, sess, avatar_address="")

    assert len(sess.added) == 1
    assert sess.added[0].avatar_addr is None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"data": "PurchaseOnClicked"}, id="not-a-success-stage"),
        pytest.param({"data": ""}, id="no-stage"),
        pytest.param({"order_id": ""}, id="no-token"),
    ],
)
def test_non_success_calls_are_not_recorded(purchase_api, overrides):
    sess = FakeSession()

    response = call_log(purchase_api, sess, **overrides)

    assert response.status_code == 200
    assert sess.added == []


def test_duplicate_signal_is_ignored(purchase_api):
    """미소비 결제는 앱을 켤 때마다 다시 보고된다. 지급 대상은 최초 신호로 고정."""
    sess = FakeSession(existing_id=1)

    call_log(purchase_api, sess, agent_address="0xsomeotheraccount")

    assert sess.added == []


def test_storage_failure_does_not_break_the_client(purchase_api):
    sess = FakeSession(fail_on_commit=True)

    response = call_log(purchase_api, sess)

    assert response.status_code == 200
    assert sess.rollbacks == 1


def test_unknown_sku_is_not_recorded(purchase_api):
    """모르는 sku 의 신호는 기록하지 않는다.

    무인증 엔드포인트라 임의 INSERT 가 가능했다. 실재 상품 확인 하나로 그 경로가 대부분
    닫히고, 원스토어 신호가 GOOGLE 로 오판돼 FAILED 로 쌓이던 노이즈도 같이 줄어든다.
    (지급 대상이 무인증 입력에서 온다는 사실 자체는 남는다 — 완화지 해결이 아니다.)
    """
    sess = FakeSession(known_sku=False)

    response = call_log(purchase_api, sess)

    # 클라이언트에겐 여전히 200 이다 — 로깅 엔드포인트라 구매 흐름을 막으면 안 된다.
    assert response.status_code == 200
    assert sess.added == []
