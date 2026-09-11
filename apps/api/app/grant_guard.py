"""
(PLD-1575) 지급 API 머니 가드 — 상품 화이트리스트 · 발행 상한 · 네임스페이스 등록제/레이트리밋.

`POST /api/admin/grant`(PLD-1564)는 `GrantItems` **force-grant** 를 admin JWT 하나로 노출한다.
지급 계정 잔액이 없어도 발행되므로 사실상 민터 권한이고, 온체인이라 회수가 불가능하다.
토큰 유출이나 호출측(포탈) 버그 하나가 "임의 상품 × 임의 아바타 × 무제한" 이 되는 구조여서
**무엇을(상품) · 얼마나(수량·빈도) · 누가(네임스페이스)** 세 축을 요청 시점에 닫는다.

`voucher_validation.py`(PLD-1472 의 C1/C3-lite/C6 머니 가드)의 형제 모듈이고 같은 규칙을 따른다:

  · **순수 모듈** — `app.config` 를 임포트하지 않는다(상한·허용목록을 인자로 받는다).
    테스트가 env 없이 임계값을 주입할 수 있고, 거꾸로 `app.config` 가 이 모듈의 파서를
    부팅 검증에 쓸 수 있다(순환 임포트 방지).
  · 위반은 FastAPI 예외로 표면화 — 호출부(admin.py)가 그대로 전파한다.
  · 얼로우리스트(deny-by-default) — 상품유형·네임스페이스가 추가돼도 기본이 차단이다.

## 가드 위반은 400 이고 **아웃박스 행을 만들지 않는다**
계약 v1.1: 아웃박스에 FAILED 행이 남으면 포탈이 **자동 환급**(SHOP_REFUND)을 트리거한다.
가드 위반은 "지급이 시작되지도 않았다"는 뜻이라 환급 대상이 아니고, 포탈이 주문을 그대로
실패 처리하면 된다. 그래서 모든 검사가 INSERT **전에** 끝나고, 이 모듈은 행을 만들지 않는다.
같은 이유로 nonce 규약(채번 후 실패를 FAILED 로 종단하지 않는다)도 건드리지 않는다 —
가드는 nonce 채번(워커) 훨씬 앞단이다.

## 이 경로는 "유저가 포인트를 냈는지"를 검증하지 않는다 — **못 한다**
포인트 원장은 포탈에 있고 IAP 는 잔액을 모른다. 마일리지(IAP 가 자기 잔액을 검증한다)와
결정적으로 다른 점이고, 그래서 이 경로는 **포탈을 신뢰하는 구조**다. 신뢰가 깨지는 경로
(포탈 버그·토큰 유출)에서 **가드 상한이 곧 blast radius** 이므로, 상한은 "넉넉하게 잡아 두는
운영 편의 값"이 아니라 사고 시 최대 발행량 그 자체다.

## 중복 방어는 4층이고 층마다 막는 게 다르다
  ① `grant_outbox.external_ref` UNIQUE — 같은 ref 재요청 → tx 1건 (IAP)
  ② 포탈 `(userId, requestId)` unique — 클라이언트 재전송 (포탈)
  ③ 워커의 조건부 UPDATE 선점 — 동시 처리 이중 tx (IAP)
  ④ **아바타 축 시간창 상한** — 한 아바타에 몰리는 발행량 (이 모듈, PLD-1575)

①~③ 이 다 통과하는 구멍이 하나 남는다: **포탈이 같은 구매에 새 orderId 를 붙여 두 번**
요청하면 `external_ref` 가 달라 멱등이 안 걸린다. IAP 는 "이미 산 건"인지 알 수단이 없다
(주문의 권위가 포탈에 있다). 그래서 이 모듈은 두 갈래로 대응한다:
  · **거절**은 아바타 축 상한이 한다(④) — 한 아바타가 시간창 전량을 태우지 못하게.
  · **의미적 중복**(같은 `(avatar_addr, product_id)` 의 짧은 창 반복)은 **경고만** 한다.
    정상 반복 구매(1회 뽑기 연속 클릭·룬스톤 팩 2개)와 구분되지 않아서, 거절하면 정상
    구매를 막는다. 사람이 포탈 `shop_order` 와 대조할 근거만 만든다.

## 아직 없는 축 (후속)
- **엔드포인트별 스코프가 없다.** admin JWT 하나로 화이트리스트 CRUD·상품 CSV import 도 열려
  있어서, 토큰이 유출되면 공격자가 스스로 화이트리스트를 켤 수 있다. 이 가드가 닫는 것은
  "무제한 발행"이고 "토큰 유출 시 임의 상품"은 스코프 분리(후속) 없이는 닫히지 않는다.
  그래서 화이트리스트를 켜는 순간에도 Slack 알림을 남긴다(admin.py).

## 설정 미주입(prod)은 400 이 아니라 503
상한이 안 박힌 prod 는 **운영 실수**지 호출자 잘못이 아니다. 400 을 주면 포탈이 주문을 영구
실패로 처리(=포인트 환급)하는데, 실제로는 아무 일도 안 일어난 상태다. 503 이면 포탈이
재시도하고, 행이 없으니 재시도가 안전하다(멱등키도 아직 안 쓰였다).
"""
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException
from shared.enums import ProductType
from shared.models.grant_outbox import GrantOutbox
from shared.models.product import (
    GACHA_KIND_FAV,
    GACHA_KIND_ITEM,
    SEASON_PASS_SKU_TOKEN,
    Product,
)
from shared.utils.address import format_addr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

# 네임스페이스(external_ref 의 `:` 앞부분) 허용 문자. `external_ref` 패턴의 부분집합이고
#   `:` 를 뺀다(구분자). `%` 는 문자집합에서 빠져 있고, 허용되는 `_` 는 LIKE 와일드카드지만
#   prefix 카운트에서 `autoescape=True` 로 이스케이프한다(`_count_since` 참고).
NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")

# 허용목록 전체 비활성(킬스위치) 신호. CSV voucher 컬럼의 `-`(전체 제거) 관례와 같은 표기.
#   빈 문자열을 킬스위치로 쓰지 않는 이유: 오타·미주입과 구분되지 않는다(그건 부팅 실패여야 한다).
NAMESPACE_DENY_ALL = "-"

