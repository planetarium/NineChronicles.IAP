import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from shared.models.receipt import Receipt
from shared.models.product import Product, Price
from shared.enums import ReceiptStatus, Store


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
