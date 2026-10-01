"""고정 SKU 시즌패스(C안) 회귀 테스트.

실행: 리포 루트에서 `pytest tests/api/test_fixed_pass_sku.py`
(`test_season_pass_deferred_ack.py` 의 픽스처를 그대로 쓴다. 수동/로컬 전용.)

## 고정하는 계약
- 결제: 고정 SKU 는 **스토어가 검증한 결제 시각**의 시즌 번호(시즌패스 `/current?at=`)와
  그 회차 행의 구성품으로 `/upgrade` 를 부른다. 시즌·회차 행을 못 정하면 시즌패스를 부르기
  전에 거절한다(Google/원스토어는 INVALID → 자동환불).
- 상점: 고정 행에 `{PASS}{시즌}Premium` 이름과 회차 행 구성품을 넣는다. 못 정하면 구매 불가.
  같은 종류 회차 행과 겹치는 이름은 응답에서 뺀다. 고정 행이 없으면 응답은 그대로다.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests
from shared.enums import PlanetID, ReceiptStatus, Store
from shared.models.product import FungibleAssetProduct, FungibleItemProduct

from test_season_pass_deferred_ack import (  # noqa: F401 — 픽스처 재사용
    FakeResp,
    FakeSession,
    call,
    env,
    make_product,
    purchase_api,
)

FIXED_SKU = "g_pkg_couragepasspremium"
PURCHASE_MS = "1790000000000"  # 2026-09-21T...Z
PURCHASE_AT = datetime.fromtimestamp(int(PURCHASE_MS) / 1000, tz=timezone.utc)


def component_row(season=36, **overrides):
    row = make_product(
        f"g_pkg_couragepass{season}premium",
        id=500 + season,
        fungible_item_list=[
            FungibleItemProduct(
                sheet_item_id=400000, name="x", fungible_item_id="Item_NT_400000", amount=50000
            )
        ],
        fav_list=[
            FungibleAssetProduct(ticker="FAV__RUNESTONE_HP", decimal_places=0, amount=100)
        ],
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


@pytest.fixture
def fixed_env(purchase_api, env, monkeypatch):
    events, state = env
    calls = {"fetch": [], "find": [], "upgrade": []}
    state["window"] = purchase_api_window(36)
    state["component"] = component_row(36)

    def fake_fetch(pass_type, planet_id, at=None):
        calls["fetch"].append((pass_type, at))
        w = state["window"]
        if isinstance(w, Exception):
            raise w
        return w

    def fake_find(sess, product, kind, season_index):
        calls["find"].append(season_index)
        return state["component"]

    monkeypatch.setattr(purchase_api, "fetch_season", fake_fetch)
    monkeypatch.setattr(purchase_api, "find_component_product", fake_find)

    class GooglePurchase:
        purchaseTimeMillis = PURCHASE_MS

    monkeypatch.setattr(
        purchase_api, "validate_google", lambda *_a, **_kw: (True, "", GooglePurchase())
    )

    real_post = purchase_api.requests.post

    def recording_post(url, *a, **kw):
        calls["upgrade"].append(kw.get("json"))
        return real_post(url, *a, **kw)

    monkeypatch.setattr(purchase_api.requests, "post", recording_post)
    return events, state, calls


def purchase_api_window(index):
    from app.fixed_pass import SeasonWindow

    now = datetime.now(timezone.utc)
    return SeasonWindow(index, now - timedelta(days=10), now + timedelta(days=20))


def fixed_product(**overrides):
    # 고정 행: 구성품 없음, account_limit 비움(시즌당 1회는 시즌패스가 막는다).
    return make_product(FIXED_SKU, id=900, account_limit=None, **overrides)


class TestPurchase:
    def test_결제시각_시즌과_회차행_구성품으로_지급한다(self, purchase_api, fixed_env):
        events, _, calls = fixed_env
        sess = FakeSession(fixed_product(), events)

        receipt = call(purchase_api, sess, sku=FIXED_SKU)

        assert receipt.status == ReceiptStatus.VALID
        # 시즌 귀속은 Google 이 검증해 준 purchaseTimeMillis 로 한다(클라 Payload 아님).
        assert calls["fetch"] == [("CouragePass", PURCHASE_AT)]
        body = calls["upgrade"][0]
        assert body["pass_type"] == "CouragePass"
        assert body["season_index"] == 36
        assert body["is_premium"] is True and body["is_premium_plus"] is True
        assert body["g_sku"] == FIXED_SKU
        assert {x["ticker"] for x in body["reward_list"]} == {
            "Item_NT_400000",
            "FAV__RUNESTONE_HP",
        }
        assert receipt.data["SeasonPassGrant"] == {
            "season_index": 36,
            "component_product_id": 536,
            "component_sku": "g_pkg_couragepass36premium",
        }
        assert events.count("google_ack") == 1

    @pytest.mark.parametrize(
        "window,component,why",
        [
            pytest.param(None, "default", "no season", id="no-season"),
            pytest.param("default", None, "no component row", id="no-component-row"),
            pytest.param(
                "lookup-error", "default", "season lookup failed", id="lookup-error"
            ),
        ],
    )
    def test_못_정하면_시즌패스를_부르기_전에_거절한다(
        self, purchase_api, fixed_env, window, component, why
    ):
        events, state, calls = fixed_env
        if window is None:
            state["window"] = None
        elif window == "lookup-error":
            from app.fixed_pass import SeasonLookupError

            state["window"] = SeasonLookupError("timeout")
        if component is None:
            state["component"] = None
        sess = FakeSession(fixed_product(), events)

        with pytest.raises(ValueError, match=why):
            call(purchase_api, sess, sku=FIXED_SKU)

        assert sess.receipt.status == ReceiptStatus.INVALID
        assert why in sess.receipt.msg
        assert calls["upgrade"] == []
        assert "sp_post" not in events
        assert "google_ack" not in events

    def test_Apple_은_예전_시즌패스_실패와_같은_모양이다(self, purchase_api, fixed_env):
        events, state, calls = fixed_env
        state["window"] = None
        sess = FakeSession(
            fixed_product(apple_sku="a_pkg_couragepasspremium"), events
        )

        with pytest.raises(Exception, match="no season") as ei:
            call(purchase_api, sess, store=Store.APPLE)

        assert not isinstance(ei.value, ValueError)
        assert sess.receipt.status == ReceiptStatus.VALID
        assert calls["upgrade"] == []
        # Apple 은 서버 확정 대상이 아니다. 시각은 Apple 검증값(originalPurchaseDate).
        assert calls["fetch"][0][1] == datetime(2026, 10, 1, tzinfo=timezone.utc)

    def test_회차_SKU_는_예전_경로_그대로(self, purchase_api, fixed_env):
        events, _, calls = fixed_env
        sess = FakeSession(make_product("g_pkg_couragepass33premium"), events)

        call(purchase_api, sess, sku="g_pkg_couragepass33premium")

        assert calls["fetch"] == []
        assert calls["upgrade"][0]["season_index"] == 33

    def test_account_limit_이_비어도_터지지_않는다(self, purchase_api, fixed_env, monkeypatch):
        """고정 행은 account_limit=None — 예전 코드는 `count > None` TypeError(ack 뒤라 과금 O·지급 X)."""
        events, _, _ = fixed_env
        hit = []
        monkeypatch.setattr(
            purchase_api,
            "check_purchase_limit",
            lambda s, r, *a, **kw: hit.append(kw.get("limit")) or r,
        )
        sess = FakeSession(fixed_product(), events)

        call(purchase_api, sess, sku=FIXED_SKU)

        assert hit == []


# ── 상점 목록 ─────────────────────────────────────────────────────────────────


def schema_of(product):
    # apply_fixed_pass_listing 은 name·fav_list·fungible_item_list 만 바꾼다.
    return SimpleNamespace(name=product.name, fav_list=[], fungible_item_list=[])


class TestListing:
    @pytest.fixture
    def fp(self, purchase_api, monkeypatch):
        from app import fixed_pass

        state = {"window": purchase_api_window(36), "component": component_row(36)}

        def fake_current(pass_type, planet_id):
            w = state["window"]
            if isinstance(w, Exception):
                raise w
            return w

        monkeypatch.setattr(fixed_pass, "current_season_for_listing", fake_current)
        monkeypatch.setattr(
            fixed_pass,
            "find_component_product",
            lambda sess, product, kind, idx: state["component"],
        )
        return fixed_pass, state

    def test_이름과_구성품을_주입한다(self, fp):
        fixed_pass, _ = fp
        product = fixed_product(name="COURAGEPASSPremium")
        schema = schema_of(product)
        from shared.models.product import fixed_pass_kind

        ok = fixed_pass.apply_fixed_pass_listing(
            None, schema, product, fixed_pass_kind(FIXED_SKU), PlanetID.ODIN, {}
        )

        assert ok
        assert schema.name == "COURAGEPASS36Premium"
        assert [x.fungible_item_id for x in schema.fungible_item_list] == ["Item_NT_400000"]
        # FAV 티커는 스키마가 정규화한다(표시용 `RUNESTONE_HP`).
        assert [x.ticker for x in schema.fav_list] == ["RUNESTONE_HP"]

    @pytest.mark.parametrize("what", ["no-season", "no-component", "lookup-error"])
    def test_못_정하면_False(self, fp, what):
        fixed_pass, state = fp
        if what == "no-season":
            state["window"] = None
        elif what == "no-component":
            state["component"] = None
        else:
            state["window"] = fixed_pass.SeasonLookupError("x")
        product = fixed_product(name="COURAGEPASSPremium")
        schema = schema_of(product)
        from shared.models.product import fixed_pass_kind

        assert not fixed_pass.apply_fixed_pass_listing(
            None, schema, product, fixed_pass_kind(FIXED_SKU), PlanetID.ODIN, {}
        )
        assert schema.name == "COURAGEPASSPremium"

    def _categories(self, *product_lists):
        return [SimpleNamespace(product_list=list(pl)) for pl in product_lists]

    def test_고정행이_있으면_같은_종류_회차행과_겹치는_이름을_뺀다(self, fp):
        fixed_pass, _ = fp
        fixed = SimpleNamespace(google_sku=FIXED_SKU, name="COURAGEPASS36Premium")
        legacy36 = SimpleNamespace(
            google_sku="g_pkg_couragepass36premium", name="COURAGEPASS36Premium"
        )
        legacy35 = SimpleNamespace(
            google_sku="g_pkg_couragepass35premium", name="COURAGEPASS35Premium"
        )
        adv = SimpleNamespace(
            google_sku="g_pkg_adventurebosspass23premium", name="ADVENTUREBOSSPASS23Premium"
        )
        adv_dup = SimpleNamespace(
            google_sku="g_pkg_adventurebosspass23premium", name="ADVENTUREBOSSPASS23Premium"
        )
        normal = SimpleNamespace(google_sku="g_pkg_daily01", name="daily")
        cats = self._categories([fixed, legacy36, normal], [legacy35, adv, adv_dup])

        fixed_pass.drop_shadowed_pass_rows(cats)

        assert cats[0].product_list == [fixed, normal]
        # 고정 행이 없는 종류(adventureboss)의 회차 행은 남는다. 이름 중복만 뺀다.
        assert cats[1].product_list == [adv]

    def test_고정행이_없으면_그대로다(self, fp):
        fixed_pass, _ = fp
        a = SimpleNamespace(google_sku="g_pkg_couragepass35premium", name="COURAGEPASS35Premium")
        b = SimpleNamespace(google_sku="g_pkg_couragepass35premium", name="COURAGEPASS35Premium")
        cats = self._categories([a, b])

        fixed_pass.drop_shadowed_pass_rows(cats)

        # 오늘 동작(겹쳐도 손대지 않음)을 바꾸지 않는다.
        assert cats[0].product_list == [a, b]


# ── 시즌 조회 ─────────────────────────────────────────────────────────────────


class TestFetchSeason:
    @pytest.fixture
    def fp(self, purchase_api):
        from app import fixed_pass

        fixed_pass.clear_listing_cache()
        yield fixed_pass
        fixed_pass.clear_listing_cache()

    def _resp(self, status, body=None):
        return SimpleNamespace(status_code=status, text="", json=lambda: body)

    def test_at_은_params_로_UTC_ISO_를_보낸다(self, fp, monkeypatch):
        seen = {}

        def fake_get(url, params=None, timeout=None):
            seen.update(url=url, params=params, timeout=timeout)
            return self._resp(
                200,
                {
                    "season_index": 36,
                    "start_timestamp": "2026-10-01T00:00:00Z",
                    "end_timestamp": "2026-10-31T23:59:59+00:00",
                },
            )

        monkeypatch.setattr(fp.requests, "get", fake_get)
        at = datetime(2026, 10, 2, 9, 0, tzinfo=timezone(timedelta(hours=9)))

        w = fp.fetch_season("CouragePass", PlanetID.ODIN, at=at)

        assert w.season_index == 36
        assert w.contains(datetime(2026, 10, 1, tzinfo=timezone.utc))
        assert seen["url"].endswith("/api/season-pass/current")
        assert seen["params"]["at"] == "2026-10-02T00:00:00+00:00"
        assert seen["params"]["pass_type"] == "CouragePass"
        assert seen["timeout"] == fp.SEASON_LOOKUP_TIMEOUT

    def test_404_는_None_그밖은_SeasonLookupError(self, fp, monkeypatch):
        monkeypatch.setattr(fp.requests, "get", lambda *a, **k: self._resp(404))
        assert fp.fetch_season("CouragePass", PlanetID.ODIN) is None

        monkeypatch.setattr(fp.requests, "get", lambda *a, **k: self._resp(500))
        with pytest.raises(fp.SeasonLookupError):
            fp.fetch_season("CouragePass", PlanetID.ODIN)

        def boom(*a, **k):
            raise requests.ConnectTimeout("x")

        monkeypatch.setattr(fp.requests, "get", boom)
        with pytest.raises(fp.SeasonLookupError):
            fp.fetch_season("CouragePass", PlanetID.ODIN)

    def test_naive_at_거절(self, fp):
        with pytest.raises(ValueError):
            fp.fetch_season("CouragePass", PlanetID.ODIN, at=datetime(2026, 10, 1))

    def test_상점_캐시는_시즌창을_넘기면_버린다(self, fp, monkeypatch):
        now = datetime.now(timezone.utc)
        windows = [
            fp.SeasonWindow(35, now - timedelta(days=30), now - timedelta(seconds=1)),
            fp.SeasonWindow(36, now - timedelta(seconds=1), now + timedelta(days=30)),
        ]
        calls = []

        def fake_fetch(pass_type, planet_id, at=None):
            calls.append(1)
            return windows[min(len(calls) - 1, 1)]

        monkeypatch.setattr(fp, "fetch_season", fake_fetch)

        # 이미 끝난 창은 캐시하지 않는다 → 다음 호출이 다시 묻는다.
        assert fp.current_season_for_listing("CouragePass", PlanetID.ODIN).season_index == 35
        assert fp.current_season_for_listing("CouragePass", PlanetID.ODIN).season_index == 36
        # 유효한 창은 TTL 동안 재사용한다.
        assert fp.current_season_for_listing("CouragePass", PlanetID.ODIN).season_index == 36
        assert len(calls) == 2
