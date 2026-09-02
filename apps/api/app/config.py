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

    # ONE Store (원스토어). 셋 다 없으면 검증기가 거절로 끝낸다(fail-closed) — 필수로 두면
    #   시크릿을 아직 안 넣은 배포가 기동조차 못 한다. client_id/secret 은 개발자센터
    #   공통정보 > 라이선스 관리에서 확인하고 환경별로 같은 값이며, 갈리는 건 호스트다:
    #     검증(개발) https://sbpp.onestore.net / 상용 https://iap-apis.onestore.net
    onestore_client_id: Optional[str] = None
    onestore_client_secret: Optional[str] = None
    onestore_host: Optional[str] = None
    # 마켓 구분 코드. 배포국가가 글로벌이면 MKT_GLB, 한국이면 MKT_ONE.
    #   **헤더를 안 보내면 원스토어가 한국 마켓에서 조회해 모든 구매가 NoSuchData 로
    #   보인다**(2026-09-02 실측). 우리 앱은 배포국가가 미국이라 MKT_GLB 가 기본이다.
    #   비밀이 아니므로 코드 기본값을 두고, 필요하면 env 로 덮는다.
    onestore_market_code: str = "MKT_GLB"

    # Stripe configuration (기존 web_payment_* 설정 대체)
    stripe_secret_key: str
    stripe_test_secret_key: str
    stripe_api_version: str = "2025-09-30.clover"

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

    # Redeem API configuration
    redeem_api_base_url: str

    # Redeem API JWT secret for 9C service only
    jwt_secret_9c: str = "jwt-secret-9c"

    # (PLD) 바우처 상품매핑 admin — C1(ticket_type ∈ 정책) 크로스read용 포탈 공개 prize-tables URL.
    portal_prize_tables_url: Optional[str] = None  # 예: https://.../api/voucher/prize-tables
    # C3-lite 상한: 1 grant 최악 지급(count×최대상금 NCG) 상한. None=미강제(런칭게이트서 숫자 주입).
    voucher_grant_max_ncg_per_grant: Optional[int] = None

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="API_")


config = Settings()
