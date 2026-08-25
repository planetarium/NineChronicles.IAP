import base64
from datetime import datetime
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
    # 이 시각(created_at) 이후 영수증만 바우처 대상(과거 소급 방지). ISO8601 env, 미설정(None)=컷오프 없음.
    voucher_grant_cutoff: Optional[datetime] = None

    # (PLD-1470) WEB(Stripe) 환불 감지용 시크릿(env WORKER_STRIPE_SECRET_KEY).
    #   **Optional 인 이유는 "휴면 배포"** 다 — 메인넷엔 아직 이 env 가 없으므로, 미설정이면 track_web_refund 가
    #   Stripe 를 부르기도 전에 즉시 no-op 한다(이미지만 올라가도 아무 일 안 일어남 = voucher_grant_enabled 와 같은 결).
    #   값은 stage 에 맞춰 넣는다: production=sk_live_…(Store.WEB), dev/staging=sk_test_…(Store.WEB_TEST).
    #   키 하나로 두 스토어를 덮는 이유는 Stripe 의 live/test 가 키로 갈리는 별개 네임스페이스라
    #   "그 키로 보이는 환불"만 조회되기 때문이다(교차 조회가 애초에 불가능).
    stripe_secret_key: Optional[str] = None
    # apps/api 와 같은 값으로 고정 — Stripe 계정 기본 버전이 롤포워드해도 응답 필드가 흔들리지 않게.
    stripe_api_version: str = "2025-09-30.clover"

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