# 같은 위반 사유가 반복될 때 Slack 알림·요청 지연을 만들지 않도록 하는 최소 간격(초).
#   루프 도는 호출자가 초당 수십 건을 던져도 채널은 사유별 1분 1건만 본다.
ALERT_THROTTLE_SECONDS = 60.0
# 스로틀 상태(프로세스 전역 dict)의 상한. 키는 정규화돼 유한하지만 무한 증식 여지를 없앤다.
ALERT_THROTTLE_MAX_KEYS = 256
# 미등록 네임스페이스를 스로틀 키에서 접을 때 쓰는 고정 라벨(호출자 제어 문자열 배제).
UNREGISTERED_NAMESPACE_LABEL = "<unregistered>"
# 임박 경고 스로틀 키에서 아바타를 접을 때 쓰는 고정 라벨(`GrantScope.coarse_key` 참고).
AVATAR_COLLAPSED_LABEL = "<any>"

# 시간창 사용률이 이 비율을 넘으면 **거절 전에** 경고를 쏜다. 임계값(상한)이 아니라 알림
#   휴리스틱이라 설정으로 빼지 않는다 — 이 값이 바뀌어도 발행 가능량은 변하지 않는다.
WINDOW_WARN_RATIO = 0.8

# 의미적 중복 경고의 임계 건수(**이번 요청 포함**). 2 = "같은 아바타·상품이 창 안에 두 번".
#   중복의 최소 단위가 2 라 3 이상으로 올리면 평범한 이중 전송(정확히 2건)을 영구히 놓친다.
DUPLICATE_ALERT_MIN_COUNT = 2

# 카운트→INSERT 구간을 직렬화하는 PG advisory lock 키(임의 상수, 이 가드 전용).
GRANT_GUARD_LOCK_KEY = 15751564


class GrantGuardViolation(HTTPException):
    """
    머니 가드 위반. `status_code` 는 400(호출자 잘못) 또는 503(설정 미주입).

    `reason` 은 알림 스로틀 키 · 감사 로그 필드로 쓰는 안정적인 식별자다(사람이 읽는 문장은
    `detail`). 응답 본문은 기존 400 과 같은 `{"detail": ...}` 이라 포탈 클라이언트에 영향이 없고,
    **detail 앞에 `[reason]` 을 붙인다** — 포탈이 "일시 초과(재시도 가치 있음)"와 "잘못된 요청"을
    문장 대신 토큰으로 구분할 수 있어야 한다(계약 v1.2 에서 상태코드를 나눌 때까지의 다리).
    """

    def __init__(self, status_code: int, reason: str, detail: str):
        super().__init__(status_code=status_code, detail=f"[{reason}] {detail}")
        self.reason = reason


def parse_grant_namespaces(raw: Optional[str]) -> frozenset:
    """
    쉼표 구분 허용 네임스페이스 목록 → 집합. **fail-closed 파서**: 형식 위반은 ValueError.

    `"shop"` · `"shop, promo"` 처럼 쓴다. `"-"` 단독은 전체 비활성(킬스위치).
    빈 값/None 은 오류다 — 미주입·오타가 조용히 "전부 허용"이나 "전부 차단"이 되면 안 되고,
    부팅 시점에 터지는 게 낫다(`app.config` 의 validator 가 이걸 호출한다).
    """
    if raw is None:
        raise ValueError("grant_allowed_namespaces 미설정 — 최소 1개(또는 킬스위치 '-') 필요")
    tokens = [token.strip() for token in str(raw).split(",")]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("grant_allowed_namespaces 가 비어 있습니다 — 최소 1개(또는 '-') 필요")
    if NAMESPACE_DENY_ALL in tokens:
        if len(tokens) != 1:
            # '-' 를 다른 값과 섞으면 의도가 모호하다(voucher CSV 의 '-' 규칙과 동일).
            raise ValueError(
                f"'{NAMESPACE_DENY_ALL}'(전체 비활성)은 단독으로만 쓸 수 있습니다: {tokens}"
            )
        return frozenset()
    for token in tokens:
        if not NAMESPACE_PATTERN.match(token):
            raise ValueError(f"네임스페이스 '{token}' 형식 위반 — {NAMESPACE_PATTERN.pattern}")
    return frozenset(tokens)


# (PLD-1575) 상품 CSV 의 `point_shop_grantable` 컬럼 토큰. 화이트리스트를 **켜는 경로**의
#   파서도 가드 모듈에 모아 둔다(같은 fail-closed 규칙이고, import_utils 는 이걸 재사용한다).
# ⚠️ 문자 `O` 는 넣지 않는다 — 숫자 `0`(=False) 오타가 True 로 읽히는 방향이라
#   "끄려다 켜는" 사고가 된다. 머니 플래그에서 그 비대칭은 허용 못 한다.
GRANTABLE_TRUE_TOKENS = frozenset({"TRUE", "T", "Y", "YES", "1"})
GRANTABLE_FALSE_TOKENS = frozenset({"FALSE", "F", "N", "NO", "0", "X", "-"})


def parse_point_shop_grantable(value: Optional[str]) -> Optional[bool]:
    """
    상품 CSV 의 `point_shop_grantable` 셀 → True/False/**None(=변경 없음)**.

    **3상태여야 한다.** "TRUE 아니면 False" 로 읽으면 컬럼이 없는 기존 시트로 임포트할 때마다
    전 상품의 화이트리스트가 조용히 꺼진다(= 포인트샵 전면 중단). 빈칸·컬럼 부재는 유지고,
    명시적으로 쓴 값만 반영한다.

    해석 불가 토큰은 ValueError — 머니 플래그라 "모르는 값은 False" 도 위험하다(오타로 꺼져도
    장애고, 무엇보다 운영자가 켠 줄 알고 방치한다). 임포트를 세우는 쪽이 낫다.
    """
    if value is None:
        return None
    token = value.strip().upper()
    if token == "":
        return None
    if token in GRANTABLE_TRUE_TOKENS:
        return True
    if token in GRANTABLE_FALSE_TOKENS:
        return False
    raise ValueError(
        f"point_shop_grantable '{value}' 를 해석할 수 없습니다"
        f" (허용: {sorted(GRANTABLE_TRUE_TOKENS)} / {sorted(GRANTABLE_FALSE_TOKENS)}"
        " / 빈칸=유지)"
    )


def namespace_of(external_ref: str) -> Optional[str]:
    """`shop:<orderId>` → `shop`. `:` 가 없으면 None(네임스페이스 없음 = 등록제 위반)."""
    namespace, separator, _ = external_ref.partition(":")
    return namespace if separator and namespace else None


