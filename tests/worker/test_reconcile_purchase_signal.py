"""리컨실 배치의 판정표를 고정.

이 배치는 유저 돈이 걸린 방향으로 움직인다. 특히 "지급 없이 ack"은 스토어의
자동 환불까지 없애 버려서 유저가 돈만 잃는다. 그래서 지급 대상이 불명하거나
이미 환불된 결제는 절대 완결로 넘어가면 안 된다.

실행: 리포 루트에서 `pytest tests/worker/test_reconcile_purchase_signal.py`
"""

import importlib
import os
import sys

import pytest
from shared.enums import PurchaseSignalStatus, Store
from shared.models.purchase_signal import PurchaseSignal

WORKER_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "worker")

TOKEN = "abcdefghijklmnop.AO-J1OxTESTTOKEN"
SKU = "g_pkg_couragepass33premium"


@pytest.fixture(scope="module")
def reconciler():
    """`apps/worker`의 배치 모듈을 부작용 없이 가져온다.

    `apps/api`와 `apps/worker` 둘 다 top-level `app` 패키지를 쓴다. 그냥 import하면
    먼저 로드된 쪽이 `sys.modules["app"]`을 선점해 다른 테스트 파일이 조용히
    엉뚱한 패키지를 집게 되므로, import 전후로 `app*`을 갈아끼웠다 되돌린다.

    그리고 **`from app.tasks import reconcile_purchase_signal` 로 가져오면 안 된다.**
    `app/tasks/__init__.py` 가 셀러리 등록을 위해 `from app.tasks.X import X` 를 하는데,
    그 순간 `app.tasks.X` **속성**이 모듈에서 태스크 객체로 덮인다(이 저장소의 모든 태스크가
    모듈명과 함수명이 같아서 전부 그렇다). 그러면 아래 monkeypatch 가 태스크 객체의 없는
    속성을 건드려 AttributeError 로 죽는다. `import_module` 은 `sys.modules` 를 보므로
    그 가림과 무관하게 **모듈**을 준다.
    """
    os.environ.setdefault("WORKER_KMS_KEY_ID", "test")

    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for key in saved:
        del sys.modules[key]

    sys.path.insert(0, WORKER_ROOT)
    try:
        module = importlib.import_module("app.tasks.reconcile_purchase_signal")
    finally:
        sys.path.remove(WORKER_ROOT)
        for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[key]
        sys.modules.update(saved)
    return module


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def make_signal(**overrides) -> PurchaseSignal:
    kwargs = dict(
        purchase_token=TOKEN,
        sku=SKU,
        planet_id="0x000000000000",
        agent_addr="0x1234567890123456789012345678901234567890",
        avatar_addr="0x0987654321098765432109876543210987654321",
        status=PurchaseSignalStatus.RECEIVED,
    )
    kwargs.update(overrides)
    return PurchaseSignal(**kwargs)


@pytest.fixture
def stub(monkeypatch, reconciler):
    """스토어/네트워크 경계를 전부 막고 판정 로직만 남긴다."""

    calls = {"requests": []}

    def configure(
        store=Store.GOOGLE,
        receipt=None,
        purchase=None,
        package="com.planetariumlabs.ninechroniclesmobilek",
        response=FakeResponse(200),
    ):
        monkeypatch.setattr(
            reconciler,
            "resolve_store_and_package",
            lambda sess, sku: (store, object() if store else None, package),
        )
        monkeypatch.setattr(
            reconciler, "find_receipt", lambda sess, store, token: receipt
        )
        monkeypatch.setattr(
            reconciler, "lookup_google_purchase", lambda sku, token: (package, purchase)
        )

        def fake_request(package_name, body):
            calls["requests"].append((package_name, body))
            return response

        monkeypatch.setattr(reconciler, "request_product_via_api", fake_request)
        return calls

    return configure


class FakeReceipt:
    id = 42


def test_matched_receipt_needs_no_action(reconciler, stub):
    stub(receipt=FakeReceipt())
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "matched"
    assert signal.status == PurchaseSignalStatus.MATCHED
    assert signal.receipt_id == 42


