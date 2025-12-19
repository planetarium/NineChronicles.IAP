import pytest
from unittest.mock import patch, Mock
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.models.base import Base
from shared.models.product import Product, Price
from shared.models.receipt import Receipt
from shared.enums import Store, PackageName, PlanetID, ReceiptStatus, ProductType
from shared.schemas.receipt import ReceiptSchema
# from app.api.purchase import request_product
# from app.config import Settings

# 테스트용 데이터베이스 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """테스트용 데이터베이스 세션 픽스처"""
    # 테이블 생성
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # 테이블 삭제
        Base.metadata.drop_all(bind=engine)

@pytest.fixture
def test_product(db_session):
    """테스트용 상품 픽스처"""
    # 상품 생성
    product = Product(
        name="Test Web Product",
        google_sku="test_sku_320",
        apple_sku="test_apple_sku",
        apple_sku_k="test_apple_sku_k",
        product_type=ProductType.IAP,
        active=True
    )
    db_session.add(product)
    db_session.flush()  # ID를 얻기 위해 flush

    # 가격 정보 생성
    price = Price(
        product_id=product.id,
        price=12.99,  # 달러
        currency="USD",
        store=Store.WEB,
        regular_price=15.99
    )
    db_session.add(price)
    db_session.commit()

    return product

@pytest.fixture
def web_payment_receipt_data(test_product):
    """웹 결제 영수증 데이터 픽스처"""
    return {
        "store": Store.WEB,
        "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
        "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
        "data": {
            "Store": "WebPayment",
            "orderId": "pi_test123",
            "productId": test_product.id,  # 실제 Product.id 사용
            "purchaseTime": 1640995200,
            "amount": 12.99,
            "currency": "USD",
            "paymentMethod": "credit_card"
        },
        "planetId": PlanetID.ODIN.value.decode("utf-8")
    }

