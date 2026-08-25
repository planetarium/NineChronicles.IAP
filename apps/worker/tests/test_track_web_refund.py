"""
(PLD-1470) WEB(Stripe) 환불 → 바우처 회수 트래커 테스트.

Stripe API 는 전부 mock 이다 — 실 호출·실 시크릿·DB 쓰기 없음.
"""
import datetime
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tasks import voucher_reconcile_task as vr
from shared.enums import Store

# ⚠️ app/tasks/__init__.py 가 같은 이름의 **태스크**를 패키지 속성으로 덮어쓰기 때문에
#    `from app.tasks import track_web_refund` 는 모듈이 아니라 celery 프록시를 준다
#    (그러면 patch.object 가 모듈 전역이 아닌 Task 객체에 붙어 아무 효과가 없다 —
#     test_track_google_refund 의 문자열 패치가 실제로는 안 먹는 이유도 같다).
tw = importlib.import_module("app.tasks.track_web_refund")


def _refund(payment_intent, status="succeeded"):
    """stripe.Refund 의 우리가 쓰는 표면만 흉내낸 값객체(속성 접근)."""
    return SimpleNamespace(id="re_dummy", payment_intent=payment_intent, status=status)


def _stripe_returning(refunds):
    """tw.stripe 를 대체할 mock. Refund.list(...).auto_paging_iter() 가 refunds 를 흘린다."""
    mock_stripe = MagicMock()
    mock_stripe.Refund.list.return_value.auto_paging_iter.return_value = iter(refunds)
    return mock_stripe


class TestGating:
    """휴면/킬스위치 — 어느 쪽이든 Stripe 를 **부르기 전에** 끊겨야 한다."""

    def test_noop_when_voucher_grant_disabled(self):
        mock_stripe = _stripe_returning([_refund("pi_1")])
        with patch.object(tw.config, "voucher_grant_enabled", False), \
            patch.object(tw.config, "stripe_secret_key", "sk_test_dummy"), \
            patch.object(tw, "stripe", mock_stripe), \
            patch.object(tw, "enqueue_revoke_by_order_ids") as enqueue:
            assert tw.handle() == "voucher grant disabled"
        mock_stripe.Refund.list.assert_not_called()
        enqueue.assert_not_called()

    def test_noop_when_secret_missing(self):
        # 메인넷엔 아직 WORKER_STRIPE_SECRET_KEY 가 없다 → 이미지만 올라가도 아무 일 없어야 한다.
        mock_stripe = _stripe_returning([_refund("pi_1")])
        with patch.object(tw.config, "voucher_grant_enabled", True), \
            patch.object(tw.config, "stripe_secret_key", None), \
            patch.object(tw, "stripe", mock_stripe), \
            patch.object(tw, "enqueue_revoke_by_order_ids") as enqueue:
            assert tw.handle() == "stripe secret not configured"
        mock_stripe.Refund.list.assert_not_called()
        enqueue.assert_not_called()

    def test_task_wrapper_delegates_to_handle(self):
        with patch.object(tw, "handle", return_value="ok") as h:
            assert tw.track_web_refund.run() == "ok"
            h.assert_called_once_with()


