import base64
from typing import Optional

from pydantic import AmqpDsn, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from shared.enums import PlanetID


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

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="WORKER_")


config = Settings()
