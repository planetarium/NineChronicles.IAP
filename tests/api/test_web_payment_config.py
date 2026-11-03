"""Web store configuration — Stripe settings (they replaced the old web_payment_* settings) and the web package wiring."""
import pytest
from pydantic import ValidationError

from shared.enums import PackageName

from apps.api.app.config import Settings as ApiSettings
from apps.api.app.config import config as api_config


class TestStripeSettings:
    def test_stripe_fields_exist_and_old_web_payment_fields_are_gone(self):
        fields = ApiSettings.model_fields
        assert {"stripe_secret_key", "stripe_test_secret_key", "stripe_api_version"} <= set(fields)
        assert not {"web_payment_api_url", "web_payment_credential", "web_payment_test_mode"} & set(fields)

    def test_secret_keys_are_required(self):
        assert ApiSettings.model_fields["stripe_secret_key"].is_required()
        assert ApiSettings.model_fields["stripe_test_secret_key"].is_required()

    def test_api_version_is_pinned(self):
        # Stripe API version is pinned so a Stripe-side default change can't alter responses
        assert ApiSettings.model_fields["stripe_api_version"].default == "2025-09-30.clover"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("API_STRIPE_SECRET_KEY", "sk_live_x")
        monkeypatch.setenv("API_STRIPE_TEST_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("API_STRIPE_API_VERSION", "2099-01-01.test")
        s = ApiSettings()
        assert (s.stripe_secret_key, s.stripe_test_secret_key, s.stripe_api_version) == ("sk_live_x", "sk_test_x", "2099-01-01.test")

    def test_missing_secret_key_fails(self, monkeypatch):
        monkeypatch.delenv("API_STRIPE_SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            ApiSettings(_env_file=None)


class TestWebPackage:
    def test_api_cdn_host_map_has_web_package(self):
        host = api_config.cdn_host_map[PackageName.NINE_CHRONICLES_WEB.value]
        assert host

    def test_worker_google_package_dict_has_web_package(self, monkeypatch):
        # the worker config module builds Settings at import time and needs its KMS key id
        monkeypatch.setenv("WORKER_KMS_KEY_ID", "test-key")
        from apps.worker.app.config import Settings as WorkerSettings

        packages = WorkerSettings.model_fields["google_package_dict"].default
        assert packages[PackageName.NINE_CHRONICLES_WEB] == "com.planetariumlabs.ninechroniclesweb"