@dataclass(frozen=True)
class GrantScope:
    """
    시간창을 **무엇으로 세는가**. 지정한 필드가 AND 로 걸리고, 전부 None 이면 전역(전체 합)이다.

    축이 늘어날 때마다 (a) 카운트 조건 (b) 사람이 읽는 라벨 (c) 알림 스로틀 키 세 곳을 따로
    고치면 하나를 빼먹는다 — 특히 (c) 를 빼먹으면 서로 다른 축·아바타의 경고가 같은 키로
    접혀 서로를 삼킨다. 그래서 셋을 한 타입에 묶는다.

    ⚠️ `planet_id` 는 일부러 넣지 않았다. 같은 아바타 주소가 두 행성에 있으면 합쳐서 세는데,
    그건 상한을 **더 엄격하게** 만드는 방향이라(발행 총량 관점) 안전한 쪽 오차다.
    """

    namespace: Optional[str] = None
    avatar_addr: Optional[str] = None
    product_id: Optional[int] = None

    @property
    def label(self) -> str:
        """거절·경고 문구에 들어가는 사람이 읽는 축 이름."""
        parts = []
        if self.namespace is not None:
            parts.append(f"네임스페이스 '{self.namespace}'")
        if self.avatar_addr is not None:
            parts.append(f"아바타 {self.avatar_addr}")
        if self.product_id is not None:
            parts.append(f"상품 {self.product_id}")
        return " × ".join(parts) if parts else "전체"

    def _key(self, avatar: Optional[str]) -> str:
        parts = []
        if self.namespace is not None:
            parts.append(f"ns={self.namespace}")
        if avatar is not None:
            parts.append(f"avatar={avatar}")
        if self.product_id is not None:
            parts.append(f"product={self.product_id}")
        return "|".join(parts) or "all"

    @property
    def key(self) -> str:
        """
        **사건 단위** 스로틀 키(`alert_key` 와 같은 `<reason>:<스코프>` 관례).

        중복 경고처럼 사건 자체가 `(아바타, 상품)` 단위인 알림에 쓴다 — 접으면 한 건이 나머지
        전부를 1분간 가린다. 아바타가 키에 들어가므로 **볼륨이 아바타 수에 비례**한다는 걸
        알고 써야 한다(요청 경로에서 webhook POST 가 나간다). 축 전체를 대표하는 신호라면
        `coarse_key` 를 쓴다.
        """
        return self._key(self.avatar_addr)

    @property
    def coarse_key(self) -> str:
        """
        **볼륨을 접는** 스로틀 키 — 아바타를 고정 라벨로 바꾼다(`alert_key` 와 같은 원칙).

        임박 경고에 쓴다. 그 신호의 내용은 "이 축의 상한에 근접한 아바타가 있다"이고 **어느
        아바타인지는 메시지와 구조 로그에 남는다**. 아바타를 키에 넣으면 상한 근처의 아바타
        수만큼 요청 경로에서 webhook POST 가 나가고(아바타 30 = POST 30건, 스로틀이 하나도
        접지 못한다) 그 키들이 스로틀 저장소를 밀어낸다 — 후자는 위반 알림 스로틀까지 지운다.
        """
        return self._key(None if self.avatar_addr is None else AVATAR_COLLAPSED_LABEL)


GLOBAL_SCOPE = GrantScope()


@dataclass(frozen=True)
class GrantWarning:
    """
    거절하지 않는 경고 1건. `on_warning` 이 이걸 받는다.

    `throttle_key` 를 메시지와 같이 들고 다니는 이유: 키를 호출부(admin.py)에서 만들면
    축이 늘어날 때마다 거기서 `reason` 문자열을 다시 해석해야 하고(= 축을 아는 곳이 둘로
    갈라진다), 아바타·상품 같은 스코프 값은 호출부에 없다.
    """

    reason: str  # 안정적 식별자(로그 필드·스로틀 키의 앞부분). 경고는 `_warn` 접미어.
    message: str  # 사람이 읽는 설명
    throttle_key: str  # `should_warn` 에 넣는 키


def scope_warn_key(reason: str, scope_key: str) -> str:
    """경고 스로틀 키 — `alert_key`(위반용)와 같은 `<reason>:<스코프>` 표기."""
    return f"{reason}:{scope_key}"


@dataclass(frozen=True)
class GrantLimits:
    """
    가드 임계값 묶음. **하드코딩 금지** — 전부 설정에서 온다(`limits_from_settings`).

    `None` = 미강제. 개발/인터널에서는 그게 편하지만 prod 에서는 fail-open 이므로
    `missing()` 이 비어야만 지급을 허용한다(`enforce_grant_guards` 의 503 게이트).
    """

    allowed_namespaces: frozenset
    # 지급 허용 FAV 티커. 빈 집합 = FAV 지급 금지(기본값이자 가장 안전한 상태)라
    #   `missing()` 에 넣지 않는다 — 미주입이 곧 fail-closed 다.
    allowed_fav_tickers: frozenset = frozenset()
    max_fav_units_per_request: Optional[int] = None
    max_item_units_per_request: Optional[int] = None
    max_grants_per_hour: Optional[int] = None
    max_grants_per_day: Optional[int] = None
    max_grants_per_namespace_per_minute: Optional[int] = None
    # 아바타 축(PLD-1575 후속) — 전역 상한은 **총노출**을 묶고 이건 **집중도**를 묶는다.
    #   전역만 있으면 한 아바타가 시간창 전량을 태울 수 있고, 그게 포탈을 신뢰하는 이 경로의
    #   실제 사고 모양(한 계정의 포인트 원장 오류/어뷰즈)이다.
    max_grants_per_avatar_per_hour: Optional[int] = None
    max_grants_per_avatar_per_day: Optional[int] = None
    # 의미적 중복 **경고**의 관측 창(초). None/0 이하 = 끔. 거절하지 않는다(모듈 도커스트링).
    duplicate_alert_window_seconds: Optional[int] = None

    def missing(self) -> List[str]:
        """
        prod 에서 반드시 주입돼야 하는데 비어 있는 항목 이름.

        ⚠️ 이 목록은 **배포 시점 fail-closed 트랩**이다 — 여기 이름을 하나 추가하면 그 env 가
        차트에 배선되기 **전에** 새 이미지가 뜨는 순간 지급 API 전체가 503(포인트샵 정지)이 되고,
        화이트리스트 켜는 경로(admin.py 의 upsert)도 같이 막힌다. 그래서 새 축을 여기 넣는 건
        "차트에 값이 이미 있다"가 확인된 다음이다.

        아바타 축·중복 경고 창을 아직 넣지 않은 이유:
          · 총노출은 `max_grants_per_hour/day`(이미 필수)가 이미 묶는다. 아바타 축은 그 안의
            **집중도**만 좁히므로, 미주입이 "무제한 발행"이 되지는 않는다.
          · 중복 경고는 애초에 거절하지 않는 관측 기능이라 필수 대상이 아니다.
        TODO(PLD-1575): 차트에 `API_GRANT_MAX_GRANTS_PER_AVATAR_PER_{HOUR,DAY}` 가 배선된
        뒤에 두 이름을 이 목록에 올린다(그 시점엔 트랩이 아니라 안전망이 된다).
        """
        return [
            name
            for name in (
                "max_fav_units_per_request",
                "max_item_units_per_request",
                "max_grants_per_hour",
                "max_grants_per_day",
                "max_grants_per_namespace_per_minute",
            )
            if getattr(self, name) is None
        ]


