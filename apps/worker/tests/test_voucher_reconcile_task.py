from unittest.mock import MagicMock, patch

from app.tasks import voucher_reconcile_task as vr
from shared.enums import VoucherGrantStatus


class TestPostRevoke:
    def _resp(self, status, body=None):
        r = MagicMock()
        r.status_code = status
        r.text = "err"
        r.json = MagicMock(return_value=body if body is not None else {})
        return r

    def _run(self, resp):
        with patch.object(vr.config, "portal_revoke_url", "http://portal/api/voucher/revoke"), \
            patch.object(vr.config, "portal_iap_jwt_secret", "secret"), \
            patch.object(vr.requests, "post", return_value=resp):
            return vr._post_revoke("some-uuid")

    def test_success(self):
        ok, ref, transient = self._run(
            self._resp(200, {"revoked": 2, "alreadyRevoked": 0, "skippedOpened": []})
        )
        assert ok is True and transient is False and "revoked=2" in ref

    def test_skipped_opened_surfaced_in_ref(self):
        ok, ref, transient = self._run(
            self._resp(200, {"revoked": 1, "alreadyRevoked": 0, "skippedOpened": [7]})
        )
        assert ok is True and "skippedOpened=[7]" in ref

    def test_5xx_transient(self):
        ok, ref, transient = self._run(self._resp(503))
        assert ok is False and transient is True

    def test_auth_ratelimit_transient(self):
        for status in (401, 403, 408, 429):
            ok, ref, transient = self._run(self._resp(status))
            assert ok is False and transient is True

    def test_4xx_non_transient(self):
        ok, ref, transient = self._run(self._resp(400, {}))
        assert ok is False and transient is False

    def test_non_object_body_non_transient(self):
        ok, ref, transient = self._run(self._resp(200, "oops"))
        assert ok is False and transient is False


class TestEnqueueRevokeForReceipt:
    def test_creates_when_absent(self):
        sess = MagicMock()
        sess.scalar.return_value = None
        added = {}
        sess.add.side_effect = lambda ob: added.setdefault("ob", ob)
        assert vr.enqueue_revoke_for_receipt(sess, 42) is True
        assert added["ob"].receipt_id == 42
        assert added["ob"].status == VoucherGrantStatus.REVOKE_PENDING

    def test_transitions_granted_to_revoke_pending(self):
        sess = MagicMock()
        ob = MagicMock()
        ob.status = VoucherGrantStatus.GRANTED
        sess.scalar.return_value = ob
        assert vr.enqueue_revoke_for_receipt(sess, 42) is True
        assert ob.status == VoucherGrantStatus.REVOKE_PENDING
        sess.add.assert_not_called()

    def test_transitions_pending_to_revoke_pending(self):
        sess = MagicMock()
        ob = MagicMock()
        ob.status = VoucherGrantStatus.PENDING
        sess.scalar.return_value = ob
        assert vr.enqueue_revoke_for_receipt(sess, 42) is True
        assert ob.status == VoucherGrantStatus.REVOKE_PENDING

    def test_noop_when_already_revoked(self):
        for st in (VoucherGrantStatus.REVOKED, VoucherGrantStatus.REVOKE_PENDING):
            sess = MagicMock()
            ob = MagicMock()
            ob.status = st
            sess.scalar.return_value = ob
            assert vr.enqueue_revoke_for_receipt(sess, 42) is False
            assert ob.status == st  # 변경 없음


class TestReconcileGating:
    def test_disabled_returns_early(self):
        with patch.object(vr.config, "voucher_grant_enabled", False):
            assert vr.reconcile_vouchers.run() == "voucher grant disabled"

    def test_not_configured_returns_early(self):
        with patch.object(vr.config, "voucher_grant_enabled", True), \
            patch.object(vr.config, "portal_revoke_url", None), \
            patch.object(vr.config, "portal_iap_jwt_secret", None):
            assert vr.reconcile_vouchers.run() == "not configured"


class TestEnqueueByOrderIds:
    def test_noop_when_disabled(self):
        with patch.object(vr.config, "voucher_grant_enabled", False):
            assert vr.enqueue_revoke_by_order_ids(["o1", "o2"]) == 0

    def test_noop_when_empty(self):
        with patch.object(vr.config, "voucher_grant_enabled", True):
            assert vr.enqueue_revoke_by_order_ids([]) == 0
