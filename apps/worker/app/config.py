import base64
from typing import Optional

from pydantic import AmqpDsn, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from shared.enums import PackageName, PlanetID


class Settings(BaseSettings):
    pg_dsn: str = "postgresql://local_test:password@127.0.0.1:5432/iap"
    broker_url: str = "pyamqp://local_test:password@127.0.0.1:5672/"
    result_backend: str = "redis://127.0.0.1:6379/0"

    gql_url_map: dict[str, str] = {
        "0x100000000000": "https://odin-internal-rpc.nine-chronicles.com/graphql",
        "0x100000000001": "https://heimdall-internal-rpc.nine-chronicles.com/graphql",
    }
    headless_jwt_secret: Optional[str] = None

    region_name: str = "us-east-2"
    kms_key_id: str

    stage: str = "development"

    iap_garage_webhook_url: Optional[str] = None
    iap_alert_webhook_url: Optional[str] = None
    iap_sales_webhook_url: Optional[str] = None

    # NCG Voucher 지급 트리거(PLD-1469). 포탈 grant 엔드포인트 + 서버간 JWT(gameBackendApiHandler).
    portal_grant_url: Optional[str] = None  # 예: https://.../api/voucher/grant
    portal_revoke_url: Optional[str] = None  # 환불 회수용(PLD-1470)
    portal_iap_jwt_secret: Optional[str] = None  # 포탈 JWT_IAP_SECRET_KEY와 동일(HS256)
    voucher_grant_enabled: bool = False  # IAP측 마스터 스위치(포탈 policy.enabled와 별개)
    voucher_grant_cutoff_receipt_id: int = 0  # 이 id 초과 영수증만 바우처 대상(과거 소급 방지)

    google_credential: Optional[str] = None
    google_package_dict: dict[PackageName, str] = {
        PackageName.NINE_CHRONICLES_M: "com.planetariumlabs.ninechroniclesmobile",
        PackageName.NINE_CHRONICLES_K: "com.planetariumlabs.ninechroniclesmobilek",
        PackageName.NINE_CHRONICLES_WEB: "com.planetariumlabs.ninechroniclesweb",
    }

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="WORKER_")


config = Settings()