def limits_from_settings(settings) -> GrantLimits:
    """
    `app.config.Settings` → `GrantLimits`. **덕 타이핑**(임포트하지 않는다 — 순환 방지·테스트 용이).

    네임스페이스 파싱은 부팅 시점에 이미 검증됐다(config validator). 여기서 다시 파싱하는 건
    문자열 하나 split 이라 비용이 없고, 런타임에 값이 바뀌는 경로가 생겨도 가드가 최신을 본다.
    """
    return GrantLimits(
        allowed_namespaces=parse_grant_namespaces(settings.grant_allowed_namespaces),
        allowed_fav_tickers=parse_fav_tickers(settings.grant_allowed_fav_tickers),
        max_fav_units_per_request=settings.grant_max_fav_units_per_request,
        max_item_units_per_request=settings.grant_max_item_units_per_request,
        max_grants_per_hour=settings.grant_max_grants_per_hour,
        max_grants_per_day=settings.grant_max_grants_per_day,
        max_grants_per_namespace_per_minute=(
            settings.grant_max_grants_per_namespace_per_minute
        ),
        max_grants_per_avatar_per_hour=settings.grant_max_grants_per_avatar_per_hour,
        max_grants_per_avatar_per_day=settings.grant_max_grants_per_avatar_per_day,
        duplicate_alert_window_seconds=settings.grant_duplicate_alert_window_seconds,
    )


def _type_name(product_type: Optional[Union[ProductType, str]]) -> str:
    """ORM enum / 문자열 / None 을 같은 문자열로. voucher_validation 과 같은 방식."""
    return (getattr(product_type, "name", None) or str(product_type)).strip().upper()


def validate_point_shop_grantable_eligible(
    product_id: int,
    product_type: Optional[Union[ProductType, str]],
    google_sku: Optional[str] = None,
) -> None:
    """
    이 상품에 `point_shop_grantable` 을 **켤 수 있는가** — 현금 상품이면 400.

    화이트리스트 플래그 자체가 1차 가드지만, 플래그를 켜는 경로(백오피스 CRUD · CSV import)와
    지급 경로 **양쪽에서** 이 검사를 돌린다. 이유는 플래그가 스테일해질 수 있기 때문이다:
    CSV import 는 기존 상품의 `product_type` 을 바꿀 수 있어서, 한 번 켠 플래그가 나중에
    현금 상품에 붙어 있을 수 있다. 지급 시점 재검증이 그 창을 닫는다.

    얼로우리스트가 아니라 **명시 차단 목록**인 이유: 포인트샵 상품이 어떤 유형으로 등록될지는
    기획 소관(FREE 가 자연스럽지만 MILEAGE 도 가능)이고, 여기서 좁히면 운영이 막힌다.
    반드시 막아야 하는 건 "현금이 오간 상품을 무상 발행하는 것"이다. 단 **미지 유형은 차단**한다
    (ProductType 에 새 유형이 추가돼도 기본이 차단, None·오전달도 조용히 통과하지 않는다).
    """
    name = _type_name(product_type)
    known = {member.name for member in ProductType}
    if name not in known:
        raise GrantGuardViolation(
            400,
            "product_type_unknown",
            f"product {product_id} product_type={name} — 알 수 없는 상품유형(포인트샵 지급 불가)",
        )
    if name == ProductType.IAP.name:
        raise GrantGuardViolation(
            400,
            "cash_product",
            f"product {product_id} product_type={name} — 현금 상품은 무상 지급 대상이 아닙니다"
            " (포인트샵 전용 상품만 허용)",
        )
    if google_sku and SEASON_PASS_SKU_TOKEN in google_sku:
        # 시즌패스는 현금 패스고 지급 주체가 SeasonPass 서비스다 — IAP 가 발행할 물건이 아니다.
        raise GrantGuardViolation(
            400,
            "season_pass_product",
            f"product {product_id} sku={google_sku} — 시즌패스 상품은 포인트샵 지급 대상이 아닙니다",
        )


def grant_units(
    product: Product, gacha_claim: Optional[List[dict]] = None
) -> Tuple[Decimal, int]:
    """
    이 상품 1건 지급이 발행하는 총량 (FAV 합, 아이템 개수 합).

    ⚠️ (PLD-1562) **뽑기 상품은 `product.fav_list`/`fungible_item_list` 가 비어 있다** —
       상금이 풀(`product_gacha_entry`)에 있기 때문이다. 그래서 뽑기를 그냥 통과시키면
       발행량이 항상 `(0, 0)` 으로 계산돼 **모든 수량 상한을 무조건 통과**한다(가드가
       뽑기에만 통째로 꺼지는 셈이다).

    ⚠️ 넘기는 값이 **풀 행이 아니라 동결된 `claim`** 인 이유: 워커가 체인에 실어 보내는 게
       바로 그 claim 이다(`grant_task` 는 풀을 읽지 않는다). 풀 행을 재면 "가드가 검사한
       바이트"와 "체인에 나가는 바이트"가 서로 다른 저장소가 되어, 둘이 어긋나는 순간
       가드가 헛것을 재게 된다. 고정 상품은 양쪽이 같은 테이블을 읽어 이 갈라짐이 없다.
       덤으로 `claim_from_result` 의 fail-closed 검증이 **요청 시점으로 앞당겨진다** —
       형식 오류가 "유저가 포인트를 쓰고 결과까지 본 뒤 FAILED→환급" 이 아니라 400 이 된다.

    ⚠️ claim 은 **`kind` 로 가른다.** 뽑기 풀은 아이템과 FAV 를 둘 다 담으므로(룬스톤·
       소울스톤·크리스탈이 FAV 축이다) 여기서 합치면 FAV 상한이 아이템 상한에 흡수된다 —
       "물약 1,000개를 허용하려고 올린 상한이 NCG 1,000 발행을 허용한다"가 그대로 재현된다.
       `kind` 는 추첨 시점에 결과에 동결된 값이라 티커 접두어로 추측하지 않는다.

    FAV(NCG·CRYSTAL 등)와 아이템을 **따로** 센다. 하나로 합치면 상한이 큰 쪽에 맞춰지고
    (예: 물약 1,000개를 허용하려고 올린 상한이 NCG 1,000 발행을 허용한다) 가드가 무의미해진다.

    ⚠️ FAV 합은 **티커를 구분하지 않는다** — CRYSTAL 기준으로 잡은 수량 상한이 SOULSTONE
    발행 한도가 된다(개당 가치가 자릿수로 다르다). 그래서 수량 상한만으로는 부족하고,
    티커 자체를 얼로우리스트로 막는다(`check_fav_tickers`). 수량 상한은 그 위의 2차 방어다.
    """
    if gacha_claim is not None:
        # 뽑기는 **뽑힌 칸 하나**만 지급한다(풀 전체가 아니다). 풀 전체를 세면 상한이
        # 사실상 0 이 되어 정상 뽑기가 전부 거절된다.
        gacha_fav = Decimal(0)
        gacha_items = 0
        for row in gacha_claim:
            kind = row.get("kind")
            if kind == GACHA_KIND_FAV:
                gacha_fav += Decimal(str(row["amount"]))
            elif kind == GACHA_KIND_ITEM:
                gacha_items += int(row["amount"])
            else:
                # 모르는 kind 를 조용히 버리면 **양쪽 합계에서 다 빠져 (0,0) 이 되어 두
                #   상한을 모두 통과한다**. 이 모듈은 "모르는 입력은 fail-closed" 가 원칙이다.
                raise GrantGuardViolation(
                    400,
                    "gacha_claim_unknown_kind",
                    f"product {product.id} 뽑기 결과의 kind 를 모릅니다: {kind!r}",
                )
        return gacha_fav, gacha_items
    fav = sum((Decimal(str(row.amount)) for row in product.fav_list), Decimal(0))
    items = sum((int(row.amount) for row in product.fungible_item_list), 0)
    return fav, items


