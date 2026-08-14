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

    google_credential: Optional[str] = None
    google_package_dict: dict[PackageName, str] = {
        PackageName.NINE_CHRONICLES_M: "com.planetariumlabs.ninechroniclesmobile",
        PackageName.NINE_CHRONICLES_K: "com.planetariumlabs.ninechroniclesmobilek",
        PackageName.NINE_CHRONICLES_WEB: "com.planetariumlabs.ninechroniclesweb",
    }

    # 결제 신호 리컨실(iap.reconcile_purchase_signal)
    # 기본값은 클러스터 내부 주소 + 드라이런이라 인프라 변경 없이 배포된다.
    iap_api_base_url: str = "http://iap-api"
    # 신호가 온 뒤 이만큼 지나도 영수증이 없으면 유실로 본다.
    purchase_signal_grace_minutes: int = 10
    purchase_signal_batch_size: int = 50
    # True면 확인·기록·알림만 하고 결제를 완결시키지 않는다.
    purchase_signal_dry_run: bool = True

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="WORKER_")


config = Settings()
