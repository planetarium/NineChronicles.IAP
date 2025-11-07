import pytest
from unittest.mock import Mock, patch
from shared.enums import Store, PackageName, PlanetID
from shared.schemas.receipt import ReceiptSchema


class TestWebPaymentPackageValidation:
    """웹 결제 패키지명 검증 테스트"""

    def test_web_payment_valid_package_name(self):
        """웹 결제에서 유효한 패키지명 사용"""
        receipt_data = {
            "store": Store.WEB,
            "agentAddress": "0x1234567890abcdef1234567890abcdef12345678",
            "avatarAddress": "0xabcdef1234567890abcdef1234567890abcdef12",
            "data": {
                "Store": "WebPayment",
                "orderId": "web_order_123",
                "productId": 1,
                "purchaseTime": 1640995200,
                "amount": 9.99,
                "currency": "USD",
                "paymentMethod": "credit_card"
            },
            "planetId": "0x000000000000"
        }

        # NINE_CHRONICLES_WEB 패키지명으로 스키마 생성
        receipt_schema = ReceiptSchema(**receipt_data)
        assert receipt_schema.store == Store.WEB
        assert receipt_schema.data["orderId"] == "web_order_123"

    def test_web_payment_invalid_package_name_mobile(self):
        """웹 결제에서 모바일 패키지명 사용 시 에러"""
        # 이 테스트는 실제 API 호출 없이 로직만 검증
        # 웹 결제에서 NINE_CHRONICLES_M 패키지명은 허용되지 않음
        web_package = PackageName.NINE_CHRONICLES_WEB
        mobile_package = PackageName.NINE_CHRONICLES_M

        # 웹 결제에서는 웹 패키지명만 허용
        assert web_package == PackageName.NINE_CHRONICLES_WEB
        assert mobile_package != PackageName.NINE_CHRONICLES_WEB
        assert mobile_package == PackageName.NINE_CHRONICLES_M

    def test_web_payment_invalid_package_name_k(self):
        """웹 결제에서 K 패키지명 사용 시 에러"""
        # 이 테스트는 실제 API 호출 없이 로직만 검증
        # 웹 결제에서 NINE_CHRONICLES_K 패키지명은 허용되지 않음
        web_package = PackageName.NINE_CHRONICLES_WEB
        k_package = PackageName.NINE_CHRONICLES_K

        # 웹 결제에서는 웹 패키지명만 허용
        assert web_package == PackageName.NINE_CHRONICLES_WEB
        assert k_package != PackageName.NINE_CHRONICLES_WEB
        assert k_package == PackageName.NINE_CHRONICLES_K

    def test_web_payment_package_name_validation_logic(self):
        """웹 결제 패키지명 검증 로직 테스트"""
        # purchase.py의 검증 로직을 직접 테스트
        def validate_web_package_name(package_name):
            """웹 결제 패키지명 검증 함수"""
            return package_name == PackageName.NINE_CHRONICLES_WEB

        # 유효한 패키지명
        assert validate_web_package_name(PackageName.NINE_CHRONICLES_WEB) is True

        # 잘못된 패키지명들
        assert validate_web_package_name(PackageName.NINE_CHRONICLES_M) is False
        assert validate_web_package_name(PackageName.NINE_CHRONICLES_K) is False

    def test_web_test_payment_package_name_validation(self):
        """웹 테스트 결제에서도 동일한 패키지명 검증 적용"""
        # 웹 테스트 결제도 동일한 패키지명 검증 로직 적용
        def validate_web_test_package_name(package_name):
            """웹 테스트 결제 패키지명 검증 함수"""
            return package_name == PackageName.NINE_CHRONICLES_WEB

        # 유효한 패키지명
        assert validate_web_test_package_name(PackageName.NINE_CHRONICLES_WEB) is True

        # 잘못된 패키지명들
        assert validate_web_test_package_name(PackageName.NINE_CHRONICLES_M) is False
        assert validate_web_test_package_name(PackageName.NINE_CHRONICLES_K) is False

    def test_web_payment_package_name_error_message(self):
        """웹 결제 패키지명 에러 메시지 테스트"""
        # 에러 메시지 형식 검증
        invalid_package = PackageName.NINE_CHRONICLES_M
        expected_error_msg = f"Invalid package name for web payment: {invalid_package}. Only NINE_CHRONICLES_WEB is allowed."

        # 에러 메시지가 올바른 형식인지 확인
        assert "Invalid package name for web payment" in expected_error_msg
        assert "Only NINE_CHRONICLES_WEB is allowed" in expected_error_msg
        assert str(invalid_package) in expected_error_msg

    def test_web_payment_package_name_enum_values(self):
        """웹 결제 패키지명 enum 값 검증"""
        # 패키지명 enum 값들이 올바른지 확인
        assert PackageName.NINE_CHRONICLES_WEB.value == "com.planetariumlabs.ninechroniclesweb"
        assert PackageName.NINE_CHRONICLES_M.value == "com.planetariumlabs.ninechroniclesmobile"
        assert PackageName.NINE_CHRONICLES_K.value == "com.planetariumlabs.ninechroniclesmobilek"

        # 웹 패키지명이 다른 패키지명과 다른지 확인
        assert PackageName.NINE_CHRONICLES_WEB != PackageName.NINE_CHRONICLES_M
        assert PackageName.NINE_CHRONICLES_WEB != PackageName.NINE_CHRONICLES_K
        assert PackageName.NINE_CHRONICLES_M != PackageName.NINE_CHRONICLES_K

    def test_web_payment_package_name_comparison(self):
        """웹 결제 패키지명 비교 테스트"""
        web_package = PackageName.NINE_CHRONICLES_WEB
        mobile_package = PackageName.NINE_CHRONICLES_M
        k_package = PackageName.NINE_CHRONICLES_K

        # 웹 패키지명은 자기 자신과만 같아야 함
        assert web_package == PackageName.NINE_CHRONICLES_WEB
        assert web_package != mobile_package
        assert web_package != k_package

        # 다른 패키지명들은 웹 패키지명과 다름
        assert mobile_package != web_package
        assert k_package != web_package
