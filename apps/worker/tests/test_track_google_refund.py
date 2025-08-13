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
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile"
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
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile"
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
            "NINE_CHRONICLES_M": "com.planetariumlabs.ninechroniclesmobile"
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
