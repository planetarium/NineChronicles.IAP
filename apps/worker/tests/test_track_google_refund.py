from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.config import config
from app.tasks.track_google_refund import (
    RefundData,
    VoidReason,
    VoidSource,
    handle,
    send_slack_alert,
)


class TestVoidReason:
    def test_void_reason_values(self):
        assert VoidReason.Other == 0
        assert VoidReason.Remorse == 1
        assert VoidReason.Not_received == 2
        assert VoidReason.Defective == 3
        assert VoidReason.Accidental_purchase == 4
        assert VoidReason.Fraud == 5
        assert VoidReason.Friendly_fraud == 6
        assert VoidReason.Chargeback == 7
        assert VoidReason.what == 8


class TestVoidSource:
    def test_void_source_values(self):
        assert VoidSource.User == 0
        assert VoidSource.Developer == 1
        assert VoidSource.Google == 2


class TestRefundData:
    def test_refund_data_creation(self):
        data = RefundData(
            orderId="test_order_123",
            purchaseTimeMillis="1640995200000",
            voidedTimeMillis="1640998800000",
            voidedSource=0,
            voidedReason=1,
            purchaseToken="test_token",
            kind="androidpublisher#voidedPurchase",
        )

        assert data.orderId == "test_order_123"
        assert data.purchaseToken == "test_token"
        assert data.voidedSource == VoidSource.User
        assert data.voidedReason == VoidReason.Remorse
        assert isinstance(data.purchaseTime, datetime)
        assert isinstance(data.voidedTime, datetime)

    def test_refund_data_timestamps(self):
        data = RefundData(
            orderId="test_order_123",
            purchaseTimeMillis="1640995200000",
            voidedTimeMillis="1640998800000",
            voidedSource=0,
            voidedReason=1,
            purchaseToken="test_token",
            kind="androidpublisher#voidedPurchase",
        )

        expected_purchase_time = datetime.fromtimestamp(1640995200, tz=timezone.utc)
        expected_voided_time = datetime.fromtimestamp(1640998800, tz=timezone.utc)

        assert data.purchaseTime == expected_purchase_time
        assert data.voidedTime == expected_voided_time


class TestSendSlackAlert:
    @patch("app.tasks.track_google_refund.config")
    @patch("app.tasks.track_google_refund.requests.post")
    def test_send_slack_alert_success(self, mock_post, mock_config):
        mock_config.iap_alert_webhook_url = "https://hooks.slack.com/test"
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        send_slack_alert("테스트 메시지")

        mock_post.assert_called_once_with(
            "https://hooks.slack.com/test", json={"text": "테스트 메시지"}, timeout=10
        )

    @patch("app.tasks.track_google_refund.config")
    def test_send_slack_alert_no_webhook_url(self, mock_config):
        mock_config.iap_alert_webhook_url = None

        with patch("app.tasks.track_google_refund.logger") as mock_logger:
            send_slack_alert("테스트 메시지")
            mock_logger.warning.assert_called_once_with(
                "iap_alert_webhook_url이 설정되지 않았습니다."
            )

    @patch("app.tasks.track_google_refund.config")
    @patch("app.tasks.track_google_refund.requests.post")
    def test_send_slack_alert_failure(self, mock_post, mock_config):
        mock_config.iap_alert_webhook_url = "https://hooks.slack.com/test"
        mock_post.side_effect = Exception("Network error")

        with patch("app.tasks.track_google_refund.logger") as mock_logger:
            send_slack_alert("테스트 메시지")
            mock_logger.error.assert_called_once_with(
                "Slack 알림 전송 실패: Network error"
            )


