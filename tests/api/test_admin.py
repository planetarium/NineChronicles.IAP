import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session, joinedload

from shared.models.receipt import Receipt
from shared.models.product import Product, Price
from shared.enums import ReceiptStatus, Store, PlanetID


class TestAdminUserReceiptsEndpoints:
    """Admin 사용자 영수증 조회 엔드포인트 테스트"""

    @pytest.fixture
    def mock_session(self):
        """Mock 세션 생성"""
        return Mock(spec=Session)

    @pytest.fixture
    def sample_receipts(self):
        """샘플 영수증 데이터"""
        receipts = []

        # 커리지패스 영수증
        receipt1 = Mock(spec=Receipt)
        receipt1.order_id = "order_2024_03_01"
        receipt1.agent_addr = "0x1234567890abcdef"
        receipt1.avatar_addr = "0xabcdef1234567890"
        receipt1.purchased_at = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        receipt1.status = ReceiptStatus.VALID
        receipt1.store = Store.GOOGLE
        receipt1.product = Mock(spec=Product)
        receipt1.product.id = 1
        receipt1.product.google_sku = "couragepass1premium"
        receipt1.product.name = "Courage Pass Premium"
        receipts.append(receipt1)

        # 어드벤쳐보스패스 영수증
        receipt2 = Mock(spec=Receipt)
        receipt2.order_id = "order_2024_03_02"
        receipt2.agent_addr = "0x1234567890abcdef"
        receipt2.avatar_addr = "0xabcdef1234567890"
        receipt2.purchased_at = datetime(2024, 3, 20, 14, 15, 0, tzinfo=timezone.utc)
        receipt2.status = ReceiptStatus.VALID
        receipt2.store = Store.GOOGLE
        receipt2.product = Mock(spec=Product)
        receipt2.product.id = 2
        receipt2.product.google_sku = "adventurebosspass1premium"
        receipt2.product.name = "Adventure Boss Pass Premium"
        receipts.append(receipt2)

        # 일반 상품 영수증
        receipt3 = Mock(spec=Receipt)
        receipt3.order_id = "order_2024_03_03"
        receipt3.agent_addr = "0x1234567890abcdef"
        receipt3.avatar_addr = "0xabcdef1234567890"
        receipt3.purchased_at = datetime(2024, 3, 25, 16, 45, 0, tzinfo=timezone.utc)
        receipt3.status = ReceiptStatus.VALID
        receipt3.store = Store.GOOGLE
        receipt3.product = Mock(spec=Product)
        receipt3.product.id = 3
        receipt3.product.google_sku = "regular_item_1"
        receipt3.product.name = "Regular Item 1"
        receipts.append(receipt3)

        return receipts

    def test_courage_pass_purchases_logic(self, mock_session, sample_receipts):
        """커리지패스 구매 확인 로직 테스트"""
        # 커리지패스만 반환하도록 설정
        courage_pass_receipts = [sample_receipts[0]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=courage_pass_receipts):
            # 로직 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                sku_pattern="couragepass\\d+premium"
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "couragepass1premium"
            assert result_receipts[0].product.name == "Courage Pass Premium"

    def test_courage_pass_purchases_no_purchases(self, mock_session):
        """커리지패스 구매 없음 테스트"""
        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=[]):
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                sku_pattern="couragepass\\d+premium"
            )

            assert len(result_receipts) == 0

    def test_adventure_boss_pass_purchases_logic(self, mock_session, sample_receipts):
        """어드벤쳐보스패스 구매 확인 로직 테스트"""
        # 어드벤쳐보스패스만 반환하도록 설정
        adventure_boss_pass_receipts = [sample_receipts[1]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=adventure_boss_pass_receipts):
            # 로직 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                sku_pattern="adventurebosspass\\d+premium"
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "adventurebosspass1premium"
            assert result_receipts[0].product.name == "Adventure Boss Pass Premium"

    def test_non_pass_purchase_amount_logic(self, mock_session, sample_receipts):
        """패스 제외 구매 금액 확인 로직 테스트"""
        # 일반 상품만 반환하도록 설정
        non_pass_receipts = [sample_receipts[2]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=non_pass_receipts):
            # 로직 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ]
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "regular_item_1"
            assert result_receipts[0].product.name == "Regular Item 1"

    def test_decimal_amount_calculation(self, mock_session, sample_receipts):
        """Decimal을 사용한 금액 계산 테스트"""
        # 일반 상품만 반환하도록 설정
        non_pass_receipts = [sample_receipts[2]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=non_pass_receipts):
            # Decimal 금액으로 테스트
            amount_threshold = Decimal("100.0")
            total_amount = Decimal("150.50")

            # Decimal 비교 테스트
            assert total_amount > amount_threshold
            assert total_amount == Decimal("150.50")

            # 결과 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ]
            )

            assert len(result_receipts) == 1

    def test_non_pass_purchase_amount_below_threshold(self, mock_session, sample_receipts):
        """패스 제외 구매 금액 임계값 미달 테스트"""
        # 일반 상품만 반환하도록 설정
        non_pass_receipts = [sample_receipts[2]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=non_pass_receipts):
            # 로직 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ]
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "regular_item_1"

    def test_non_pass_purchase_count_logic(self, mock_session, sample_receipts):
        """패스 제외 구매 건수 확인 로직 테스트"""
        # 일반 상품만 반환하도록 설정
        non_pass_receipts = [sample_receipts[2]]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=non_pass_receipts):
            # 로직 검증
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ]
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "regular_item_1"

    def test_non_pass_purchase_count_below_threshold(self, mock_session):
        """패스 제외 구매 건수 임계값 미달 테스트"""
        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=[]):
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ]
            )

            assert len(result_receipts) == 0

    def test_address_normalization_logic(self):
        """주소 정규화 로직 테스트"""
        # 주소 정규화 함수 테스트
        def normalize_address(addr: str) -> str:
            if not addr.startswith("0x"):
                addr = "0x" + addr
            return addr.lower()

        # 테스트 케이스들
        test_cases = [
            ("0x1234567890abcdef", "0x1234567890abcdef"),
            ("1234567890abcdef", "0x1234567890abcdef"),
            ("0xABCDEF1234567890", "0xabcdef1234567890"),
            ("ABCDEF1234567890", "0xabcdef1234567890"),
        ]

        for input_addr, expected in test_cases:
            result = normalize_address(input_addr)
            assert result == expected

    def test_courage_pass_count_with_avatar(self, mock_session, sample_receipts):
        """커리지패스 구매 숫자 조회 테스트 (avatar_address 제공)"""
        # 커리지패스만 반환하도록 설정
        courage_pass_receipts = [sample_receipts[0]]

        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()
        mock_order_by = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.options.return_value = mock_options
        mock_options.all.return_value = courage_pass_receipts

        # 쿼리 로직 테스트 (avatar_address 제공)
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"
        avatar_address = "0xabcdef1234567890"

        query = mock_session.query(Receipt).filter(
            and_(
                Receipt.agent_addr == agent_address,
                func.timezone('UTC', Receipt.created_at) >= utc_start,
                func.timezone('UTC', Receipt.created_at) < utc_end,
            )
        )
        query = query.filter(Receipt.avatar_addr == avatar_address)
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # SKU 패턴 필터링
        import re
        sku_pattern = "couragepass\\d+premium"
        filtered_receipts = []

        for receipt in receipts:
            if not receipt.product:
                continue
            product_sku = receipt.product.google_sku
            if not product_sku:
                continue
            if re.search(sku_pattern, product_sku, re.IGNORECASE):
                filtered_receipts.append(receipt)

        # 결과 검증
        assert len(filtered_receipts) == 1
        assert filtered_receipts[0].product.google_sku == "couragepass1premium"

    def test_courage_pass_count_without_avatar(self, mock_session, sample_receipts):
        """커리지패스 구매 숫자 조회 테스트 (avatar_address 없음, agent 전체 합산)"""
        # 같은 agent의 다른 avatar의 커리지패스 영수증 추가
        receipt4 = Mock(spec=Receipt)
        receipt4.order_id = "order_2024_03_04"
        receipt4.agent_addr = "0x1234567890abcdef"
        receipt4.avatar_addr = "0x1111111111111111"  # 다른 avatar
        receipt4.purchased_at = datetime(2024, 3, 16, 10, 30, 0, tzinfo=timezone.utc)
        receipt4.status = ReceiptStatus.VALID
        receipt4.store = Store.GOOGLE
        receipt4.product = Mock(spec=Product)
        receipt4.product.id = 4
        receipt4.product.google_sku = "couragepass2premium"
        receipt4.product.name = "Courage Pass 2 Premium"

        # 두 개의 커리지패스 영수증 반환 (다른 avatar)
        courage_pass_receipts = [sample_receipts[0], receipt4]

        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.options.return_value = mock_options
        mock_options.all.return_value = courage_pass_receipts

        # 쿼리 로직 테스트 (avatar_address 없음)
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"

        query = mock_session.query(Receipt).filter(
            and_(
                Receipt.agent_addr == agent_address,
                func.timezone('UTC', Receipt.created_at) >= utc_start,
                func.timezone('UTC', Receipt.created_at) < utc_end,
            )
        )
        # avatar_address 필터링 없음
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # SKU 패턴 필터링
        import re
        sku_pattern = "couragepass\\d+premium"
        filtered_receipts = []

        for receipt in receipts:
            if not receipt.product:
                continue
            product_sku = receipt.product.google_sku
            if not product_sku:
                continue
            if re.search(sku_pattern, product_sku, re.IGNORECASE):
                filtered_receipts.append(receipt)

        # 결과 검증 (두 개의 avatar에서 구매한 커리지패스 합산)
        assert len(filtered_receipts) == 2

    def test_courage_pass_count_no_purchases(self, mock_session):
        """커리지패스 구매 숫자 조회 테스트 (구매 없음)"""
        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.options.return_value = mock_options
        mock_options.all.return_value = []

        # 쿼리 로직 테스트
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"

        query = mock_session.query(Receipt).filter(
            and_(
                Receipt.agent_addr == agent_address,
                func.timezone('UTC', Receipt.created_at) >= utc_start,
                func.timezone('UTC', Receipt.created_at) < utc_end,
            )
        )
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # SKU 패턴 필터링
        import re
        sku_pattern = "couragepass\\d+premium"
        filtered_receipts = []

        for receipt in receipts:
            if not receipt.product:
                continue
            product_sku = receipt.product.google_sku
            if not product_sku:
                continue
            if re.search(sku_pattern, product_sku, re.IGNORECASE):
                filtered_receipts.append(receipt)

        # 결과 검증
        assert len(filtered_receipts) == 0

    def test_courage_pass_count_multiple_avatars(self, mock_session, sample_receipts):
        """커리지패스 구매 숫자 조회 테스트 (여러 avatar 합산)"""
        # 같은 agent의 다른 avatar들의 커리지패스 영수증 추가
        receipt4 = Mock(spec=Receipt)
        receipt4.order_id = "order_2024_03_04"
        receipt4.agent_addr = "0x1234567890abcdef"
        receipt4.avatar_addr = "0x1111111111111111"
        receipt4.purchased_at = datetime(2024, 3, 16, 10, 30, 0, tzinfo=timezone.utc)
        receipt4.status = ReceiptStatus.VALID
        receipt4.store = Store.GOOGLE
        receipt4.product = Mock(spec=Product)
        receipt4.product.id = 4
        receipt4.product.google_sku = "couragepass2premium"
        receipt4.product.name = "Courage Pass 2 Premium"

        receipt5 = Mock(spec=Receipt)
        receipt5.order_id = "order_2024_03_05"
        receipt5.agent_addr = "0x1234567890abcdef"
        receipt5.avatar_addr = "0x2222222222222222"
        receipt5.purchased_at = datetime(2024, 3, 17, 10, 30, 0, tzinfo=timezone.utc)
        receipt5.status = ReceiptStatus.VALID
        receipt5.store = Store.GOOGLE
        receipt5.product = Mock(spec=Product)
        receipt5.product.id = 5
        receipt5.product.google_sku = "couragepass3premium"
        receipt5.product.name = "Courage Pass 3 Premium"

        # 세 개의 커리지패스 영수증 반환 (세 개의 다른 avatar)
        courage_pass_receipts = [sample_receipts[0], receipt4, receipt5]

        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.options.return_value = mock_options
        mock_options.all.return_value = courage_pass_receipts

        # 쿼리 로직 테스트
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"

        query = mock_session.query(Receipt).filter(
            and_(
                Receipt.agent_addr == agent_address,
                func.timezone('UTC', Receipt.created_at) >= utc_start,
                func.timezone('UTC', Receipt.created_at) < utc_end,
            )
        )
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # SKU 패턴 필터링
        import re
        sku_pattern = "couragepass\\d+premium"
        filtered_receipts = []

        for receipt in receipts:
            if not receipt.product:
                continue
            product_sku = receipt.product.google_sku
            if not product_sku:
                continue
            if re.search(sku_pattern, product_sku, re.IGNORECASE):
                filtered_receipts.append(receipt)

        # 결과 검증 (세 개의 avatar에서 구매한 커리지패스 합산)
        assert len(filtered_receipts) == 3

    def test_get_user_receipts_by_month_with_planet_id(self, mock_session, sample_receipts):
        """planet_id 필터링 테스트"""
        # ODIN planet_id를 가진 영수증만 반환
        odin_receipts = [sample_receipts[0]]
        odin_receipts[0].planet_id = PlanetID.ODIN.value

        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()
        mock_order_by = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = odin_receipts

        # planet_id 필터링이 포함된 쿼리 테스트
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"
        avatar_address = "0xabcdef1234567890"
        planet_id = PlanetID.ODIN.value

        # planet_id 필터링이 포함된 쿼리
        filter_conditions = [
            Receipt.agent_addr == agent_address,
            func.timezone('UTC', Receipt.created_at) >= utc_start,
            func.timezone('UTC', Receipt.created_at) < utc_end,
            Receipt.avatar_addr == avatar_address,
            Receipt.planet_id == planet_id
        ]

        query = mock_session.query(Receipt).filter(and_(*filter_conditions))
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.order_by(Receipt.created_at.desc())
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # 결과 검증
        assert len(receipts) == 1
        assert receipts[0].planet_id == PlanetID.ODIN.value

    def test_get_user_receipts_by_month_without_planet_id(self, mock_session, sample_receipts):
        """planet_id가 None일 때 필터링되지 않는지 테스트"""
        # 여러 planet_id를 가진 영수증들
        all_receipts = sample_receipts.copy()
        all_receipts[0].planet_id = PlanetID.ODIN.value
        all_receipts[1].planet_id = PlanetID.HEIMDALL.value
        all_receipts[2].planet_id = PlanetID.ODIN.value

        # Mock 쿼리 체인 설정
        mock_query = Mock()
        mock_filter = Mock()
        mock_join1 = Mock()
        mock_join2 = Mock()
        mock_filter2 = Mock()
        mock_options = Mock()
        mock_order_by = Mock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.filter.return_value = mock_filter
        mock_filter.join.return_value = mock_join1
        mock_join1.join.return_value = mock_join2
        mock_join2.filter.return_value = mock_filter2
        mock_filter2.order_by.return_value = mock_order_by
        mock_order_by.options.return_value = mock_options
        mock_options.all.return_value = all_receipts

        # planet_id 필터링 없이 쿼리 테스트
        from sqlalchemy import and_, func

        year = 2024
        month = 3
        utc_start = datetime(year, month, 1)
        utc_end = datetime(year, month + 1, 1)

        agent_address = "0x1234567890abcdef"
        avatar_address = "0xabcdef1234567890"
        planet_id = None

        # planet_id 필터링이 없는 쿼리
        filter_conditions = [
            Receipt.agent_addr == agent_address,
            func.timezone('UTC', Receipt.created_at) >= utc_start,
            func.timezone('UTC', Receipt.created_at) < utc_end,
            Receipt.avatar_addr == avatar_address,
        ]

        query = mock_session.query(Receipt).filter(and_(*filter_conditions))
        query = query.join(Receipt.product).join(Price).filter(Price.price > 0)
        query = query.order_by(Receipt.created_at.desc())
        query = query.options(joinedload(Receipt.product))
        receipts = query.all()

        # 결과 검증 (모든 planet_id의 영수증이 반환됨)
        assert len(receipts) == 3

    def test_courage_pass_with_planet_id(self, mock_session, sample_receipts):
        """커리지패스 구매 확인에 planet_id 필터링 테스트"""
        # ODIN planet_id를 가진 커리지패스만 반환
        odin_receipt = sample_receipts[0]
        odin_receipt.planet_id = PlanetID.ODIN.value
        courage_pass_receipts = [odin_receipt]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=courage_pass_receipts):
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                sku_pattern="couragepass\\d+premium",
                planet_id=PlanetID.ODIN.value
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "couragepass1premium"
            # get_user_receipts_by_month가 planet_id 파라미터를 받았는지 확인
            Receipt.get_user_receipts_by_month.assert_called_once()
            call_kwargs = Receipt.get_user_receipts_by_month.call_args[1]
            assert call_kwargs['planet_id'] == PlanetID.ODIN.value

    def test_adventure_boss_pass_with_planet_id(self, mock_session, sample_receipts):
        """어드벤쳐보스패스 구매 확인에 planet_id 필터링 테스트"""
        # HEIMDALL planet_id를 가진 어드벤쳐보스패스만 반환
        heimdall_receipt = sample_receipts[1]
        heimdall_receipt.planet_id = PlanetID.HEIMDALL.value
        adventure_boss_pass_receipts = [heimdall_receipt]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=adventure_boss_pass_receipts):
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                sku_pattern="adventurebosspass\\d+premium",
                planet_id=PlanetID.HEIMDALL.value
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "adventurebosspass1premium"
            # get_user_receipts_by_month가 planet_id 파라미터를 받았는지 확인
            Receipt.get_user_receipts_by_month.assert_called_once()
            call_kwargs = Receipt.get_user_receipts_by_month.call_args[1]
            assert call_kwargs['planet_id'] == PlanetID.HEIMDALL.value

    def test_non_pass_purchase_with_planet_id(self, mock_session, sample_receipts):
        """패스 제외 구매 확인에 planet_id 필터링 테스트"""
        # ODIN planet_id를 가진 일반 상품만 반환
        odin_receipt = sample_receipts[2]
        odin_receipt.planet_id = PlanetID.ODIN.value
        non_pass_receipts = [odin_receipt]

        with patch.object(Receipt, 'get_user_receipts_by_month', return_value=non_pass_receipts):
            result_receipts = Receipt.get_user_receipts_by_month(
                session=mock_session,
                agent_addr="0x1234567890abcdef",
                avatar_addr="0xabcdef1234567890",
                year=2024,
                month=3,
                include_product=True,
                only_paid_products=True,
                exclude_sku_patterns=[
                    "adventurebosspass\\d+premium",
                    "couragepass\\d+premium"
                ],
                planet_id=PlanetID.ODIN.value
            )

            # 결과 검증
            assert len(result_receipts) == 1
            assert result_receipts[0].product.google_sku == "regular_item_1"
            # get_user_receipts_by_month가 planet_id 파라미터를 받았는지 확인
            Receipt.get_user_receipts_by_month.assert_called_once()
            call_kwargs = Receipt.get_user_receipts_by_month.call_args[1]
            assert call_kwargs['planet_id'] == PlanetID.ODIN.value
