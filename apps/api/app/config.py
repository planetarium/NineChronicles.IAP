import base64
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from shared.enums import PackageName, PlanetID


class Settings(BaseSettings):
    pg_dsn: str = "postgresql://local_test:password@127.0.0.1:5432/season_pass"
    broker_url: str = "pyamqp://local_test:password@127.0.0.1:5672/"
    result_backend: str = "redis://127.0.0.1:6379/0"

    gql_url_map: dict[str, str] = {
        "0x100000000000": "https://odin-internal-rpc.nine-chronicles.com/graphql",
        "0x100000000001": "https://heimdall-internal-rpc.nine-chronicles.com/graphql",
    }
    cdn_host_map: dict[str, str] = {
        "com.planetariumlabs.ninechroniclesmobile": "http://localhost",
        "com.planetariumlabs.ninechroniclesmobilek": "http://localhost",
        "com.planetariumlabs.ninechroniclesweb": "http://localhost",
    }

    backoffice_jwt_secret: str

    headless_jwt_secret: Optional[str] = None

    season_pass_host: str
    season_pass_jwt_secret: str

    region_name: str = "us-east-2"

    google_credential: str
    apple_credential: str
    apple_bundle_id: str
    apple_key_id: str
    apple_issuer_id: str
    apple_validation_url: str

    # Web payment configuration
    web_payment_api_url: str
    web_payment_credential: str
    web_payment_test_mode: bool = False

    stage: str = "development"
    debug: bool = False
    db_echo: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    timeout_keep_alive: int = 5

    cloudflare_api_key: str
    cloudflare_assets_k_zone_id: str
    cloudflare_assets_zone_id: str
    cloudflare_email: str
    r2_access_key_id: str
    r2_account_id: str
    r2_bucket: str
    r2_secret_access_key: str
    s3_bucket: str
    cloudfront_distribution_1: str
    cloudfront_distribution_2: str
    l10n_file_path: str = "product.csv"

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="API_")


config = Settings()