class TestRevocableOrderIds:
    def test_only_succeeded_and_pending(self):
        # failed/canceled 는 돈이 돌아가지 않았으므로 회수 대상이 아니다.
        refunds = [
            _refund("pi_ok", "succeeded"),
            _refund("pi_pending", "pending"),
            _refund("pi_failed", "failed"),
            _refund("pi_canceled", "canceled"),
            _refund("pi_action", "requires_action"),
        ]
        order_ids, pending_only = tw._revocable_order_ids(refunds)
        assert order_ids == ["pi_ok", "pi_pending"]
        # 뒤집힘 위험이 가장 큰 subset 을 따로 뽑아 로그에 남긴다(오회수 사후 추적).
        assert pending_only == ["pi_pending"]

    def test_dedups_partial_refunds_of_same_payment_intent(self):
        refunds = [_refund("pi_same"), _refund("pi_same"), _refund("pi_other")]
        order_ids, _ = tw._revocable_order_ids(refunds)
        assert order_ids == ["pi_same", "pi_other"]

    def test_pending_plus_succeeded_is_not_pending_only(self):
        # 같은 PI 에 pending + succeeded 가 섞이면 이미 확정된 환불이므로 pending-only 가 아니다.
        refunds = [_refund("pi_mixed", "pending"), _refund("pi_mixed", "succeeded")]
        order_ids, pending_only = tw._revocable_order_ids(refunds)
        assert order_ids == ["pi_mixed"] and pending_only == []

    def test_skips_refund_without_payment_intent(self):
        # Charge 직접 환불(payment_intent=None)은 WEB 결제 경로가 아니다.
        refunds = [_refund(None), _refund(""), _refund(MagicMock()), _refund("pi_ok")]
        order_ids, _ = tw._revocable_order_ids(refunds)
        assert order_ids == ["pi_ok"]


class TestHandle:
    def _run(self, refunds, queued=0, lookback_hours=24):
        mock_stripe = _stripe_returning(refunds)
        with patch.object(tw.config, "voucher_grant_enabled", True), \
            patch.object(tw.config, "stripe_secret_key", "sk_test_dummy"), \
            patch.object(tw.config, "stripe_api_version", "2025-09-30.clover"), \
            patch.object(tw.config, "stripe_refund_lookback_hours", lookback_hours), \
            patch.object(tw, "stripe", mock_stripe), \
            patch.object(
                tw, "enqueue_revoke_by_order_ids", return_value=queued
            ) as enqueue:
            result = tw.handle()
        return result, mock_stripe, enqueue

    def test_matched_refunds_are_enqueued_with_web_stores(self):
        result, _, enqueue = self._run([_refund("pi_A"), _refund("pi_B")], queued=2)
        assert enqueue.call_args.args[0] == ["pi_A", "pi_B"]
        # 스토어 화이트리스트를 반드시 WEB 계열로 넘겨야 한다(구글 영수증 오회수 방지).
        assert enqueue.call_args.kwargs["stores"] == vr.WEB_STORES
        assert result == "refunds=2 revocable=2 queued=2"

    def test_stripe_called_with_secret_and_lookback_window(self):
        before = datetime.datetime.now(datetime.timezone.utc)
        _, mock_stripe, _ = self._run([])
        kwargs = mock_stripe.Refund.list.call_args.kwargs
        assert kwargs["api_key"] == "sk_test_dummy"
        assert kwargs["stripe_version"] == "2025-09-30.clover"
        assert kwargs["limit"] == tw.PAGE_SIZE
        expected = int((before - datetime.timedelta(hours=24)).timestamp())
        # 룩백 윈도우 경계(초 단위 오차 허용). 커서 없이 겹침으로 유실을 막는 전략의 고정점.
        assert abs(kwargs["created"]["gte"] - expected) <= 5

    def test_lookback_is_configurable(self):
        # 컷오버 때 재배포 없이 광역 스캔을 돌릴 수 있어야 한다(홀드 72h > 기본 룩백 24h).
        before = datetime.datetime.now(datetime.timezone.utc)
        _, mock_stripe, _ = self._run([], lookback_hours=96)
        expected = int((before - datetime.timedelta(hours=96)).timestamp())
        assert abs(mock_stripe.Refund.list.call_args.kwargs["created"]["gte"] - expected) <= 5

    def test_invalid_lookback_falls_back_to_default(self):
        # 창이 0 이면 신호가 조용히 끊긴다 → 기본값으로 되돌린다.
        before = datetime.datetime.now(datetime.timezone.utc)
        for bad in (0, -5, None):
            _, mock_stripe, _ = self._run([], lookback_hours=bad)
            expected = int((before - datetime.timedelta(hours=24)).timestamp())
            assert abs(mock_stripe.Refund.list.call_args.kwargs["created"]["gte"] - expected) <= 5

    def test_no_refunds_is_noop(self):
        result, _, enqueue = self._run([])
        # order_ids 가 비면 enqueue 헬퍼가 즉시 0을 반환한다(호출 자체는 무해).
        assert enqueue.call_args.args[0] == []
        assert result == "refunds=0 revocable=0 queued=0"

    def test_unmatched_refunds_do_not_fail(self):
        # Stripe 계정엔 IAP 영수증과 무관한 환불도 섞일 수 있다 → 미매칭은 정상이고 오류가 아니다.
        result, _, _ = self._run([_refund("pi_unknown")], queued=0)
        assert result == "refunds=1 revocable=1 queued=0"

    def test_caps_refund_scan(self):
        # 최신순이라 잘리는 쪽은 가장 오래된 건(=이전 실행이 이미 처리) → 상한이 신규 유실을 만들지 않는다.
        many = [_refund(f"pi_{i}") for i in range(tw.MAX_REFUNDS + 10)]
        result, _, enqueue = self._run(many, queued=tw.MAX_REFUNDS)
        assert len(enqueue.call_args.args[0]) == tw.MAX_REFUNDS
        assert result.startswith(f"refunds={tw.MAX_REFUNDS} ")


