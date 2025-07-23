import pytest
from datetime import datetime, timezone
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

        # 결과 확인 (product가 None이므로 필터링되지 않고 그대로 반환되어야 함)
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
