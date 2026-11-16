"""retryer 는 접속 주소가 있는 플래닛의 영수증만 send_product 로 다시 보낸다.

주소가 없는 플래닛(내린 thor 등)의 영수증은 다시 보내도 "node is down" 으로 끝난다. 그걸 매분
재전송하면 concurrency=1 인 product_queue 가 처리량보다 빨리 쌓여 다른 플래닛 지급까지 멈춘다
(2026-11-16 인터널: thor 영수증 218건 × 매분 → 대기열 289만 건, heimdall 일반 상품 미지급).

실행: 리포 루트에서 `pytest tests/worker/test_retryer_planets.py` (TEST_DB_URI 필요)
"""

import importlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from shared.enums import PackageName, ProductAssetUISize, ProductType, ReceiptStatus, Store
from shared.models.product import Product
from shared.models.receipt import Receipt

from tests.worker.test_reconcile_purchase_signal import worker_app_imported

ODIN = b"0x000000000000"
HEIMDALL = b"0x000000000001"
THOR = b"0x000000000003"


@pytest.fixture(scope="module")
def retryer():
    with worker_app_imported():
        return importlib.import_module("app.tasks.retryer")


def make_receipt(product: Product, planet_id: bytes) -> Receipt:
    return Receipt(
        store=Store.GOOGLE,
        package_name=PackageName.NINE_CHRONICLES_M.value,
        order_id=f"GPA.test-{uuid.uuid4()}",
        data={},
        status=ReceiptStatus.VALID,
        product_id=product.id,
        planet_id=planet_id,
        agent_addr="0x0",
        avatar_addr="0x0",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )


@pytest.fixture
def receipts(db_session):
    product = Product(
        name="Retryer Planet Test",
        google_sku="g_pkg_retryer_planet_test",
        apple_sku="retryer_planet_test",
        apple_sku_k="retryer_planet_test_k",
        product_type=ProductType.IAP,
        active=True,
        size=ProductAssetUISize.ONE_BY_ONE,
        path="test/retryer.png",
        l10n_key="TEST_RETRYER",
    )
    db_session.add(product)
    db_session.commit()
    rows = {p: make_receipt(product, p) for p in (ODIN, HEIMDALL, THOR)}
    db_session.add_all(rows.values())
    db_session.commit()
    return rows


def found_uuids(retryer, db_session):
    return {r["uuid"] for r in retryer.get_null_tx_status_receipts(db_session)}


def test_skips_planets_without_gql_url(retryer, db_session, receipts, monkeypatch):
    monkeypatch.setattr(
        retryer.config,
        "gql_url_map",
        {ODIN.decode(): "http://odin/graphql", HEIMDALL.decode(): "http://heimdall/graphql"},
    )

    found = found_uuids(retryer, db_session)

    assert receipts[ODIN].uuid in found
    assert receipts[HEIMDALL].uuid in found
    assert receipts[THOR].uuid not in found


def test_empty_gql_url_map_selects_nothing(retryer, db_session, receipts, monkeypatch):
    monkeypatch.setattr(retryer.config, "gql_url_map", {})

    assert not found_uuids(retryer, db_session) & {r.uuid for r in receipts.values()}


def test_retry_task_expires_before_next_round(retryer, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        retryer.app, "send_task", lambda *a, **kw: sent.update(kw) or type("T", (), {"id": "t"})()
    )

    assert retryer.send_uuid_to_worker("u")
    assert sent["expires"] == retryer.RETRY_TASK_EXPIRES_SECONDS == 60