def test_dry_run_never_completes(reconciler, stub):
    calls = stub(receipt=None, purchase={"purchaseState": 0})
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=True) == "missing_dry_run"
    assert signal.status == PurchaseSignalStatus.UNRESOLVED
    assert calls["requests"] == [], "드라이런에서는 결제를 건드리면 안 된다"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"avatar_addr": None}, id="no-avatar"),
        pytest.param({"agent_addr": None}, id="no-agent"),
        pytest.param({"planet_id": None}, id="no-planet"),
    ],
)
def test_unknown_target_is_not_completed(reconciler, stub, overrides):
    """지급 대상을 모르면 알림만. 여기서 ack하면 자동 환불까지 막힌다."""
    calls = stub(receipt=None, purchase={"purchaseState": 0})
    signal = make_signal(**overrides)

    assert reconciler.resolve(None, signal, dry_run=False) == "unresolved"
    assert signal.status == PurchaseSignalStatus.UNRESOLVED
    assert calls["requests"] == []


def test_voided_purchase_is_not_completed(reconciler, stub):
    """이미 환불된 결제를 되살리지 않는다."""
    calls = stub(receipt=None, purchase={"purchaseState": 1})
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "voided"
    assert signal.status == PurchaseSignalStatus.VOIDED
    assert calls["requests"] == []


def test_store_lookup_failure_is_not_completed(reconciler, stub):
    calls = stub(receipt=None, purchase=None)
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "lookup_failed"
    assert signal.status == PurchaseSignalStatus.FAILED
    assert calls["requests"] == []


def test_unknown_sku_is_not_completed(reconciler, stub):
    calls = stub(store=None)
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "unknown_sku"
    assert signal.status == PurchaseSignalStatus.FAILED
    assert calls["requests"] == []


def test_completion_replays_the_client_request(reconciler, stub):
    calls = stub(
        receipt=None,
        purchase={
            "purchaseState": 0,
            "orderId": "GPA.1234-5678-9012-34567",
            "purchaseTimeMillis": "1786242210269",
        },
    )
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "completed"
    assert signal.status == PurchaseSignalStatus.COMPLETED

    (package_name, body), = calls["requests"]
    assert package_name == "com.planetariumlabs.ninechroniclesmobilek"
    assert body["agentAddress"] == signal.agent_addr
    assert body["avatarAddress"] == signal.avatar_addr
    assert body["planetId"] == signal.planet_id
    assert body["store"] == int(Store.GOOGLE)
    assert TOKEN in body["data"]


def test_failed_request_is_not_marked_complete(reconciler, stub):
    stub(
        receipt=None,
        purchase={
            "purchaseState": 0,
            "orderId": "GPA.1234-5678-9012-34567",
            "purchaseTimeMillis": "1786242210269",
        },
        response=FakeResponse(400, "Receipt is not deliverable"),
    )
    signal = make_signal()

    assert reconciler.resolve(None, signal, dry_run=False) == "request_failed"
    assert signal.status == PurchaseSignalStatus.FAILED
    assert "400" in signal.msg


def test_every_beat_task_is_registered():
    """beat 가 부르는 이름이 전부 워커에 등록돼 있는가.

    이 배치는 첫 리뷰에서 **등록이 빠진 채** 올라왔다. `app.autodiscover_tasks(["app.tasks"])`
    는 `app.tasks` 패키지를 import 하는 게 전부고 실제 등록은 `app/tasks/__init__.py` 의 명시
    import 가 한다 — 거기 한 줄을 빠뜨리면 beat 는 10분마다 publish 하는데 워커는
    `Received unregistered task of type` 으로 리젝트한다. `task_acks_late=True` 라 메시지는
    그냥 버려지고, **알람도 배치 안에 있으니 안 온다.** 기능이 죽은 걸 아무도 모른다.

    그래서 이름 하나가 아니라 **beat 전체**를 본다. 다음에 태스크를 추가하는 사람도 같은
    구멍에 빠지지 않는다.
    """
    os.environ.setdefault("WORKER_KMS_KEY_ID", "test")

    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for key in saved:
        del sys.modules[key]

    sys.path.insert(0, WORKER_ROOT)
    try:
        celery_app = importlib.import_module("app.celery_app").app
        celery_app.loader.import_default_modules()
        registered = set(celery_app.tasks)
        scheduled = {
            entry["task"] for entry in celery_app.conf.beat_schedule.values()
        }
    finally:
        sys.path.remove(WORKER_ROOT)
        for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[key]
        sys.modules.update(saved)

    assert "iap.reconcile_purchase_signal" in scheduled
    assert not (scheduled - registered), (
        f"beat 가 부르는데 등록되지 않은 태스크: {sorted(scheduled - registered)} "
        "— app/tasks/__init__.py 에 import 를 추가할 것"
    )
