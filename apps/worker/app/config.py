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
    #
    #   ⚠️ **어느 환경에 어느 키를 넣느냐가 곧 어느 스토어를 덮느냐**다. Stripe 의 live/test 는 키로 갈리는
    #      별개 네임스페이스여서 "그 키로 보이는 환불"만 조회된다(교차 조회가 애초에 불가능).
    #      apps/api 는 stripe_secret_key 와 stripe_test_secret_key 를 **둘 다** 들고 스토어별로 고르지만
    #      (validate.py / purchase.py), 워커는 키가 하나다. 그래서 환경별로 이렇게 배선한다:
    #        - mainnet:       sk_live_…  → Store.WEB 커버. WEB_TEST 는 애초에 발급 대상이 아니다
    #                         (voucher_grant_task._grantable_stores, WORKER_STAGE=mainnet 배선 전제).
    #        - internal/dev:  sk_test_… → Store.WEB_TEST 커버. 이쪽은 TEST 스토어도 발급 대상이라
    #                         test 키를 안 넣으면 샌드박스 환불이 회수되지 않는다.
    #      ⚠️ 이름 함정: `WORKER_STRIPE_SECRET_KEY` 라는 이름은 운영자가 인터널에도 live 키를 복사하도록
    #         유도한다. 인터널엔 **test 키**다. 한 환경에서 live/test 를 동시에 덮어야 하면 test 키 필드를
    #         따로 추가해야 한다(현재 미지원, 별건).
    stripe_secret_key: Optional[str] = None
    # apps/api 와 같은 값으로 고정 — Stripe 계정 기본 버전이 롤포워드해도 응답 필드가 흔들리지 않게.
    stripe_api_version: str = "2025-09-30.clover"
    # 환불 폴링 룩백(시간). config 로 빼둔 이유는 **유실이 실제로 생기는 경로가 "룩백보다 긴 공백"** 이라서다:
    #   휴면→배선 컷오버 갭 / 워커가 룩백보다 오래 다운 / 콜드 스타트에 MAX_REFUNDS 도달.
    #   특히 컷오버 시점엔 홀드가 72h 라 24h 밖에도 미개봉 바우처가 살아 있다 →
    #   env 만 키워(예: 96) **재배포 없이 일회성 광역 스캔**을 돌릴 수 있어야 한다.
    stripe_refund_lookback_hours: int = 24

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
