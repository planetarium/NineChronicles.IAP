import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.models.base import Base
from shared.models.product import Product, Price
from shared.enums import Store, ProductType
from shared.schemas.receipt import ReceiptSchema
from shared.validator.common import get_order_data

# 테스트용 데이터베이스 설정 (PostgreSQL 사용)
SQLALCHEMY_DATABASE_URL = "postgresql://test_user:test_pass@localhost:5432/test_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
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

class TestWebPaymentSimpleDatabase:
    def test_web_payment_product_lookup(self, db_session, test_product):
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

    def test_web_payment_receipt_schema_parsing(self, test_product):
        """웹 결제 영수증 스키마 파싱 테스트"""
        web_payment_receipt_data = {
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
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)

        assert receipt_schema.store == Store.WEB
        assert receipt_schema.agentAddress == "0x1234567890abcdef1234567890abcdef12345678"
        assert receipt_schema.avatarAddress == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert receipt_schema.data["orderId"] == "pi_test123"
        assert receipt_schema.data["productId"] == test_product.id
        assert receipt_schema.planetId == "0x000000000001"

    def test_web_payment_get_order_data(self, test_product):
        """웹 결제에서 get_order_data 함수 테스트"""
        from datetime import datetime, timezone

        web_payment_receipt_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "pi_test123",
                "productId": test_product.id,
                "purchaseTime": 1640995200,
                "amount": 12.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000001"
        }

        receipt_schema = ReceiptSchema(**web_payment_receipt_data)
        order_id, product_id, purchased_at = get_order_data(receipt_schema)

        assert order_id == "pi_test123"
        assert product_id == test_product.id
        assert isinstance(purchased_at, datetime)
        assert purchased_at.tzinfo == timezone.utc

    def test_price_lookup_for_web_store(self, db_session, test_product):
        """웹 스토어에 대한 가격 조회 테스트"""
        from sqlalchemy import select

        # 웹 스토어 가격 조회
        web_price = db_session.scalar(
            select(Price)
            .where(Price.product_id == test_product.id, Price.store == Store.WEB)
        )

        assert web_price is not None
        assert float(web_price.price) == 12.99
        assert web_price.currency == "USD"
        assert web_price.store == Store.WEB

        # 웹 테스트 스토어 가격 조회 (없어야 함)
        web_test_price = db_session.scalar(
            select(Price)
            .where(Price.product_id == test_product.id, Price.store == Store.WEB_TEST)
        )

        assert web_test_price is None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