class TestScanFailureAlerting:
    """신호원이 조용히 죽는 것(키 폐기·refund:read 누락 등)을 경보로 드러내야 한다."""

    def _fail_once(self, error=RuntimeError("stripe down")):
        mock_stripe = MagicMock()
        mock_stripe.Refund.list.side_effect = error
        with patch.object(tw.config, "voucher_grant_enabled", True), \
            patch.object(tw.config, "stripe_secret_key", "sk_test_dummy"), \
            patch.object(tw.config, "stripe_refund_lookback_hours", 24), \
            patch.object(tw, "stripe", mock_stripe), \
            patch.object(tw, "_alert") as alert, \
            patch.object(tw, "enqueue_revoke_by_order_ids") as enqueue:
            raised = False
            try:
                tw.handle()
            except RuntimeError:
                raised = True
        return raised, alert, enqueue

    def setup_method(self):
        tw._consecutive_failures = 0

    def teardown_method(self):
        tw._consecutive_failures = 0

    def test_failure_propagates_and_skips_enqueue(self):
        raised, alert, enqueue = self._fail_once()
        # 다음 tick 이 같은 창을 되짚으므로 삼키지 않고 올린다.
        assert raised is True
        enqueue.assert_not_called()
        # 1회 실패로는 경보하지 않는다(일시 오류로 슬랙을 때리지 않게).
        alert.assert_not_called()

    def test_alerts_after_consecutive_failures(self):
        for _ in range(tw.ALERT_FAILURES - 1):
            _, alert, _ = self._fail_once()
            alert.assert_not_called()
        _, alert, _ = self._fail_once()
        alert.assert_called_once()
        assert "환불 회수 신호가 끊긴" in alert.call_args.args[0]

    def test_success_resets_failure_counter(self):
        self._fail_once()
        assert tw._consecutive_failures == 1
        mock_stripe = _stripe_returning([])
        with patch.object(tw.config, "voucher_grant_enabled", True), \
            patch.object(tw.config, "stripe_secret_key", "sk_test_dummy"), \
            patch.object(tw.config, "stripe_refund_lookback_hours", 24), \
            patch.object(tw, "stripe", mock_stripe), \
            patch.object(tw, "enqueue_revoke_by_order_ids", return_value=0):
            tw.handle()
        assert tw._consecutive_failures == 0


class _FakeReceipt:
    def __init__(self, receipt_id, order_id, store):
        self.id = receipt_id
        self.order_id = order_id
        self.store = store