def parse_fav_tickers(raw: Optional[str]) -> frozenset:
    """
    쉼표 구분 지급 허용 FAV 티커 목록 → 집합. **빈 값/None = 빈 집합 = FAV 지급 전면 금지.**

    네임스페이스 파서와 달리 빈 값이 오류가 아닌 이유: 여기서는 빈 값이 **가장 안전한 상태**고
    (기본값이기도 하다) 포인트샵 상품은 원칙적으로 아이템이다. FAV 를 지급하려면 티커를
    명시적으로 열어야 한다 — 화폐 발행은 "실수로 열려 있는" 상태가 없어야 한다.
    """
    if not raw:
        return frozenset()
    return frozenset(token.strip() for token in str(raw).split(",") if token.strip())


def check_fav_tickers(
    product: Product, allowed: frozenset, gacha_claim: Optional[List[dict]] = None
) -> None:
    """
    이 상품이 지급할 FAV 티커가 전부 허용목록 안인지.

    ⚠️ (PLD-1562) **뽑힌 칸의 FAV 도 본다.** 뽑기 상품은 `product.fav_list` 가 비어 있고
       상금이 풀에 있으므로, 여기서 product 만 보면 룬스톤·크리스탈 뽑기가 얼로우리스트를
       통째로 우회한다(화폐 발행이 "실수로 열려 있는" 상태가 된다 — 이 모듈이 가장 피하는 것).

    수량 상한보다 이게 먼저 필요한 가드다: `product.fav_list` 는 상품 CSV(`fungible-assets/import`)
    로 갈아치울 수 있어서, 화이트리스트에 이미 올라간 상품의 구성품을 CRYSTAL → NCG 로 바꾸면
    수량 상한은 그대로 통과한다. 티커 얼로우리스트가 그 경로를 닫는다.

    상태코드를 두 갈래로 나눈다 — 이 모듈의 "미주입은 400 이 아니라 503" 규칙과 같은 이유다:
      · 허용목록이 **비어 있는데** FAV 상품이 왔다 → **503**. 배선을 잊은 운영 실수일 수 있고,
        400 이면 포탈이 그 주문을 영구 실패(=포인트 환급)로 확정한다. 503 이면 재시도한다.
        (정말 "FAV 는 안 준다"는 정책이면 그 상품을 화이트리스트에 켜지 않으면 된다 —
         그때는 이 지점까지 오지 않는다.)
      · 허용목록이 있는데 이 상품 티커가 밖이다 → **400**. 상품 구성 오류라 재시도해도 같다.
    """
    tickers = {row.ticker for row in product.fav_list}
    tickers |= {
        row["ticker"]
        for row in (gacha_claim or [])
        if row.get("kind") == GACHA_KIND_FAV
    }
    if not tickers:
        return
    if not allowed:
        raise GrantGuardViolation(
            503,
            "fav_tickers_unset",
            f"product {product.id} 는 FAV({sorted(tickers)})를 지급하는데"
            " 허용 티커 목록(grant_allowed_fav_tickers)이 비어 있습니다"
            " — 티커를 열거나 이 상품을 화이트리스트에서 내려야 합니다",
        )
    denied = sorted(tickers - allowed)
    if denied:
        raise GrantGuardViolation(
            400,
            "fav_ticker_not_allowed",
            f"product {product.id} FAV 티커 {denied} 는 지급 허용목록 밖입니다"
            f" (허용: {sorted(allowed)})",
        )


def _count_since(
    sess: Session, since: datetime, scope: GrantScope = GLOBAL_SCOPE
) -> int:
    """
    `since` 이후 생성된 아웃박스 행 수 — `scope` 가 **무엇으로 세는가**를 정한다(기본 전역).

    상태를 보지 않는다 — PENDING/GRANTED/FAILED 모두 "발행을 시도했다"는 사실이고, 상한의
    목적은 발행 시도 자체를 묶는 것이다(FAILED 도 nonce·tx 를 소모했을 수 있다).

    인덱스: 전역/네임스페이스 축은 `ix_grant_outbox_created_at`, 아바타·상품 축은
    `ix_grant_outbox_avatar_addr_created_at` 을 탄다. 이 카운트는 요청 경로 **그리고 advisory
    lock 안**에서 돌기 때문에 지연이 곧 직렬화된 처리량이다(느린 카운트 = 지급 처리량 저하).
    """
    stmt = (
        select(func.count())
        .select_from(GrantOutbox)
        .where(GrantOutbox.created_at >= since)
    )
    if scope.namespace is not None:
        stmt = stmt.where(
            GrantOutbox.external_ref.startswith(f"{scope.namespace}:", autoescape=True)
        )
    if scope.avatar_addr is not None:
        # 저장 형식과 **같게 정규화된 주소**여야 한다 — 대소문자가 다르면 카운트가 0 이 되어
        #   조용히 fail-open 이다. `enforce_grant_guards` 가 `format_addr` 로 정규화해서 넣는다.
        stmt = stmt.where(GrantOutbox.avatar_addr == scope.avatar_addr)
    if scope.product_id is not None:
        stmt = stmt.where(GrantOutbox.product_id == scope.product_id)
    return int(sess.scalar(stmt) or 0)