class TestHandle:
    @patch("app.tasks.track_google_refund.get_google_client")
    @patch("app.tasks.track_google_refund.config")
    @patch("app.tasks.track_google_refund.send_slack_alert")
    @patch("app.tasks.track_google_refund.datetime")
    def test_handle_with_refunds(
        self, mock_datetime, mock_send_alert, mock_config, mock_get_client
    ):
        mock_config.google_package_dict = {
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile",
            "NINE_CHRONICLES_WEB": "com.planetariumlabs.ninechroniclesweb"
        }

        current_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = current_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        mock_client = Mock()
        mock_voided_list = {
            "voidedPurchases": [
                {
                    "orderId": "order_123",
                    "purchaseTimeMillis": "1640995200000",
                    "voidedTimeMillis": str(int(current_time.timestamp() * 1000)),
                    "voidedSource": 0,
                    "voidedReason": 1,
                    "purchaseToken": "token_123",
                    "kind": "androidpublisher#voidedPurchase",
                }
            ]
        }

        mock_client.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.return_value = mock_voided_list
        mock_get_client.return_value = mock_client

        with patch("app.tasks.track_google_refund.logger") as mock_logger:
            handle(None, None)

            mock_send_alert.assert_called_once()
            mock_logger.info.assert_called()

    @patch("app.tasks.track_google_refund.get_google_client")
    @patch("app.tasks.track_google_refund.config")
    @patch("app.tasks.track_google_refund.datetime")
    def test_handle_no_refunds(self, mock_datetime, mock_config, mock_get_client):
        mock_config.google_package_dict = {
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile",
            "NINE_CHRONICLES_WEB": "com.planetariumlabs.ninechroniclesweb"
        }

        current_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = current_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        mock_client = Mock()
        mock_voided_list = {"voidedPurchases": []}

        mock_client.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.return_value = mock_voided_list
        mock_get_client.return_value = mock_client

        with patch("app.tasks.track_google_refund.logger") as mock_logger:
            handle(None, None)

            mock_logger.info.assert_called_with(
                "NINE_CHRONICLES_M 패키지에서 최근 1시간 내 환불 건이 없습니다."
            )

    @patch("app.tasks.track_google_refund.get_google_client")
    @patch("app.tasks.track_google_refund.config")
    @patch("app.tasks.track_google_refund.datetime")
    def test_handle_api_parameters(self, mock_datetime, mock_config, mock_get_client):
        mock_config.google_package_dict = {
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile",
            "NINE_CHRONICLES_WEB": "com.planetariumlabs.ninechroniclesweb"
        }

        current_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = current_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        mock_client = Mock()
        mock_voided_list = {"voidedPurchases": []}

        mock_list_method = Mock()
        mock_list_method.execute.return_value = mock_voided_list
        mock_voidedpurchases = Mock()
        mock_voidedpurchases.list.return_value = mock_list_method
        mock_purchases = Mock()
        mock_purchases.voidedpurchases.return_value = mock_voidedpurchases
        mock_client.purchases.return_value = mock_purchases
        mock_get_client.return_value = mock_client

        handle(None, None)

        expected_start_time = str(
            int((current_time - timedelta(hours=1)).timestamp() * 1000)
        )
        expected_end_time = str(int(current_time.timestamp() * 1000))

        mock_voidedpurchases.list.assert_called_once_with(
            packageName="com.planetariumlabs.ninechroniclesmobile",
            startTime=expected_start_time,
            endTime=expected_end_time,
        )


class TestGoogleRevokeHandoff:
    """
    (PLD-1470) google 트래커 → 바우처 회수 핸드오프 스모크.

    왜 필요한가: 위 TestHandle 의 기존 실패 4건은 `package_name.value`(config 미패치)에서 먼저 죽어
    회수 큐잉 줄까지 도달하지 않는다. 그래서 `stores=` 인자가 누락돼도 track_google_refund 의
    `except Exception` 이 warning 으로 삼켜 **구글 회수가 조용히 멈추는** 모양이 된다 —
    그 한 줄을 실제로 통과시켜 고정한다.

    ⚠️ 이 클래스는 위 4건의 선행 실패를 건드리지 않는다(별건, 범위 밖).
       패치를 문자열이 아니라 모듈 객체로 하는 이유는 app/tasks/__init__.py 가 같은 이름의 태스크를
       패키지 속성으로 덮어써서 문자열 타깃이 모듈이 아닌 celery 프록시에 붙기 때문이다.
    """

    def _run_with_one_void(self):
        import importlib

        tg = importlib.import_module("app.tasks.track_google_refund")
        vr = importlib.import_module("app.tasks.voucher_reconcile_task")

        void = {
            "orderId": "GPA.1234-5678-9012-34567",
            "purchaseTimeMillis": "1640995200000",
            "voidedTimeMillis": "1641081600000",
            "voidedSource": 0,
            "voidedReason": 1,
            "purchaseToken": "token_123",
            "kind": "androidpublisher#voidedPurchase",
        }
        client = Mock()
        client.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.return_value = {
            "voidedPurchases": [void]
        }
        # google_package_dict 은 실 config 값(PackageName enum 키)을 그대로 쓴다 — .value 접근이 살아야 한다.
        with patch.object(tg, "get_google_client", return_value=client), \
            patch.object(tg, "send_slack_alert"), \
            patch.object(tg, "enqueue_revoke_by_order_ids", return_value=1) as enqueue:
            tg.handle(None, None)
        return enqueue, vr, void["orderId"]

    def test_passes_google_stores_and_order_ids(self):
        enqueue, vr, order_id = self._run_with_one_void()
        assert enqueue.call_count == 1
        # 패키지 3개를 돌지만 order_id 는 패키지마다 같은 목록에 누적된 뒤 한 번에 넘어간다.
        assert enqueue.call_args.args[0].count(order_id) >= 1
        # 🔴 스토어 화이트리스트 누락은 except Exception 에 삼켜져 조용히 회수가 멈춘다 → 여기서 고정.
        assert enqueue.call_args.kwargs["stores"] == vr.GOOGLE_STORES