class TestWebPaymentWithDatabase:
    def test_web_payment_product_lookup(self, db_session, test_product, web_payment_receipt_data):
        """웹 결제에서 실제 데이터베이스로 상품 조회 테스트"""
        from sqlalchemy import select

        # 상품 조회 테스트
        product = db_session.scalar(
            select(Product)
            .where(Product.active.is_(True), Product.id == test_product.id)
        )

        assert product is not None
        assert product.name == "Test Web Product"
        assert product.google_sku == "test_sku_320"

        # 가격 정보 조회 테스트
        price = db_session.scalar(
            select(Price)
            .where(Price.product_id == product.id, Price.store == Store.WEB)
        )

        assert price is not None
        assert float(price.price) == 12.99
        assert price.currency == "USD"

    def test_web_payment_receipt_schema_parsing(self, web_payment_receipt_data):
        """웹 결제 영수증 스키마 파싱 테스트"""
        receipt_schema = ReceiptSchema(**web_payment_receipt_data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "pi_test123"
        assert receipt_schema.data["productId"] == web_payment_receipt_data["data"]["productId"]
        assert receipt_schema.planetId == PlanetID.ODIN.value.decode("utf-8")

    def test_web_payment_get_order_data(self, web_payment_receipt_data):
        """웹 결제에서 get_order_data 함수 테스트"""
        from shared.validator.common import get_order_data
        from datetime import datetime, timezone

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)
        order_id, product_id, purchased_at = get_order_data(receipt_schema)

        assert order_id == "pi_test123"
        assert product_id == web_payment_receipt_data["data"]["productId"]
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    @pytest.mark.skip(reason="실제 API 호출이 필요하므로 모킹 필요")
    def test_web_payment_request_product_integration(self, db_session, test_product, web_payment_receipt_data):
        """웹 결제 request_product 통합 테스트 (실제 API 호출)"""
        # 이 테스트는 실제 API 호출이 필요하므로 모킹이 필요합니다
        # Stripe API 호출을 모킹하고 request_product 함수를 테스트할 수 있습니다
        pass

    def test_zero_price_validation(self, db_session):
        """가격이 0원인 경우 검증 로직 테스트"""
        from sqlalchemy import select

        # 가격이 0원인 상품 생성
        product = Product(
            name="Zero Price Product",
            google_sku="zero_price_sku",
            apple_sku="zero_price_apple_sku",
            apple_sku_k="zero_price_apple_sku_k",
            product_type=ProductType.IAP,
            active=True
        )
        db_session.add(product)
        db_session.flush()

        # 가격이 0원인 Price 생성
        price = Price(
            product_id=product.id,
            price=0.0,  # 0원
            currency="USD",
            store=Store.WEB,
            regular_price=0.0
        )
        db_session.add(price)
        db_session.commit()

        # 가격 조회 및 검증 로직 테스트
        price = db_session.scalar(
            select(Price)
            .where(Price.product_id == product.id)
            .limit(1)
        )

        assert price is not None
        expected_amount_cents = int(price.price * 100)

        # 가격이 0원 이하인지 확인
        assert expected_amount_cents <= 0, "가격이 0원 이하여야 함"
        assert expected_amount_cents == 0, "가격이 정확히 0원이어야 함"

    def test_negative_price_validation(self, db_session):
        """가격이 음수인 경우 검증 로직 테스트"""
        from sqlalchemy import select
        from decimal import Decimal

        # 가격이 음수인 상품 생성
        product = Product(
            name="Negative Price Product",
            google_sku="negative_price_sku",
            apple_sku="negative_price_apple_sku",
            apple_sku_k="negative_price_apple_sku_k",
            product_type=ProductType.IAP,
            active=True
        )
        db_session.add(product)
        db_session.flush()

        # 가격이 음수인 Price 생성
        price = Price(
            product_id=product.id,
            price=Decimal("-1.00"),  # 음수 가격
            currency="USD",
            store=Store.WEB,
            regular_price=Decimal("-1.00")
        )
        db_session.add(price)
        db_session.commit()

        # 가격 조회 및 검증 로직 테스트
        price = db_session.scalar(
            select(Price)
            .where(Price.product_id == product.id)
            .limit(1)
        )

        assert price is not None
        expected_amount_cents = int(price.price * 100)

        # 가격이 0원 이하인지 확인
        assert expected_amount_cents <= 0, "가격이 0원 이하여야 함"
        assert expected_amount_cents < 0, "가격이 음수여야 함"

    @patch('app.api.purchase.validate_web')
    @patch('app.api.purchase.send_to_worker')
    def test_request_endpoint_zero_price_rejection(self, mock_send_to_worker, mock_validate_web, db_session):
        """/request 엔드포인트에서 가격이 0원인 경우 거부 테스트"""
        from app.api.purchase import request_product
        from shared.schemas.receipt import ReceiptSchema

        # 가격이 0원인 상품 생성
        product = Product(
            name="Zero Price Product",
            google_sku="zero_price_sku",
            apple_sku="zero_price_apple_sku",
            apple_sku_k="zero_price_apple_sku_k",
            product_type=ProductType.IAP,
            active=True
        )
        db_session.add(product)
        db_session.flush()

        # 가격이 0원인 Price 생성
        price = Price(
            product_id=product.id,
            price=0.0,  # 0원
            currency="USD",
            store=Store.WEB,
            regular_price=0.0
        )
        db_session.add(price)
        db_session.commit()

        # 구매 요청 데이터 생성
        receipt_data = ReceiptSchema(
            store=Store.WEB,
            agentAddress="0x1234567890abcdef1234567890abcdef12345678",
            avatarAddress="0xabcdef1234567890abcdef1234567890abcdef12",
            data={
                "Store": "WebPayment",
                "orderId": "pi_zero_price_test",
                "productId": product.id,
                "purchaseTime": 1640995200,
            },
            planetId=PlanetID.ODIN.value.decode("utf-8")
        )

        # 가격이 0원이므로 ValueError가 발생해야 함
        with pytest.raises(ValueError, match="Price must be greater than 0"):
            request_product(
                receipt_data=receipt_data,
                x_iap_packagename=PackageName.NINE_CHRONICLES_WEB,
                sess=db_session
            )

        # validate_web이 호출되지 않았는지 확인 (가격 검증에서 먼저 실패해야 함)
        mock_validate_web.assert_not_called()

        # Receipt가 INVALID 상태로 저장되었는지 확인
        receipt = db_session.scalar(
            select(Receipt).where(Receipt.order_id == "pi_zero_price_test")
        )
        assert receipt is not None
        assert receipt.status == ReceiptStatus.INVALID

    @patch('app.api.purchase.validate_web')
    @patch('app.api.purchase.send_to_worker')
    def test_request_endpoint_negative_price_rejection(self, mock_send_to_worker, mock_validate_web, db_session):
        """/request 엔드포인트에서 가격이 음수인 경우 거부 테스트"""
        from app.api.purchase import request_product
        from shared.schemas.receipt import ReceiptSchema
        from decimal import Decimal

        # 가격이 음수인 상품 생성
        product = Product(
            name="Negative Price Product",
            google_sku="negative_price_sku",
            apple_sku="negative_price_apple_sku",
            apple_sku_k="negative_price_apple_sku_k",
            product_type=ProductType.IAP,
            active=True
        )
        db_session.add(product)
        db_session.flush()

        # 가격이 음수인 Price 생성
        price = Price(
            product_id=product.id,
            price=Decimal("-1.00"),  # 음수 가격
            currency="USD",
            store=Store.WEB,
            regular_price=Decimal("-1.00")
        )
        db_session.add(price)
        db_session.commit()

        # 구매 요청 데이터 생성
        receipt_data = ReceiptSchema(
            store=Store.WEB,
            agentAddress="0x1234567890abcdef1234567890abcdef12345678",
            avatarAddress="0xabcdef1234567890abcdef1234567890abcdef12",
            data={
                "Store": "WebPayment",
                "orderId": "pi_negative_price_test",
                "productId": product.id,
                "purchaseTime": 1640995200,
            },
            planetId=PlanetID.ODIN.value.decode("utf-8")
        )

        # 가격이 음수이므로 ValueError가 발생해야 함
        with pytest.raises(ValueError, match="Price must be greater than 0"):
            request_product(
                receipt_data=receipt_data,
                x_iap_packagename=PackageName.NINE_CHRONICLES_WEB,
                sess=db_session
            )

        # validate_web이 호출되지 않았는지 확인 (가격 검증에서 먼저 실패해야 함)
        mock_validate_web.assert_not_called()

        # Receipt가 INVALID 상태로 저장되었는지 확인
        receipt = db_session.scalar(
            select(Receipt).where(Receipt.order_id == "pi_negative_price_test")
        )
        assert receipt is not None
        assert receipt.status == ReceiptStatus.INVALID

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