def guard_now(sess: Session) -> datetime:
    """
    시간창의 기준시각. PG 에서는 **DB 시계**를 쓴다.

    행의 `created_at` 은 DB `now()` 로 찍히는데(TimeStampMixin) 창의 경계를 앱 시계로 잡으면
    앱↔DB 스큐가 그대로 창을 밀어버린다. 앱이 앞서면 `since` 가 미래가 되어 카운트가 0 —
    **fail-open** 이다. 같은 시계에서 양쪽을 재면 스큐가 상쇄된다.
    SQLite(테스트)의 `now()` 는 문자열을 돌려주므로 앱 시계를 쓴다(단일 프로세스라 스큐 없음).
    """
    if sess.get_bind().dialect.name != "postgresql":
        return datetime.now(timezone.utc)
    return sess.scalar(select(func.now()))


def lock_grant_guard(sess: Session) -> None:
    """
    카운트→INSERT 구간을 직렬화한다(PG 전용, 트랜잭션 종료 시 자동 해제).

    DB 카운트 기반 레이트리밋은 그냥 두면 TOCTOU 다 — 동시 요청 2건이 둘 다 "아직 여유 있음"을
    보고 둘 다 INSERT 한다. advisory **xact** lock 이라 커밋/롤백에서 알아서 풀리고, 잠금 하나로
    전 네임스페이스를 직렬화한다(락 순서 역전 = 데드락 여지를 없앤다. 포인트샵 주문량에서
    직렬화 비용은 무의미하다).

    ⚠️ 호출부 계약: 이 잠금 이후의 카운트와 INSERT/commit 이 **같은 트랜잭션**이어야 한다.
    SQLite(테스트)에는 advisory lock 이 없어 no-op 이다 — 단일 스레드 테스트라 무해하다.
    """
    bind = sess.get_bind()
    if bind.dialect.name != "postgresql":
        return
    sess.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": GRANT_GUARD_LOCK_KEY}
    )


def enforce_claim_guards(
    product: Product,
    *,
    limits: GrantLimits,
    gacha_claim: Optional[List[dict]] = None,
) -> None:
    """
    **지급 내용**에 걸리는 가드 — 구성품 티커 얼로우리스트 + 요청 단위 발행량 상한.

    `enforce_grant_guards` 에서 떼어낸 이유(PLD-1562): 이 두 검사만 **뽑힌 칸을 알아야**
    한다. 나머지(네임스페이스·상품 화이트리스트·레이트리밋)는 추첨과 무관하다.

    ⚠️ 이 분리가 **조용한 재추첨**을 막는다. 추첨은 아웃박스 행을 만들기 전에 일어나므로,
       가드가 거절하면 행이 없고 → 포탈 재시도가 멱등에 안 걸려 **다시 뽑는다**.
       레이트리밋처럼 *일시적인* 거절이 추첨 뒤에 있으면 재시도마다 결과가 갈리고, 공시
       확률이 차단 칸을 제외하고 조용히 재정규화된다(화면엔 99% 인데 실제로는 다른 값이
       나온다 — 확률형 아이템에서 가장 피해야 할 모양이고, 아무 로그도 안 남는다).
       그래서 **추첨과 무관한 가드를 전부 앞으로** 보냈다. 여기 남는 거절(수량 상한·티커
       얼로우리스트)은 **영구 오류**라 재시도해도 같은 결과이고, 애초에 CSV 임포트가 등록
       시점에 막는다(import_utils 의 assert_gacha_* 두 개).

    ⚠️ 거절 사유의 우선순위가 바뀌었다 — 예전엔 수량 상한이 레이트리밋보다 먼저 나왔다.
       두 축이 동시에 초과면 이제 레이트리밋 토큰이 보인다(둘 다 400 이라 포탈 분기는 동일).
    """
    fav_units, item_units = grant_units(product, gacha_claim)
    if (
        limits.max_fav_units_per_request is not None
        and fav_units > limits.max_fav_units_per_request
    ):
        raise GrantGuardViolation(
            400,
            "fav_units_exceeded",
            f"product {product.id} FAV 발행량 {fav_units} > 상한"
            f" {limits.max_fav_units_per_request}",
        )
    if (
        limits.max_item_units_per_request is not None
        and item_units > limits.max_item_units_per_request
    ):
        raise GrantGuardViolation(
            400,
            "item_units_exceeded",
            f"product {product.id} 아이템 발행량 {item_units} > 상한"
            f" {limits.max_item_units_per_request}",
        )
    check_fav_tickers(product, limits.allowed_fav_tickers, gacha_claim)


