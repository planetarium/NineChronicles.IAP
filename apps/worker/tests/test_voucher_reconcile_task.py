from unittest.mock import MagicMock, patch

from app.tasks import voucher_reconcile_task as vr
from shared.enums import Store, VoucherGrantStatus


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

    def test_transitions_failed_to_revoke_pending(self):
        # 🔴#2: 크래시창에 발급됐는데 FAILED 찍힌 건도 회수 대상 → 전이돼야 함.
        sess = MagicMock()
        ob = MagicMock()
        ob.status = VoucherGrantStatus.FAILED
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


class TestEnqueueByOrderIdsInSession:
    def test_handles_multiple_google_matches(self):
        # order_id가 (store,order_id)로만 유일 → 다중 매치 시 모두 큐잉.
        sess = MagicMock()
        r1, r2 = MagicMock(), MagicMock()
        r1.id, r2.id = 1, 2
        r1.order_id = r2.order_id = "order-x"
        sess.execute.return_value.scalars.return_value.all.return_value = [r1, r2]
        with patch.object(vr, "enqueue_revoke_for_receipt", return_value=True) as m:
            queued = vr.enqueue_revoke_by_order_ids_in_session(
                sess, ["order-x"], stores=vr.GOOGLE_STORES
            )
            assert queued == ["order-x", "order-x"]
            assert m.call_count == 2

    def test_no_match_returns_empty(self):
        sess = MagicMock()
        sess.execute.return_value.scalars.return_value.all.return_value = []
        assert (
            vr.enqueue_revoke_by_order_ids_in_session(
                sess, ["order-x"], stores=vr.GOOGLE_STORES
            )
            == []
        )

    def test_one_failure_does_not_block_others(self):
        sess = MagicMock()
        r1, r2 = MagicMock(), MagicMock()
        r1.id, r2.id = 1, 2
        r1.order_id, r2.order_id = "o1", "o2"
        sess.execute.return_value.scalars.return_value.all.return_value = [r1, r2]
        with patch.object(
            vr, "enqueue_revoke_for_receipt", side_effect=[RuntimeError("boom"), True]
        ):
            assert (
                vr.enqueue_revoke_by_order_ids_in_session(
                    sess, ["o1", "o2"], stores=vr.GOOGLE_STORES
                )
                == ["o2"]
            )

    def test_store_filter_is_bound_from_argument(self):
        # (PLD-1470) 스토어 필터 일반화 회귀 — GOOGLE_STORES/WEB_STORES가 그대로 쿼리에 실려야 한다.
        #   하드코딩을 지운 뒤에도 google 경로가 종전과 동일한 필터를 쓰는지 고정한다.
        for stores in (vr.GOOGLE_STORES, vr.WEB_STORES):
            sess = MagicMock()
            sess.execute.return_value.scalars.return_value.all.return_value = []
            vr.enqueue_revoke_by_order_ids_in_session(
                sess, ["order-x", "order-y"], stores=stores
            )
            stmt = sess.execute.call_args.args[0]
            params = stmt.compile().params
            # order_id 는 IN 한 방 — N번 조회하면 겹침 배수만큼 seq scan 이 곱해진다.
            assert params["order_id_1"] == ["order-x", "order-y"]
            assert params["store_1"] == stores
            assert sess.execute.call_count == 1

    def test_google_and_web_store_lists_are_disjoint(self):
        # 두 신호원이 서로의 영수증을 절대 건드리지 못해야 한다(크로스-스토어 오회수 방지).
        assert set(vr.GOOGLE_STORES).isdisjoint(vr.WEB_STORES)
        assert set(vr.GOOGLE_STORES) == {Store.GOOGLE, Store.GOOGLE_TEST}
        assert set(vr.WEB_STORES) == {Store.WEB, Store.WEB_TEST}


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
            assert (
                vr.enqueue_revoke_by_order_ids(["o1", "o2"], stores=vr.GOOGLE_STORES)
                == 0
            )

    def test_noop_when_empty(self):
        with patch.object(vr.config, "voucher_grant_enabled", True):
            assert vr.enqueue_revoke_by_order_ids([], stores=vr.GOOGLE_STORES) == 0
