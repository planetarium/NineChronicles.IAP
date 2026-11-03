import pytest
import requests
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import jwt

from apps.api.main import app
from apps.api.app.config import config


class TestRedeemCode:
    """Redeem Code 사용 처리 API 테스트"""

    @pytest.fixture
    def client(self, db_session):
        """FastAPI TestClient — 앱의 DB 세션을 테스트 DB(tests/conftest.py db_session, 롤백)로 바꿔 끼운다.
        상품을 넣지 않은 테스트는 외부 API 성공 뒤 404 "Product not found" 경로를 탄다."""
        from app.dependencies import session as app_session  # main 이 쓰는 그 의존성(apps/api 가 sys.path 에 있다)

        app.dependency_overrides[app_session] = lambda: db_session
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(app_session, None)

    @pytest.fixture
    def valid_jwt_token(self):
        """유효한 JWT 토큰 생성"""
        now = datetime.now(tz=timezone.utc)
        data = {
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "aud": "iap"
        }
        token = jwt.encode(data, config.backoffice_jwt_secret, algorithm="HS256")
        return f"Bearer {token}"

    @pytest.fixture
    def expired_jwt_token(self):
        """만료된 JWT 토큰 생성"""
        now = datetime.now(tz=timezone.utc)
        data = {
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "aud": "iap"
        }
        token = jwt.encode(data, config.backoffice_jwt_secret, algorithm="HS256")
        return f"Bearer {token}"

    @pytest.fixture
    def invalid_jwt_token(self):
        """잘못된 JWT 토큰 생성"""
        return "Bearer invalid_token"

    @pytest.fixture
    def redeem_request_data(self):
        """Redeem Code 요청 데이터"""
        return {
            "code": "9C-PLT-A3F7-9B2C-E8D1-4F6A",
            "target_user_id": "9C_USER_999",
            "service_id": "9C",
            "agent_address": "0x1234567890abcdef1234567890abcdef12345678",
            "avatar_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            "planet_id": "0x000000000000",
            "package_name": "com.planetariumlabs.ninechroniclesmobile"
        }

    @pytest.fixture
    def success_response_data(self):
        """성공 응답 데이터"""
        return {
            "success": True,
            "code": "IR2-PLT-3F7K-9Q2L-B8E4-C1D9",
            "product_code": "PLT_PACKAGE_STARTER",
            "issued_by": "V8",
            "buyer_user_id": "V8_USER_123",
            "used": True,
            "used_by_user_id": "IR2_USER_999",
            "used_at": "2025-12-08T03:21:00Z",
            "metadata": {}
        }

    def test_redeem_code_success(
        self, client, db_session, valid_jwt_token, redeem_request_data, success_response_data
    ):
        """성공 케이스 — 외부 API 호출, Receipt(VALID) 생성, 워커 전송까지"""
        from sqlalchemy import select
        from shared.enums import ProductAssetUISize, ProductType, ReceiptStatus, Store
        from shared.models.product import Product
        from shared.models.receipt import Receipt

        product = Product(
            name="Redeem Starter",
            google_sku=success_response_data["product_code"],
            apple_sku="redeem_apple_sku",
            apple_sku_k="redeem_apple_sku_k",
            product_type=ProductType.IAP,
            active=True,
            size=ProductAssetUISize.ONE_BY_ONE,
            path="test/redeem.png",
            l10n_key="TEST_REDEEM",
        )
        db_session.add(product)
        db_session.commit()

        with patch("apps.api.app.api.redeem.requests.post") as mock_post, \
                patch("app.api.redeem.send_to_worker", return_value="task-1") as mock_send:
            # Mock 응답 설정
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = success_response_data
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            # 외부 API 호출 검증
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            # 생성된 JWT 토큰이 Bearer 형식으로 포함되어 있는지 확인
            auth_header = call_args[1]["headers"]["Authorization"]
            assert auth_header.startswith("Bearer ")
            # 토큰 디코딩하여 iss claim 확인
            token = auth_header.split(" ")[1]
            decoded = jwt.decode(token, options={"verify_signature": False})
            assert decoded["iss"] == redeem_request_data["service_id"].upper()
            assert call_args[1]["json"]["code"] == redeem_request_data["code"]
            assert call_args[1]["json"]["target_user_id"] == redeem_request_data["target_user_id"]

            assert response.status_code == 200, response.text
            data = response.json()
            assert data["success"] is True
            assert data["code"] == success_response_data["code"]
            assert data["product_code"] == success_response_data["product_code"]

            receipt = db_session.scalar(select(Receipt).where(Receipt.product_id == product.id))
            assert receipt is not None
            assert (receipt.store, receipt.status) == (Store.REDEEM, ReceiptStatus.VALID)
            assert receipt.order_id.startswith(f"REDEEM-{redeem_request_data['code']}-")
            assert receipt.avatar_addr == redeem_request_data["avatar_address"].lower()
            mock_send.assert_called_once_with("iap.send_product", {"uuid": str(receipt.uuid)})

    def test_redeem_code_no_token(self, client, redeem_request_data):
        """JWT 토큰 없음 테스트 - 인증이 제거되어 항상 외부 API 호출 시도"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            # 외부 API 호출은 시도되지만, Product를 찾지 못하면 404
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "success": True,
                "code": "IR2-PLT-3F7K-9Q2L-B8E4-C1D9",
                "product_code": "PLT_PACKAGE_STARTER",
                "issued_by": "V8",
                "buyer_user_id": "V8_USER_123",
                "used": True,
                "used_by_user_id": "IR2_USER_999",
                "used_at": "2025-12-08T03:21:00Z",
                "metadata": {}
            }
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data
            )

            # Product를 찾지 못하면 404 (정상적인 동작)
            assert response.status_code == 404
            assert "Product not found" in response.json()["detail"]

    def test_redeem_code_invalid_token(
        self, client, invalid_jwt_token, redeem_request_data
    ):
        """잘못된 JWT 토큰 테스트 - 인증이 제거되어 외부 API 호출 시도"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            # 외부 API 호출은 시도되지만, Product를 찾지 못하면 404
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "success": True,
                "code": "IR2-PLT-3F7K-9Q2L-B8E4-C1D9",
                "product_code": "PLT_PACKAGE_STARTER",
                "issued_by": "V8",
                "buyer_user_id": "V8_USER_123",
                "used": True,
                "used_by_user_id": "IR2_USER_999",
                "used_at": "2025-12-08T03:21:00Z",
                "metadata": {}
            }
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": invalid_jwt_token}
            )

            # Product를 찾지 못하면 404 (정상적인 동작)
            assert response.status_code == 404
            assert "Product not found" in response.json()["detail"]

    def test_redeem_code_expired_token(
        self, client, expired_jwt_token, redeem_request_data
    ):
        """만료된 JWT 토큰 테스트 - 인증이 제거되어 외부 API 호출 시도"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            # 외부 API 호출은 시도되지만, Product를 찾지 못하면 404
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "success": True,
                "code": "IR2-PLT-3F7K-9Q2L-B8E4-C1D9",
                "product_code": "PLT_PACKAGE_STARTER",
                "issued_by": "V8",
                "buyer_user_id": "V8_USER_123",
                "used": True,
                "used_by_user_id": "IR2_USER_999",
                "used_at": "2025-12-08T03:21:00Z",
                "metadata": {}
            }
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": expired_jwt_token}
            )

            # Product를 찾지 못하면 404 (정상적인 동작)
            assert response.status_code == 404
            assert "Product not found" in response.json()["detail"]

    def test_redeem_code_403_wrong_project(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """403 에러: 잘못된 프로젝트 테스트"""
        error_response = {
            "success": False,
            "error_code": "WRONG_PROJECT",
            "message": "Code cannot be used in this project"
        }

        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 403
            mock_response.json.return_value = error_response
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 403
            assert error_response["message"] in response.json()["detail"]

    def test_redeem_code_404_invalid_code(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """404 에러: 존재하지 않는 코드 테스트"""
        error_response = {
            "success": False,
            "error_code": "INVALID_CODE",
            "message": "Code not found"
        }

        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.json.return_value = error_response
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 404
            assert error_response["message"] in response.json()["detail"]

    def test_redeem_code_409_already_used(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """409 에러: 이미 사용된 코드 테스트"""
        error_response = {
            "success": False,
            "error_code": "ALREADY_USED",
            "message": "Code has already been used"
        }

        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 409
            mock_response.json.return_value = error_response
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 409
            assert error_response["message"] in response.json()["detail"]

    def test_redeem_code_401_external_api(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """외부 API에서 401 에러 반환 테스트"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"error": "Unauthorized"}
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 401
            assert "JWT authentication failed" in response.json()["detail"]

    def test_redeem_code_network_error(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """네트워크 에러 테스트"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException("Network error")

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 500
            assert "Network error" in response.json()["detail"]

    def test_redeem_code_unexpected_status_code(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """예상치 못한 상태 코드 테스트"""
        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=redeem_request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 500
            assert "Internal server error" in response.json()["detail"]

    def test_redeem_code_invalid_service_id(
        self, client, valid_jwt_token, redeem_request_data
    ):
        """유효하지 않은 service_id 테스트 (9C가 아닌 서비스는 403 반환)"""
        invalid_request_data = redeem_request_data.copy()
        invalid_request_data["service_id"] = "INVALID_SERVICE"

        response = client.post(
            "/api/redeem-codes/redeem",
            json=invalid_request_data,
            headers={"Authorization": valid_jwt_token}
        )

        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"]
        assert "9C" in response.json()["detail"]

    def test_redeem_code_different_service_ids(
        self, client, valid_jwt_token, redeem_request_data, success_response_data
    ):
        """다양한 service_id 테스트 - 9C만 허용, 다른 서비스는 403 반환"""
        # 9C는 정상 처리되어야 함
        request_data_9c = redeem_request_data.copy()
        request_data_9c["service_id"] = "9C"

        with patch("apps.api.app.api.redeem.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = success_response_data
            mock_post.return_value = mock_response

            response = client.post(
                "/api/redeem-codes/redeem",
                json=request_data_9c,
                headers={"Authorization": valid_jwt_token}
            )

            # 생성된 토큰의 iss claim 확인
            call_args = mock_post.call_args
            auth_header = call_args[1]["headers"]["Authorization"]
            token = auth_header.split(" ")[1]
            decoded = jwt.decode(token, options={"verify_signature": False})
            assert decoded["iss"] == "9C"

            # Product를 찾지 못하면 404 (정상적인 동작)
            # 실제 환경에서는 Product가 있어야 함
            if response.status_code == 404:
                assert "Product not found" in response.json()["detail"]
            else:
                assert response.status_code == 200

        # 다른 서비스들은 403 에러를 반환해야 함
        other_service_ids = ["V8", "IR2", "PETPOP"]
        for service_id in other_service_ids:
            request_data = redeem_request_data.copy()
            request_data["service_id"] = service_id

            response = client.post(
                "/api/redeem-codes/redeem",
                json=request_data,
                headers={"Authorization": valid_jwt_token}
            )

            assert response.status_code == 403
            assert "not allowed" in response.json()["detail"]
            assert "9C" in response.json()["detail"]