def enforce_grant_guards(
    sess: Session,
    *,
    external_ref: str,
    product: Product,
    avatar_addr: str,
    limits: GrantLimits,
    is_production: bool,
    now: Optional[datetime] = None,
    on_warning: Optional[Callable[["GrantWarning"], None]] = None,
) -> str:
    """
    지급 요청 1건에 머니 가드 전부를 적용하고 네임스페이스를 돌려준다. 위반은 `GrantGuardViolation`.

    호출 순서 계약:
      1. **멱등 조회가 먼저다.** 이미 있는 `external_ref` 재요청은 이 함수를 타지 않는다 —
         이미 tx 가 나갔을 수 있는 주문을 뒤늦은 상한 변경으로 400 으로 만들면 포탈 폴링이
         깨지고(계약: 재요청 = 200) 지급/환급 판정이 뒤집힌다.
      2. 값이 싼 검사(설정·네임스페이스·상품·수량)를 먼저, DB 카운트를 마지막에.
      3. 이 함수가 성공하면 **같은 트랜잭션에서** INSERT+commit 해야 한다(잠금 유효 구간).
      3-1. (PLD-1562) 이 함수는 **추첨과 무관한 가드만** 본다. 지급 내용 가드는
         `enforce_claim_guards` 이고, 순서는 **이 함수 → 추첨 → 그 함수** 다.
      4. 위반(예외)으로 빠졌으면 호출부가 **먼저 rollback** 해서 잠금·트랜잭션을 놓고 나서
         알림 같은 외부 I/O 를 해야 한다(안 그러면 Slack 지연이 전 지급 요청을 줄 세운다).

    `avatar_addr` 는 저장 형식(`format_addr` — 소문자 `0x…`)으로 **이 함수가 정규화한다**.
    아바타 축 카운트가 `grant_outbox.avatar_addr` 와 문자열 비교라, 정규화를 호출부 규약으로만
    두면 대소문자 하나로 카운트가 0 이 되어 조용히 fail-open 한다(`_count_since` 참고).

    `on_warning(GrantWarning)` 는 **거절 전에** 부르는 소프트 임계 경고다(아래 참고).
    선택 인자로 둔 이유: 이 모듈은 알림 수단(webhook·config)을 몰라야 한다.
    ⚠️ 이 콜백은 **잠금을 잡은 상태**에서 호출된다 — 외부 I/O(webhook)를 여기서 하면 안 된다.
    호출부는 메시지를 모아 두고 commit **뒤에** 보낸다(admin.py).
    """
    # ── 0) 설정 fail-closed 게이트 ────────────────────────────────────────────
    if is_production:
        missing = limits.missing()
        if missing:
            raise GrantGuardViolation(
                503,
                "limits_unset",
                f"grant 머니 가드 임계 미설정: {', '.join(missing)}"
                " — prod 에서는 상한 주입 후에만 지급할 수 있습니다",
            )

    # ── 1) 호출자 식별: external_ref 네임스페이스 등록제 ─────────────────────
    namespace = namespace_of(external_ref)
    if namespace is None:
        raise GrantGuardViolation(
            400,
            "namespace_missing",
            f"externalRef '{external_ref}' 에 네임스페이스가 없습니다"
            " — `<namespace>:<orderId>` 형식이어야 합니다",
        )
    if namespace not in limits.allowed_namespaces:
        raise GrantGuardViolation(
            400,
            "namespace_not_allowed",
            f"externalRef 네임스페이스 '{namespace}' 는 등록되지 않았습니다"
            f" (허용: {sorted(limits.allowed_namespaces) or '없음(전체 비활성)'})",
        )

    # ── 2) 상품 화이트리스트 ──────────────────────────────────────────────────
    if not bool(getattr(product, "point_shop_grantable", False)):
        raise GrantGuardViolation(
            400,
            "product_not_whitelisted",
            f"product {product.id} 는 포인트샵 지급 대상이 아닙니다"
            " (point_shop_grantable=false — 상품 CSV 나 백오피스에서 켜야 합니다)",
        )
    # 플래그 스테일 방어(도커스트링 참고): 켠 뒤에 현금 상품으로 바뀐 경우를 지급 시점에 잡는다.
    validate_point_shop_grantable_eligible(
        product.id, product.product_type, product.google_sku
    )

    # ── 3) 지급 내용 가드는 `enforce_claim_guards` 로 떼어냈다(PLD-1562).
    #      호출 순서는 **이 함수 → 추첨 → enforce_claim_guards** 다. 근거는 그쪽 도커스트링.

    # ── 4) 시간창 총량 + 네임스페이스/아바타 레이트리밋 (경합 안전) ──────────
    #   축 순서 = 거절 사유의 우선순위다. 기존 축(분·시·일 전역)을 앞에 두는 이유: 여러 축이
    #   동시에 초과일 때 포탈이 보던 사유 토큰이 바뀌지 않게 한다(계약 v1.2 의 부류 판정이
    #   토큰 문자열에 붙어 있다). 아바타 축은 뒤에 붙여 **전역이 여유일 때만** 표면화한다.
    #   주소는 **여기서** 저장 형식으로 정규화한다(호출부가 이미 그렇게 넘겨도 멱등이다).
    #   호출부 규약으로만 두면 대소문자가 다른 주소 하나로 카운트가 0 이 되어 **조용히
    #   fail-open** 한다 — 머니 가드에서 그건 허용 못 하는 실패 모양이다.
    avatar_addr = format_addr(avatar_addr)
    avatar_scope = GrantScope(avatar_addr=avatar_addr)
    windows = (
        (
            "per_minute_exceeded",
            limits.max_grants_per_namespace_per_minute,
            timedelta(minutes=1),
            GrantScope(namespace=namespace),
        ),
        (
            "per_hour_exceeded",
            limits.max_grants_per_hour,
            timedelta(hours=1),
            GLOBAL_SCOPE,
        ),
        (
            "per_day_exceeded",
            limits.max_grants_per_day,
            timedelta(days=1),
            GLOBAL_SCOPE,
        ),
        (
            "per_avatar_hour_exceeded",
            limits.max_grants_per_avatar_per_hour,
            timedelta(hours=1),
            avatar_scope,
        ),
        (
            "per_avatar_day_exceeded",
            limits.max_grants_per_avatar_per_day,
            timedelta(days=1),
            avatar_scope,
        ),
    )
    # 중복 경고 창: None/0 이하 = 끔(env 로 끄려면 0 을 넣는다 — 빈 문자열은 파싱 오류다).
    #   경고를 받을 사람이 없으면(`on_warning is None`) 세지도 않는다 — 이 카운트는 잠금
    #   안에서 도는 추가 쿼리라 결과를 버릴 거면 켤 이유가 없다.
    duplicate_window: Optional[timedelta] = None
    if on_warning is not None and (limits.duplicate_alert_window_seconds or 0) > 0:
        duplicate_window = timedelta(seconds=limits.duplicate_alert_window_seconds)
    if (
        not any(cap is not None for _, cap, _, _ in windows)
        and duplicate_window is None
    ):
        # 셀 것이 없으면 잠금도 잡지 않는다 — 이 잠금은 전 지급 요청을 직렬화한다.
        return namespace
    lock_grant_guard(sess)
    now = now or guard_now(sess)
    for reason, cap, window, scope in windows:
        if cap is None:
            continue
        used = _count_since(sess, now - window, scope)
        if used >= cap:
            raise GrantGuardViolation(
                400,
                reason,
                f"{scope.label} 지급 건수 상한 초과: 최근 {window} 동안 {used}건 ≥ 상한 {cap}"
                " — 임계를 올리거나 잠시 후 다시 시도하세요",
            )
        if on_warning is not None and used >= cap * WINDOW_WARN_RATIO:
            # 거절이 시작된 **뒤에만** 알리면 운영자가 손 쓸 기회가 없다(첫 초과 주문이 이미
            #   영구 실패다). 임박 경고가 상한 유지의 실질적 완화책이다.
            #   ⚠️ 스로틀 키는 `coarse_key`(아바타 접힘)다 — 정확 키를 쓰면 상한 근처의 아바타
            #   수만큼 요청 경로에서 webhook POST 가 나간다. 어느 아바타인지는 문구·로그에 있다.
            warn_reason = f"{reason}_warn"
            on_warning(
                GrantWarning(
                    warn_reason,
                    f"{scope.label} 지급 건수 상한 임박: 최근 {window} 동안 {used}건"
                    f" / 상한 {cap} — 초과분은 400 으로 거절된다",
                    scope_warn_key(warn_reason, scope.coarse_key),
                )
            )

    # ── 5) 의미적 중복 감지 — **경고만, 요청은 통과** ────────────────────────
    #   같은 `(avatar_addr, product_id)` 의 짧은 창 반복은 "포탈이 같은 구매를 두 번 보냈다"의
    #   신호지만 **정상 반복 구매와 구분되지 않는다**(1회 뽑기 연속 클릭·같은 팩 2개 구매).
    #   그래서 거절은 위의 아바타 축 상한이 하고, 여기서는 사람이 볼 근거만 만든다.
    #   잠금 안에서 세는 이유는 축을 아는 코드를 한 곳에 모으고 위와 **같은 `now`** 를 쓰는
    #   것뿐이다(경고 전용이라 정확성이 잠금을 요구하지는 않는다). 직렬 구간이 문제가 되면
    #   커밋 뒤로 옮길 수 있고, 그때는 방금 넣은 행이 카운트에 포함돼 아래 `+1` 이 사라진다.
    if duplicate_window is not None and on_warning is not None:
        dup_scope = GrantScope(avatar_addr=avatar_addr, product_id=product.id)
        # 카운트는 **이번 요청 직전까지**의 행이다(INSERT 는 아직 안 했다) → +1 이 총 건수.
        repeats = _count_since(sess, now - duplicate_window, dup_scope) + 1
        if repeats >= DUPLICATE_ALERT_MIN_COUNT:
            dup_reason = "duplicate_grant_warn"
            window_seconds = int(duplicate_window.total_seconds())
            on_warning(
                GrantWarning(
                    dup_reason,
                    f"{dup_scope.label} 지급 요청이 최근 {window_seconds}초 동안"
                    f" {repeats}건 — 포탈이 같은 구매에 `새 external_ref 를 붙여 재요청`했을"
                    " 가능성이 있습니다(external_ref 가 다르면 IAP 멱등키가 걸리지 않는다)."
                    " 포탈 `shop_order` 에서 이 아바타·상품의 주문을 대조하세요."
                    " 정상 반복 구매와 구분되지 않아 `거절하지 않았고 지급은 진행된다`"
                    f" (externalRef=`{external_ref}`)",
                    # 중복은 사건 자체가 (아바타, 상품) 단위라 **정확 키**를 쓴다 — 접으면
                    #   먼저 뜬 한 건이 나머지 전부를 1분간 가린다.
                    scope_warn_key(dup_reason, dup_scope.key),
                )
            )
    return namespace


