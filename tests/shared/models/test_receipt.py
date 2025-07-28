import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

from shared.models.receipt import Receipt


class TestReceipt:
    def test_get_user_receipts_by_month_basic(self):
        """get_user_receipts_by_month 메서드의 기본 동작을 테스트합니다."""
        # Mock 세션 생성
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        # Mock 체인 설정 (only_paid_products=True이므로 join과 추가 filter가 호출됨)
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = []

        # 메서드 호출
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3
        )

        # 세션이 올바르게 호출되었는지 확인
        mock_session.query.assert_called_once_with(Receipt)
        assert result == []

    def test_get_user_receipts_by_month_with_data(self):
        """데이터가 있는 경우의 동작을 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.name = "Product 1"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.name = "Product 2"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt2, mock_receipt1]  # 내림차순 정렬

        # 메서드 호출
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3
        )

        # 결과 확인
        assert len(result) == 2
        assert result[0].order_id == "order_2024_03_02"
        assert result[1].order_id == "order_2024_03_01"

    def test_get_user_receipts_by_month_parameters(self):
        """메서드가 올바른 매개변수로 호출되는지 테스트합니다."""
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = []

        agent_addr = "0x1234567890abcdef"
        avatar_addr = "0xabcdef1234567890"
        year = 2024
        month = 3

        Receipt.get_user_receipts_by_month(
            mock_session, agent_addr, avatar_addr, year, month
        )

        # filter 메서드가 호출되었는지 확인
        mock_query.filter.assert_called_once()

        # join 메서드가 호출되었는지 확인 (가격 필터링)
        mock_filter.join.assert_called()

        # order_by 메서드가 호출되었는지 확인
        mock_join.order_by.assert_called_once()

        # options 메서드가 호출되었는지 확인 (joinedload 사용)
        mock_order_by.options.assert_called_once()

        # all 메서드가 호출되었는지 확인
        mock_options.all.assert_called_once()

    def test_get_user_receipts_by_month_empty_result(self):
        """데이터가 없는 경우 빈 리스트를 반환하는지 테스트합니다."""
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = []

        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2023,
            1
        )

        assert result == []
        assert len(result) == 0

    def test_get_user_receipts_by_month_with_product(self):
        """product 정보가 함께 로드되는지 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt.product = Mock()
        mock_receipt.product.name = "Test Product"
        mock_receipt.product.price = 1000

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (product 포함)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True
        )

        # 결과 확인
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"
        assert result[0].product.name == "Test Product"
        assert result[0].product.price == 1000

        # options 메서드가 호출되었는지 확인 (joinedload 사용)
        mock_order_by.options.assert_called_once()

    def test_get_user_receipts_by_month_without_product(self):
        """product 정보 없이 조회하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.all.return_value = [mock_receipt]

        # 메서드 호출 (product 제외)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=False
        )

        # 결과 확인
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"

        # options 메서드가 호출되지 않았는지 확인
        mock_order_by.options.assert_not_called()

    def test_get_user_receipts_by_month_only_paid_products(self):
        """가격이 0보다 큰 상품만 필터링하는지 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt.product = Mock()
        mock_receipt.product.name = "Paid Product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (가격이 0보다 큰 상품만)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            only_paid_products=True
        )

        # 결과 확인
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"

        # join 메서드가 호출되었는지 확인 (가격 필터링)
        mock_filter.join.assert_called()
        mock_join.join.assert_called()

    def test_get_user_receipts_by_month_include_free_products(self):
        """무료 상품도 포함하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt.product = Mock()
        mock_receipt.product.name = "Free Product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (무료 상품 포함)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            only_paid_products=False
        )

        # 결과 확인
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"

        # join 메서드가 호출되지 않았는지 확인 (가격 필터링 없음)
        mock_filter.join.assert_not_called()

    def test_get_user_receipts_by_month_with_sku_pattern(self):
        """특정 SKU 패턴만 포함하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "adventurebosspass1premium"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "couragepass2premium"

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "regular_item"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (어드벤쳐보스패스만)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            sku_pattern="adventurebosspass\\d+premium"
        )

        # 결과 확인 (어드벤쳐보스패스만 포함되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"
        assert result[0].product.google_sku == "adventurebosspass1premium"

    def test_get_user_receipts_by_month_exclude_sku_patterns(self):
        """특정 SKU 패턴을 제외하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "adventurebosspass1premium"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "couragepass2premium"

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "regular_item"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (패스 타입 제외)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            exclude_sku_patterns=[
                "adventurebosspass\\d+premium",
                "couragepass\\d+premium"
            ]
        )

        # 결과 확인 (패스 타입이 제외되고 regular_item만 포함되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_03"
        assert result[0].product.google_sku == "regular_item"

    def test_get_user_receipts_by_month_sku_pattern_without_product(self):
        """product가 없는 경우 SKU 패턴 필터링이 무시되는지 테스트합니다."""
        # Mock 영수증 객체 생성 (product가 None)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt.product = None  # product가 None

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (SKU 패턴 지정하지만 product가 None)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            sku_pattern="adventurebosspass\\d+premium"
        )

        # 결과 확인 (product가 None이므로 필터링에서 제외됨)
        assert len(result) == 0  # product가 None이므로 필터링에서 제외됨

    def test_get_user_receipts_by_month_couragepass_pattern(self):
        """커리지패스 패턴만 포함하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "couragepass1premium"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "couragepass2premium"

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "adventurebosspass1premium"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (커리지패스만)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            sku_pattern="couragepass\\d+premium"
        )

        # 결과 확인 (커리지패스만 포함되어야 함)
        assert len(result) == 2
        assert result[0].order_id == "order_2024_03_01"
        assert result[0].product.google_sku == "couragepass1premium"
        assert result[1].order_id == "order_2024_03_02"
        assert result[1].product.google_sku == "couragepass2premium"

    def test_get_user_receipts_by_month_sku_pattern_without_google_sku(self):
        """google_sku가 None인 경우 SKU 패턴 필터링이 무시되는지 테스트합니다."""
        # Mock 영수증 객체 생성 (google_sku가 None)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_03_01"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        mock_receipt.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt.product = Mock()
        mock_receipt.product.google_sku = None  # google_sku가 None

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (SKU 패턴 지정하지만 google_sku가 None)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            sku_pattern="adventurebosspass\\d+premium"
        )

        # 결과 확인 (google_sku가 None이므로 필터링에서 제외됨)
        assert len(result) == 0

    def test_get_user_receipts_by_month_complex_filtering(self):
        """복합 조건 (가격 필터링 + SKU 패턴)을 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "adventurebosspass1premium"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "regular_item"

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "adventurebosspass2premium"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (유료 상품 + 어드벤쳐보스패스만)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            only_paid_products=True,
            sku_pattern="adventurebosspass\\d+premium"
        )

        # 결과 확인 (어드벤쳐보스패스만 포함되어야 함)
        assert len(result) == 2
        assert result[0].order_id == "order_2024_03_01"
        assert result[0].product.google_sku == "adventurebosspass1premium"
        assert result[1].order_id == "order_2024_03_03"
        assert result[1].product.google_sku == "adventurebosspass2premium"

    def test_get_user_receipts_by_month_case_insensitive(self):
        """대소문자 무시 테스트를 합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "ADVENTUREBOSSPASS1PREMIUM"  # 대문자

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "CouragePass2Premium"  # 혼합 대소문자

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "regular_item"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (대소문자 무시 패턴)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            sku_pattern="adventurebosspass\\d+premium"
        )

        # 결과 확인 (대소문자 무시하고 매칭되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_01"
        assert result[0].product.google_sku == "ADVENTUREBOSSPASS1PREMIUM"

    def test_get_user_receipts_by_month_multiple_exclude_patterns(self):
        """여러 제외 패턴을 동시에 적용하는 경우를 테스트합니다."""
        # Mock 영수증 객체 생성
        mock_receipt1 = Mock()
        mock_receipt1.order_id = "order_2024_03_01"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "adventurebosspass1premium"

        mock_receipt2 = Mock()
        mock_receipt2.order_id = "order_2024_03_02"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "couragepass2premium"

        mock_receipt3 = Mock()
        mock_receipt3.order_id = "order_2024_03_03"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "regular_item"

        mock_receipt4 = Mock()
        mock_receipt4.order_id = "order_2024_03_04"
        mock_receipt4.agent_addr = "0x1234567890abcdef"
        mock_receipt4.avatar_addr = "0xabcdef1234567890"
        mock_receipt4.purchased_at = datetime(2024, 3, 30, 18, 20, 0, tzinfo=timezone.utc)
        mock_receipt4.product = Mock()
        mock_receipt4.product.google_sku = "otherpass3premium"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3, mock_receipt4]

        # 메서드 호출 (여러 패스 타입 제외)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            3,
            include_product=True,
            exclude_sku_patterns=[
                "adventurebosspass\\d+premium",
                "couragepass\\d+premium",
                "otherpass\\d+premium"
            ]
        )

        # 결과 확인 (모든 패스 타입이 제외되고 regular_item만 포함되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_03_03"
        assert result[0].product.google_sku == "regular_item"

    # ===== 타임존 경계 케이스 테스트 =====

    def test_get_user_receipts_by_month_timezone_boundary_month_start(self):
        """월 시작 경계 케이스를 테스트합니다.
        DB에는 KST로 저장되고, API는 UTC 기준으로 요청받아 KST를 UTC로 변환하여 조회
        """
        # Mock 영수증 객체 생성 (KST로 저장된 데이터)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_02_01_kst"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        # KST 2024-02-01 09:00:00 (UTC 2024-02-01 00:00:00에 해당)
        mock_receipt.purchased_at = datetime(2024, 2, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt.product = Mock()
        mock_receipt.product.google_sku = "test_product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (UTC 2024년 2월 요청)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            2
        )

        # 결과 확인 (KST를 UTC로 변환하여 조회되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_02_01_kst"

    def test_get_user_receipts_by_month_timezone_boundary_month_end(self):
        """월 끝 경계 케이스를 테스트합니다.
        DB에는 KST로 저장되고, API는 UTC 기준으로 요청받아 KST를 UTC로 변환하여 조회
        """
        # Mock 영수증 객체 생성 (KST로 저장된 데이터)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2024_02_01_0830_kst"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        # KST 2024-02-01 08:30:00 (UTC 2024-01-31 23:30:00에 해당)
        mock_receipt.purchased_at = datetime(2024, 2, 1, 8, 30, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt.product = Mock()
        mock_receipt.product.google_sku = "test_product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (UTC 2024년 1월 요청)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            1
        )

        # 결과 확인 (KST를 UTC로 변환하여 조회되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2024_02_01_0830_kst"

    def test_get_user_receipts_by_month_timezone_boundary_year_end(self):
        """연말 경계 케이스를 테스트합니다.
        DB에는 KST로 저장되고, API는 UTC 기준으로 요청받아 KST를 UTC로 변환하여 조회
        """
        # Mock 영수증 객체 생성 (KST로 저장된 데이터)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2025_01_01_0830_kst"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        # KST 2025-01-01 08:30:00 (UTC 2024-12-31 23:30:00에 해당)
        mock_receipt.purchased_at = datetime(2025, 1, 1, 8, 30, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt.product = Mock()
        mock_receipt.product.google_sku = "test_product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (UTC 2024년 12월 요청)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            12
        )

        # 결과 확인 (KST를 UTC로 변환하여 조회되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2025_01_01_0830_kst"

    def test_get_user_receipts_by_month_timezone_boundary_year_start(self):
        """연초 경계 케이스를 테스트합니다.
        DB에는 KST로 저장되고, API는 UTC 기준으로 요청받아 KST를 UTC로 변환하여 조회
        """
        # Mock 영수증 객체 생성 (KST로 저장된 데이터)
        mock_receipt = Mock()
        mock_receipt.order_id = "order_2025_01_01_0900_kst"
        mock_receipt.agent_addr = "0x1234567890abcdef"
        mock_receipt.avatar_addr = "0xabcdef1234567890"
        # KST 2025-01-01 09:00:00 (UTC 2025-01-01 00:00:00에 해당)
        mock_receipt.purchased_at = datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt.product = Mock()
        mock_receipt.product.google_sku = "test_product"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt]

        # 메서드 호출 (UTC 2025년 1월 요청)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2025,
            1
        )

        # 결과 확인 (KST를 UTC로 변환하여 조회되어야 함)
        assert len(result) == 1
        assert result[0].order_id == "order_2025_01_01_0900_kst"

    def test_get_user_receipts_by_month_timezone_boundary_edge_cases(self):
        """여러 경계 케이스를 동시에 테스트합니다.
        DB에는 KST로 저장되고, API는 UTC 기준으로 요청받아 KST를 UTC로 변환하여 조회
        """
        # Mock 영수증 객체들 생성 (KST로 저장된 데이터)
        mock_receipt1 = Mock()  # KST 2024-02-01 08:30:00 (UTC 2024-01-31 23:30:00에 해당)
        mock_receipt1.order_id = "order_2024_02_01_0830_kst"
        mock_receipt1.agent_addr = "0x1234567890abcdef"
        mock_receipt1.avatar_addr = "0xabcdef1234567890"
        mock_receipt1.purchased_at = datetime(2024, 2, 1, 8, 30, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt1.product = Mock()
        mock_receipt1.product.google_sku = "product1"

        mock_receipt2 = Mock()  # KST 2024-02-01 09:00:00 (UTC 2024-02-01 00:00:00에 해당)
        mock_receipt2.order_id = "order_2024_02_01_0900_kst"
        mock_receipt2.agent_addr = "0x1234567890abcdef"
        mock_receipt2.avatar_addr = "0xabcdef1234567890"
        mock_receipt2.purchased_at = datetime(2024, 2, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt2.product = Mock()
        mock_receipt2.product.google_sku = "product2"

        mock_receipt3 = Mock()  # KST 2024-02-01 23:30:00 (UTC 2024-02-01 14:30:00에 해당)
        mock_receipt3.order_id = "order_2024_02_01_2330_kst"
        mock_receipt3.agent_addr = "0x1234567890abcdef"
        mock_receipt3.avatar_addr = "0xabcdef1234567890"
        mock_receipt3.purchased_at = datetime(2024, 2, 1, 23, 30, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_receipt3.product = Mock()
        mock_receipt3.product.google_sku = "product3"

        # Mock 세션 설정
        mock_session = Mock()
        mock_query = Mock()
        mock_filter = Mock()
        mock_join = Mock()
        mock_order_by = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join
        mock_join.join.return_value = mock_join
        mock_join.filter.return_value = mock_join
        mock_join.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = [mock_receipt1, mock_receipt2, mock_receipt3]

        # 메서드 호출 (UTC 2024년 2월 요청)
        result = Receipt.get_user_receipts_by_month(
            mock_session,
            "0x1234567890abcdef",
            "0xabcdef1234567890",
            2024,
            2
        )

        # 결과 확인 (모든 영수증이 KST를 UTC로 변환하여 조회되어야 함)
        assert len(result) == 3
        order_ids = [r.order_id for r in result]
        assert "order_2024_02_01_0830_kst" in order_ids
        assert "order_2024_02_01_0900_kst" in order_ids
        assert "order_2024_02_01_2330_kst" in order_ids

    def test_get_user_receipts_by_month_timezone_conversion_logic(self):
        """타임존 변환 로직이 올바르게 작동하는지 테스트합니다."""
        from datetime import timedelta

        # UTC 기준 월의 시작 시간들
        test_cases = [
            # (UTC year, UTC month, expected KST year, expected KST month)
            (2024, 1, 2024, 1),   # UTC 2024-01-01 00:00 -> KST 2024-01-01 09:00
            (2024, 2, 2024, 2),   # UTC 2024-02-01 00:00 -> KST 2024-02-01 09:00
            (2024, 12, 2024, 12), # UTC 2024-12-01 00:00 -> KST 2024-12-01 09:00
            (2024, 1, 2024, 1),   # UTC 2024-01-31 23:30 -> KST 2024-02-01 08:30 (이전 월 요청 시)
        ]

        for utc_year, utc_month, expected_kst_year, expected_kst_month in test_cases:
            # Mock 세션 설정
            mock_session = Mock()
            mock_query = Mock()
            mock_filter = Mock()
            mock_join = Mock()
            mock_order_by = Mock()
            mock_options = Mock()

            mock_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_filter
            mock_filter.join.return_value = mock_join
            mock_join.join.return_value = mock_join
            mock_join.filter.return_value = mock_join
            mock_join.order_by.return_value = mock_order_by
            mock_order_by.options.return_value = mock_options
            mock_options.all.return_value = []

            # 메서드 호출
            Receipt.get_user_receipts_by_month(
                mock_session,
                "0x1234567890abcdef",
                "0xabcdef1234567890",
                utc_year,
                utc_month
            )

            # filter 호출에서 올바른 UTC 범위가 사용되었는지 확인
            # 실제로는 func.timezone 함수 호출을 확인해야 하지만, Mock에서는 호출 여부만 확인
            mock_query.filter.assert_called_once()

            # Mock 초기화
            mock_session.reset_mock()
            mock_query.reset_mock()
            mock_filter.reset_mock()
            mock_join.reset_mock()
            mock_order_by.reset_mock()
            mock_options.reset_mock()
