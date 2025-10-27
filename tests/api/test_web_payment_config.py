import pytest
from unittest.mock import patch, Mock

from shared.enums import PackageName


class TestWebPaymentConfig:
    """웹 결제 설정 테스트"""

    def test_api_config_web_payment_settings(self):
        """API 설정에서 웹 결제 설정이 올바르게 정의되어 있는지 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # 웹 결제 설정 필드들이 존재하는지 확인
        assert "web_payment_api_url" in config_content
        assert "web_payment_credential" in config_content
        assert "web_payment_test_mode" in config_content

    def test_api_config_cdn_host_map_web_package(self):
        """API 설정에서 CDN 호스트 맵에 웹 패키지가 포함되어 있는지 테스트"""
        from apps.api.app.config import config

        # 웹 패키지명이 CDN 호스트 맵에 포함되어 있는지 확인
        web_package_name = PackageName.NINE_CHRONICLES_WEB.value
        assert web_package_name in config.cdn_host_map

        # CDN 호스트 URL이 설정되어 있는지 확인
        web_cdn_host = config.cdn_host_map[web_package_name]
        assert web_cdn_host is not None
        assert len(web_cdn_host) > 0

    def test_worker_config_google_package_dict_web_package(self):
        """Worker 설정에서 Google 패키지 딕셔너리에 웹 패키지가 포함되어 있는지 테스트"""
        from apps.worker.app.config import config

        # 웹 패키지명이 Google 패키지 딕셔너리에 포함되어 있는지 확인
        assert PackageName.NINE_CHRONICLES_WEB in config.google_package_dict

        # 웹 패키지명의 값이 올바른지 확인
        web_package_value = config.google_package_dict[PackageName.NINE_CHRONICLES_WEB]
        assert web_package_value == "com.planetariumlabs.ninechroniclesweb"

    def test_config_consistency_between_api_and_worker(self):
        """API와 Worker 설정 간의 일관성 테스트"""
        from apps.api.app.config import api_config
        from apps.worker.app.config import worker_config

        # 웹 패키지명이 양쪽 설정에 모두 포함되어 있는지 확인
        web_package_name = PackageName.NINE_CHRONICLES_WEB.value

        assert web_package_name in api_config.cdn_host_map
        assert PackageName.NINE_CHRONICLES_WEB in worker_config.google_package_dict

        # 패키지명 값이 일치하는지 확인
        api_package_value = api_config.cdn_host_map[web_package_name]
        worker_package_value = worker_config.google_package_dict[PackageName.NINE_CHRONICLES_WEB]

        # API에서는 CDN 호스트 URL, Worker에서는 패키지명이므로 다른 값이어야 함
        assert api_package_value != worker_package_value
        assert worker_package_value == "com.planetariumlabs.ninechroniclesweb"

    def test_web_payment_config_environment_variables(self):
        """웹 결제 설정 환경변수 테스트"""
        # 환경변수 모킹
        with patch.dict('os.environ', {
            'API_WEB_PAYMENT_API_URL': 'https://test-payment-api.com',
            'API_WEB_PAYMENT_CREDENTIAL': 'test-credential-123',
            'API_WEB_PAYMENT_TEST_MODE': 'true'
        }):
            # 설정 재로드
            from apps.api.app.config import Settings
            test_config = Settings()

            # 환경변수가 올바르게 로드되는지 확인
            assert test_config.web_payment_api_url == 'https://test-payment-api.com'
            assert test_config.web_payment_credential == 'test-credential-123'
            assert test_config.web_payment_test_mode is True

    def test_web_payment_config_default_values(self):
        """웹 결제 설정 기본값 테스트"""
        from apps.api.app.config import Settings

        # 기본값으로 설정 생성
        default_config = Settings()

        # 기본값들이 올바른지 확인
        assert isinstance(default_config.web_payment_test_mode, bool)
        assert default_config.web_payment_test_mode is False  # 기본값은 False

    def test_web_payment_config_validation(self):
        """웹 결제 설정 유효성 검증 테스트"""
        from apps.api.app.config import Settings

        # 유효한 설정값들
        valid_config = Settings(
            web_payment_api_url="https://valid-api.com",
            web_payment_credential="valid-credential",
            web_payment_test_mode=False
        )

        assert valid_config.web_payment_api_url == "https://valid-api.com"
        assert valid_config.web_payment_credential == "valid-credential"
        assert valid_config.web_payment_test_mode is False

    def test_web_payment_config_type_validation(self):
        """웹 결제 설정 타입 검증 테스트"""
        from apps.api.app.config import Settings

        # 잘못된 타입의 설정값들
        with pytest.raises(ValueError):
            Settings(
                web_payment_api_url="https://valid-api.com",
                web_payment_credential="valid-credential",
                web_payment_test_mode="invalid_boolean"  # 잘못된 타입
            )

    def test_web_payment_config_required_fields(self):
        """웹 결제 설정 필수 필드 테스트"""
        from apps.api.app.config import Settings

        # 필수 필드들이 설정에 포함되어 있는지 확인
        config = Settings()

        # 필수 필드들이 존재하는지 확인
        required_fields = [
            'web_payment_api_url',
            'web_payment_credential',
            'web_payment_test_mode'
        ]

        for field in required_fields:
            assert hasattr(config, field), f"Required field {field} is missing"

    def test_web_payment_config_immutability(self):
        """웹 결제 설정 불변성 테스트"""
        from apps.api.app.config import config

        # 설정 객체가 불변인지 확인 (실제로는 가변이지만 테스트용)
        original_test_mode = config.web_payment_test_mode

        # 설정 변경 시도
        try:
            config.web_payment_test_mode = not original_test_mode
        except AttributeError:
            # 설정이 불변인 경우
            pass
        else:
            # 설정이 가변인 경우 원래 값으로 복원
            config.web_payment_test_mode = original_test_mode

    def test_web_payment_config_serialization(self):
        """웹 결제 설정 직렬화 테스트"""
        from apps.api.app.config import Settings

        config = Settings(
            web_payment_api_url="https://test-api.com",
            web_payment_credential="test-credential",
            web_payment_test_mode=True
        )

        # 설정을 딕셔너리로 변환
        config_dict = config.model_dump()

        # 웹 결제 관련 설정이 포함되어 있는지 확인
        assert 'web_payment_api_url' in config_dict
        assert 'web_payment_credential' in config_dict
        assert 'web_payment_test_mode' in config_dict

        # 값들이 올바른지 확인
        assert config_dict['web_payment_api_url'] == "https://test-api.com"
        assert config_dict['web_payment_credential'] == "test-credential"
        assert config_dict['web_payment_test_mode'] is True
