from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.config import config
from app.tasks.status_monitor import (
    check_monthly_sales,
    create_divider_block,
    daily_sales_report,
)
from shared.enums import ReceiptStatus, Store


class TestCreateDividerBlock:
    def test_create_divider_block(self):
        """Test divider block creation"""
        block = create_divider_block()
        assert block == {"type": "divider"}


class TestCheckMonthlySales:
    @patch("app.tasks.status_monitor.config")
    @patch("app.tasks.status_monitor.send_message")
    @patch("app.tasks.status_monitor.logger")
    def test_check_monthly_sales_no_webhook_url(self, mock_logger, mock_send_message, mock_config):
        """Test that function returns early when webhook URL is not set"""
        mock_config.iap_sales_webhook_url = None
        mock_sess = Mock()

        check_monthly_sales(mock_sess)

        mock_logger.warning.assert_called_once_with("iap_sales_webhook_url이 설정되지 않았습니다.")
        mock_send_message.assert_not_called()

    @patch("app.tasks.status_monitor.config")
    @patch("app.tasks.status_monitor.send_message")
    @patch("app.tasks.status_monitor.datetime")
    def test_check_monthly_sales_with_data(self, mock_datetime, mock_send_message, mock_config):
        """Test check_monthly_sales with sample data"""
        mock_config.iap_sales_webhook_url = "https://hooks.slack.com/test"

        # Mock current time to January 2024
        mock_now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        # Create a side_effect function that returns the real datetime when called with arguments
        def datetime_side_effect(*args, **kwargs):
            if args or kwargs:
                return datetime(*args, **kwargs)
            return mock_now

        mock_datetime.now = Mock(side_effect=lambda tz=None: mock_now)
        mock_datetime.side_effect = datetime_side_effect

        # Mock database session and query
        mock_sess = Mock(spec=Session)

        # Mock query result
        mock_result1 = Mock()
        mock_result1.sale_date = datetime(2024, 1, 1).date()
        mock_result1.store = Store.APPLE
        mock_result1.total_sales = 100.0

        mock_result2 = Mock()
        mock_result2.sale_date = datetime(2024, 1, 1).date()
        mock_result2.store = Store.GOOGLE
        mock_result2.total_sales = 200.0

        mock_result3 = Mock()
        mock_result3.sale_date = datetime(2024, 1, 2).date()
        mock_result3.store = Store.WEB
        mock_result3.total_sales = 150.0

        # Mock query chain
        mock_query = Mock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_result1, mock_result2, mock_result3]

        mock_sess.query.return_value = mock_query

        check_monthly_sales(mock_sess)

        # Verify send_message was called
        assert mock_send_message.called
        call_args = mock_send_message.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        assert "[NineChronicles.IAP] Daily Sales Report :: 1월" in call_args[0][1]

        # Verify blocks structure
        blocks = call_args[0][2]
        assert len(blocks) > 0

        # Check header block
        assert blocks[0]["type"] == "section"
        assert "*날짜* | *총매출* | *APPLE* | *GOOGLE* | *WEB*" in blocks[0]["text"]["text"]

        # Check divider blocks
        divider_count = sum(1 for block in blocks if block.get("type") == "divider")
        assert divider_count >= 2  # At least 2 dividers (before data and before total)

        # Check total block (should be last)
        total_block = blocks[-1]
        assert total_block["type"] == "section"
        assert "*합계*" in total_block["text"]["text"]

    @patch("app.tasks.status_monitor.config")
    @patch("app.tasks.status_monitor.send_message")
    @patch("app.tasks.status_monitor.datetime")
    def test_check_monthly_sales_no_data(self, mock_datetime, mock_send_message, mock_config):
        """Test check_monthly_sales when there is no sales data"""
        mock_config.iap_sales_webhook_url = "https://hooks.slack.com/test"

        mock_now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        def datetime_side_effect(*args, **kwargs):
            if args or kwargs:
                return datetime(*args, **kwargs)
            return mock_now

        mock_datetime.now = Mock(side_effect=lambda tz=None: mock_now)
        mock_datetime.side_effect = datetime_side_effect

        mock_sess = Mock(spec=Session)
        mock_query = Mock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []  # No data

        mock_sess.query.return_value = mock_query

        check_monthly_sales(mock_sess)

        # Should still send message with header and total (even if empty)
        assert mock_send_message.called
        blocks = mock_send_message.call_args[0][2]
        # Should have at least header, divider, total
        assert len(blocks) >= 3


class TestDailySalesReportTask:
    @patch("app.tasks.status_monitor.check_monthly_sales")
    @patch("app.tasks.status_monitor.scoped_session")
    @patch("app.tasks.status_monitor.sessionmaker")
    @patch("app.tasks.status_monitor.engine")
    @patch("app.tasks.status_monitor.logger")
    def test_daily_sales_report_success(
        self, mock_logger, mock_engine, mock_sessionmaker, mock_scoped_session, mock_check_sales
    ):
        """Test daily_sales_report task execution"""
        mock_sess = Mock()
        mock_scoped_session.return_value = mock_sess

        task_instance = Mock()
        daily_sales_report(task_instance)

        mock_check_sales.assert_called_once_with(mock_sess)
        mock_sess.close.assert_called_once()
        mock_logger.debug.assert_called()

    @patch("app.tasks.status_monitor.check_monthly_sales")
    @patch("app.tasks.status_monitor.scoped_session")
    @patch("app.tasks.status_monitor.sessionmaker")
    @patch("app.tasks.status_monitor.engine")
    @patch("app.tasks.status_monitor.logger")
    def test_daily_sales_report_failure(
        self, mock_logger, mock_engine, mock_sessionmaker, mock_scoped_session, mock_check_sales
    ):
        """Test daily_sales_report task handles exceptions"""
        mock_sess = Mock()
        mock_scoped_session.return_value = mock_sess
        mock_check_sales.side_effect = Exception("Database error")

        task_instance = Mock()

        with pytest.raises(Exception):
            daily_sales_report(task_instance)

        mock_check_sales.assert_called_once_with(mock_sess)
        mock_sess.close.assert_called_once()
        mock_logger.error.assert_called_once()