class _FilteringSession:
    """
    order_id/store 필터를 **실제로 평가**하는 최소 세션.

    Receipt 모델이 postgres 전용 타입(JSONB/ENUM)을 써서 SQLite 로 띄울 수 없으므로,
    컴파일된 바인드 파라미터를 읽어 인메모리 목록에 같은 조건을 적용한다.
    (바인드 이름이 바뀌면 KeyError 로 시끄럽게 깨진다 — 조용히 통과하지 않는다.)
    """

    def __init__(self, receipts):
        self.receipts = receipts

    def execute(self, stmt):
        params = stmt.compile().params
        matched = [
            r
            for r in self.receipts
            if r.order_id in params["order_id_1"] and r.store in params["store_1"]
        ]
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: list(matched))
        )


class TestCrossStoreIsolation:
    """
    스토어 필터 일반화가 실제로 격리를 지키는지 — 같은 order_id 를 가진 타 스토어/무료·마일리지
    영수증이 섞여 있어도 신호원 계열만 회수돼야 한다.
    """

    def _receipts(self):
        return [
            _FakeReceipt(1, "pi_shared", Store.WEB),  # 유료 WEB 결제(Stripe pi)
            _FakeReceipt(2, "pi_shared", Store.GOOGLE),  # 같은 문자열의 google 영수증
            _FakeReceipt(3, "FREE-2f1c8a90", Store.WEB),  # 무료 클레임(Stripe 결제 아님)
            _FakeReceipt(4, "MILE-8b3d0e11", Store.WEB),  # 마일리지 교환(Stripe 결제 아님)
            _FakeReceipt(5, "pi_other", Store.WEB_TEST),  # 샌드박스 WEB
        ]

    def _queued_ids(self, order_ids, stores):
        if isinstance(order_ids, str):
            order_ids = [order_ids]
        sess = _FilteringSession(self._receipts())
        with patch.object(vr, "enqueue_revoke_for_receipt", return_value=True) as m:
            vr.enqueue_revoke_by_order_ids_in_session(sess, order_ids, stores=stores)
            return [c.args[1] for c in m.call_args_list]

    def test_web_signal_touches_only_web_receipt(self):
        assert self._queued_ids("pi_shared", vr.WEB_STORES) == [1]

    def test_google_signal_touches_only_google_receipt(self):
        # 구글 경로 회귀 — 일반화 후에도 google 신호는 google 영수증만 건드린다.
        assert self._queued_ids("pi_shared", vr.GOOGLE_STORES) == [2]

    def test_free_and_mileage_receipts_are_not_touched(self):
        """
        무료 클레임(FREE-<uuid>)·마일리지 교환(MILE-<uuid>) 영수증은 Stripe 결제가 아니다.
        Stripe 가 돌려주는 payment_intent 는 항상 `pi_…` 이므로 접두어가 구조적으로 겹칠 수 없고,
        같은 WEB 스토어에 섞여 있어도 pi_ 조회에 걸려 나오지 않아야 한다(별도 접두어 필터 불필요).
        """
        free_ids = {3, 4}
        for order_id in ("pi_shared", "pi_other", "pi_absent"):
            for stores in (vr.WEB_STORES, vr.GOOGLE_STORES):
                assert not (set(self._queued_ids(order_id, stores)) & free_ids)
        # 그 접두어들을 통째로 넘겨도(있을 수 없는 입력) WEB 계열에서 실제 매칭돼 회수되지만,
        #   Stripe 는 그런 order_id 를 만들지 않는다 — 즉 방어선은 "pi_ 로만 조회된다"는 사실 자체다.
        #   여기서는 무료/마일리지 영수증이 **pi_ 조회로는 절대 안 잡힌다**는 것만 고정한다.
        assert set(self._queued_ids(["pi_shared", "pi_other"], vr.WEB_STORES)) == {1, 5}

    def test_sandbox_web_receipt_matched_by_web_stores(self):
        # dev/staging 에서 sk_test_ 키를 넣으면 WEB_TEST 영수증이 그대로 회수된다(env 하나로 커버).
        assert self._queued_ids("pi_other", vr.WEB_STORES) == [5]
