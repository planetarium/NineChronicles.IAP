import base64
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from shared.enums import PackageName, PlanetID

from app.grant_guard import parse_grant_namespaces


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

    # ── (PLD-1575) 지급 API(POST /api/admin/grant) 머니 가드 ─────────────────
    #   `GrantItems` force-grant 를 여는 엔드포인트라 상한 없이는 사실상 무제한 민터다.
    #   임계는 전부 여기(설정)에만 있다 — 코드에 숫자를 박지 않는다. 상세는 app/grant_guard.py.
    #   ⚠️ prod(stage=production|mainnet)에서는 아래 상한이 **하나라도 None 이면 지급 요청을
    #      503 으로 거절**한다(fail-closed). voucher C3-lite 게이트와 같은 규칙.

    # 허용 external_ref 네임스페이스(쉼표 구분). 호출자 식별 = 이 등록제. `-` 단독은 전체 비활성.
    grant_allowed_namespaces: str = "shop"
    # 지급 허용 FAV 티커(쉼표 구분, 예: `FAV__CRYSTAL`). **빈 값 = FAV 지급 금지**(기본).
    #   수량 상한은 티커를 구분하지 못한다(CRYSTAL 기준 상한이 곧 SOULSTONE 상한이 된다)
    #   → 화폐 종류 자체를 얼로우리스트로 연다. 아이템만 지급하는 동안은 비워 두는 게 맞다.
    grant_allowed_fav_tickers: str = ""
    # 1건 지급의 FAV(NCG·CRYSTAL 등) 총량 상한. 아이템과 따로 센다(단위가 다르다).
    grant_max_fav_units_per_request: Optional[int] = None
    # 1건 지급의 아이템 총 개수 상한.
    grant_max_item_units_per_request: Optional[int] = None
    # 시간창 총량(전 네임스페이스 합) — 시간당 / 일당 지급 건수 상한.
    grant_max_grants_per_hour: Optional[int] = None
    grant_max_grants_per_day: Optional[int] = None
    # 네임스페이스별 레이트리밋 — 분당 지급 건수 상한(버스트 차단).
    #   ⚠️ 시간당/일당 상한이 총노출을 이미 묶으므로 이 값은 **넉넉하게**(실측 버스트의 3~5배)
    #   잡는다. 초과는 400 = 포탈 기준 영구 실패이므로, 촘촘한 분당 상한은 총량을 더 줄이지
    #   못하면서 정상 버스트를 주문 실패로 바꾸는 오탐만 만든다.
    grant_max_grants_per_namespace_per_minute: Optional[int] = None
    # 아바타별 시간창 상한 — 시간당 / 일당. **전역 상한은 총노출, 이건 집중도를 묶는다.**
    #   이게 없으면 한 아바타가 전역 시간창 전량을 태울 수 있다. 이 경로는 "유저가 포인트를
    #   냈는지"를 IAP 가 검증하지 못하고(원장은 포탈) 포탈을 신뢰하는 구조라, 포탈 버그 하나의
    #   blast radius 가 곧 이 값이다.
    #   ⚠️ **미주입(None) = 그 축 미적용**이고 503(limits_unset) 대상이 아니다 — 차트에 값이
    #   배선되기 전에 이미지가 뜨면 포인트샵 전체가 멈추기 때문이다(grant_guard.GrantLimits
    #   .missing 도커스트링의 배포 순서 TODO 참고).
    #   ⚠️ 초과는 **400 = 포탈 기준 영구 실패**다(위 분당 상한 주석과 같은 성질). 전역 축에서는
    #   사고 때만 보이던 모양이 아바타 축에서는 **개별 유저의 정상 연속 구매**로 나타날 수 있어서,
    #   값은 "정상 유저 상위 관측치의 3~5배"로 넉넉하게 잡는다(예: 인터널 첫 배선 hour=20/day=100).
    #   그리고 카운트는 상태를 보지 않는다 — 체인 장애로 FAILED 가 된 건도 이 축을 소모한다
    #   (환급 후 재구매가 한 시간 막힐 수 있다). 그때 처방은 값 상향이지 축 제거가 아니다.
    #   ⚠️ 임박 경고(80%)는 값이 5 미만이면 발화 대역이 비어 있다(`used >= cap` 이 먼저 거절).
    #   경고를 받고 싶으면 5 이상으로 잡는다.
    grant_max_grants_per_avatar_per_hour: Optional[int] = None
    grant_max_grants_per_avatar_per_day: Optional[int] = None
    # 의미적 중복 **경고**의 관측 창(초). 같은 (아바타, 상품)이 이 창 안에 2건 이상이면
    #   Slack 경고만 남기고 **요청은 통과**시킨다 — 정상 반복 구매와 구분할 수 없어서 거절하면
    #   정상 구매를 막는다(거절은 위의 아바타 축 상한이 한다).
    #   기본 None = 끔. 켜려면 60 정도를 넣고, 끌 때는 0(빈 값은 파싱 오류다).
    #   ⚠️ 기본을 켜 두지 않는 이유: 정상 반복 구매에서도 발화하는 신호라 기본값으로 켜면
    #   거절 알림과 같은 채널이 오탐으로 채워진다(알림 피로 → 진짜 거절을 놓친다). "포탈
    #   이중 요청이 의심될 때 켜는 진단 스위치"로 쓴다.
    grant_duplicate_alert_window_seconds: Optional[int] = None
    # 가드 위반 알림. 워커의 WORKER_IAP_ALERT_WEBHOOK_URL 과 **같은 값**(같은 Slack 채널)을 넣는다.
    iap_alert_webhook_url: Optional[str] = None

    @field_validator("grant_allowed_namespaces")
    @classmethod
    def _validate_grant_allowed_namespaces(cls, value: str) -> str:
        """
        fail-closed 파서 — 형식 위반이면 **부팅이 실패**한다.

        런타임 400 으로 미루지 않는 이유: 오타 하나가 포인트샵 전체를 조용히 세우는데,
        그때는 이미 주문이 쌓인 뒤다. 배포 시점에 터지는 쪽이 훨씬 싸다.
        """
        parse_grant_namespaces(value)
        return value

    @property
    def converted_gql_url_map(self) -> dict[PlanetID, str]:
        return {PlanetID(k.encode()): v for k, v in self.gql_url_map.items()}

    @property
    def is_production(self) -> bool:
        """운영 배포인가 — 머니 가드 fail-closed 게이트 판정용(voucher 게이트와 같은 집합)."""
        return self.stage in ("production", "mainnet")

    model_config = SettingsConfigDict(env_file=(".env"), env_prefix="API_")


config = Settings()
