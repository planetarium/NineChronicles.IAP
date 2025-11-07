import pytest


class TestWebPaymentConfigSimple:
    """웹 결제 설정 간단 테스트"""

    def test_api_config_web_payment_settings(self):
        """API 설정에서 웹 결제 설정이 올바르게 정의되어 있는지 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # Stripe 설정 필드들이 존재하는지 확인
        assert "stripe_secret_key" in config_content
        assert "stripe_test_secret_key" in config_content
        assert "stripe_api_version" in config_content

    def test_api_config_cdn_host_map_web_package(self):
        """API 설정에서 CDN 호스트 맵에 웹 패키지가 포함되어 있는지 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # 웹 패키지명이 CDN 호스트 맵에 포함되어 있는지 확인
        assert "com.planetariumlabs.ninechroniclesweb" in config_content

    def test_worker_config_google_package_dict_web_package(self):
        """Worker 설정에서 Google 패키지 딕셔너리에 웹 패키지가 포함되어 있는지 테스트"""
        # 설정 파일을 직접 읽어서 테스트
        config_path = "/Users/yang/projects/iap/apps/worker/app/config.py"
        with open(config_path, 'r') as f:
            config_content = f.read()

        # 웹 패키지명이 Google 패키지 딕셔너리에 포함되어 있는지 확인
        assert "NINE_CHRONICLES_WEB" in config_content
        assert "com.planetariumlabs.ninechroniclesweb" in config_content

    def test_config_consistency_between_api_and_worker(self):
        """API와 Worker 설정 간의 일관성 테스트"""
        # API 설정 파일 읽기
        api_config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(api_config_path, 'r') as f:
            api_config_content = f.read()

        # Worker 설정 파일 읽기
        worker_config_path = "/Users/yang/projects/iap/apps/worker/app/config.py"
        with open(worker_config_path, 'r') as f:
            worker_config_content = f.read()

        # 웹 패키지명이 양쪽 설정에 모두 포함되어 있는지 확인
        web_package_name = "com.planetariumlabs.ninechroniclesweb"

        assert web_package_name in api_config_content
        assert web_package_name in worker_config_content

    def test_web_payment_config_required_fields(self):
        """웹 결제 설정 필수 필드 테스트"""
        # API 설정 파일 읽기
        api_config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(api_config_path, 'r') as f:
            api_config_content = f.read()

        # 필수 필드들이 설정에 포함되어 있는지 확인
        required_fields = [
            'stripe_secret_key',
            'stripe_test_secret_key',
            'stripe_api_version'
        ]

        for field in required_fields:
            assert field in api_config_content, f"Required field {field} is missing"

    def test_web_payment_config_default_values(self):
        """웹 결제 설정 기본값 테스트"""
        # API 설정 파일 읽기
        api_config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(api_config_path, 'r') as f:
            api_config_content = f.read()

        # 기본값이 설정되어 있는지 확인
        assert "stripe_api_version: str = \"2025-09-30.clover\"" in api_config_content

    def test_web_payment_config_type_annotations(self):
        """웹 결제 설정 타입 어노테이션 테스트"""
        # API 설정 파일 읽기
        api_config_path = "/Users/yang/projects/iap/apps/api/app/config.py"
        with open(api_config_path, 'r') as f:
            api_config_content = f.read()

        # 타입 어노테이션이 올바르게 설정되어 있는지 확인
        assert "stripe_secret_key: str" in api_config_content
        assert "stripe_test_secret_key: str" in api_config_content
        assert "stripe_api_version: str" in api_config_content