_alert_sent_at: Dict[str, float] = {}  # 위반(거절) 알림
_warn_sent_at: Dict[str, float] = {}  # 경고 알림 — 위반 스로틀을 밀어내지 않게 분리


def alert_key(reason: str, namespace: Optional[str], allowed: frozenset) -> str:
    """
    **위반**(거절) 알림의 스로틀 키. **호출자가 조종하는 값을 키에 넣지 않는다.**

    미등록 네임스페이스를 그대로 키에 넣으면 `promo1:x`, `promo2:x`, … 로 ref 만 바꿔 던지는
    것으로 키가 매번 새로워져 스로틀이 무력화된다(= Slack 도배 + 요청마다 webhook POST,
    스로틀 dict 무한 증식). 등록된 값만 남기고 나머지는 하나로 접는다.

    그래서 아바타 주소도 여기 들어가지 않는다 — 위반은 **행을 만들지 않고도** 발화할 수 있어서
    (미등록 네임스페이스가 그렇다) 키 카디널리티에 상한이 없다. 경고 쪽 키는 축에 따라 접는
    단위가 다르고 저장소도 분리돼 있다(`GrantScope.key`/`coarse_key` · `should_warn`).
    """
    label = namespace if namespace in allowed else UNREGISTERED_NAMESPACE_LABEL
    return f"{reason}:{label}"


def _throttle(store: Dict[str, float], key: str, now: Optional[float]) -> bool:
    """
    같은 키의 알림을 `ALERT_THROTTLE_SECONDS` 에 1회로 제한(프로세스 로컬, best-effort).

    왜 필요한가: 알림을 무조건 보내면 루프 도는 호출자가 Slack 을 도배하고, 더 나쁘게는
    **요청 경로에서 webhook POST 를 반복**해 API 를 스스로 느리게 만든다. 정확한 분산 스로틀이
    아니어도 목적(도배 방지)에는 충분하다 — API 는 단일 프로세스로 뜨고(workers=1),
    감사 근거는 스로틀되지 않는 구조 로그가 남긴다.

    저장소에 키 상한을 둔다 — 프로세스 수명이 긴 서비스에 무한 증식하는 전역 dict 를 남기지
    않는다. 넘칠 때 오래된 키부터 버리고, 그래도 넘치면 전부 비운다(= 그 순간의 스로틀 상태를
    잃는다). **그 부수효과 때문에 위반용/경고용 저장소를 나눈다** — 카디널리티가 큰 경고 키가
    위반 알림의 스로틀을 지우면 거절 알림 도배가 다시 열린다.
    """
    now = time.monotonic() if now is None else now
    if len(store) >= ALERT_THROTTLE_MAX_KEYS:
        for stale, at in list(store.items()):
            if now - at >= ALERT_THROTTLE_SECONDS:
                store.pop(stale, None)
        if len(store) >= ALERT_THROTTLE_MAX_KEYS:
            # 그래도 넘치면 버린다. 스로틀 상태를 잃는 최악의 결과는 "알림이 한 번 더 나감"이다.
            store.clear()
    last = store.get(key)
    if last is not None and now - last < ALERT_THROTTLE_SECONDS:
        return False
    store[key] = now
    return True


def should_alert(key: str, now: Optional[float] = None) -> bool:
    """**위반**(거절) 알림 스로틀. 키는 `alert_key` 로 정규화한다."""
    return _throttle(_alert_sent_at, key, now)


def should_warn(key: str, now: Optional[float] = None) -> bool:
    """
    **경고**(거절 아님) 알림 스로틀 — 위반 알림과 **다른 저장소**를 쓴다.

    경고 키는 스코프(아바타·상품)를 포함할 수 있어 위반 키보다 카디널리티가 크다. 한 저장소를
    공유하면 경고 키가 상한을 채워 `clear()` 를 유발하고, 그때 위반 알림의 스로틀 상태가 함께
    지워진다(= 거절 알림이 다시 도배된다). 반대 방향의 오염도 마찬가지로 막힌다.
    """
    return _throttle(_warn_sent_at, key, now)
