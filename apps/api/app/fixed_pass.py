"""고정 SKU 시즌패스 — 시즌 번호와 구성품을 결제 SKU 가 아니라 시즌 정의·회차 행에서 읽는다.

## 구조 (C안)
- 스토어에서 실제로 파는 건 **고정 행** 하나(`g_pkg_couragepasspremium`)다. 가격·마일리지·복권
  매핑·한도는 이 행에 있다. 구성품은 없다.
- 시즌별 구성품은 지금처럼 상품 시트로 매달 올리는 **회차 행**(`g_pkg_couragepass36premium`)에
  둔다. 회차 행은 스토어에 등록하지 않고 NoShow 에도 연결하지 않는다 — 구성품 정의용이다.
- 시즌 번호는 시즌패스 서버(`GET /api/season-pass/current`)가 정답이다. 결제는 **결제 시각**
  (`at`)으로, 상점 표시는 지금 시각으로 묻는다.

## 실패 정책
회차 행이 없거나 시즌을 못 정하면 줄 구성품이 없다. 상점은 그 상품을 구매 불가로 내보내고
(클라가 결제창 전에 막는다), 결제 경로는 시즌패스를 부르기 전에 거절한다.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import requests
from shared.enums import PlanetID, ReceiptStatus
from shared.models.product import (
    SEASON_PASS_SKU_TOKEN,
    FixedPassKind,
    Product,
    fixed_pass_display_name,
    fixed_pass_kind,
    season_component_sku,
)
from shared.schemas.product import FungibleAssetValueSchema, FungibleItemSchema
from shared.models.receipt import Receipt
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from app.config import config

logger = logging.getLogger(__name__)

#: 시즌패스 조회 timeout(초) — 결제 경로. 시즌 조회는 부작용 없는 GET 이라 한 번 더 시도한다
#:   (`PURCHASE_LOOKUP_TRIES`). 이 호출은 commit 전이라 #482 advisory 락(lock_timeout 10s)을
#:   쥔 채 기다린다. requests 의 timeout 은 연결·읽기에 **각각** 걸려서 한 번에 최악 ~4s,
#:   두 번이면 ~8s 다 — 10s 예산 안이지만 여유가 작다. 늘리지 말 것.
SEASON_LOOKUP_TIMEOUT = 2
PURCHASE_LOOKUP_TRIES = 2
#: 상점 목록용 timeout(초). 상점 요청은 클라 상점 초기화·결제 직전 재확인마다 나가고, 같은
#:   스레드풀을 결제(/request)와 나눠 쓴다 — 시즌패스가 느려도 상점이 오래 붙잡히지 않게 짧게.
LISTING_LOOKUP_TIMEOUT = 1
#: 상점 표시용 캐시 수명(초). 시즌 경계는 아래 `contains` 로 따로 끊으므로, 이 값은 시즌
#:   정의가 시즌 중간에 고쳐졌을 때(PUT) 얼마나 늦게 따라갈지만 정한다.
LISTING_CACHE_TTL = 60
#: 시즌이 없다는 응답(404)과 조회 실패를 캐시하는 시간(초). 시즌패스 장애·경계 직후 시즌 미등록
#:   때 상점 요청마다 timeout 을 기다리지 않게 한다.
LISTING_NEGATIVE_TTL = 10


def is_pass_sku(sku: str) -> bool:
    # is_season_pass_product 와 같은 규칙(스키마에는 ORM 이 아니라 SKU 문자열만 있다).
    return SEASON_PASS_SKU_TOKEN in (sku or "")


class SeasonLookupError(Exception):
    """시즌패스 서버에 물어보지 못했다(연결·timeout·5xx). 시즌이 없다는 뜻이 아니다."""


@dataclass(frozen=True)
class SeasonWindow:
    season_index: int
    start: Optional[datetime]
    end: Optional[datetime]

    def contains(self, at: datetime) -> bool:
        # 시즌패스 get_pass 와 같은 규칙: 양 끝 포함, None 은 무기한.
        return (self.start is None or self.start <= at) and (
            self.end is None or at <= self.end
        )


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def fetch_season(
    pass_type: str,
    planet_id: PlanetID,
    at: Optional[datetime] = None,
    timeout: float = SEASON_LOOKUP_TIMEOUT,
) -> Optional[SeasonWindow]:
    """`at`(기본: 지금)에 진행 중인 시즌. 시즌이 없으면 None, 묻지 못하면 SeasonLookupError.

    `at` 을 줬으면 돌려받은 시즌이 실제로 `at` 을 포함하는지 확인한다. 시즌패스가 `at` 을 모르는
    옛 버전이면 모르는 파라미터를 무시하고 **지금** 시즌을 주기 때문이다 — 배포 순서 실수가
    엉뚱한 시즌 지급이 아니라 조회 실패로 드러나게 한다.
    """
    params = {"planet_id": planet_id.value.decode("utf-8"), "pass_type": pass_type}
    if at is not None:
        if at.tzinfo is None:
            raise ValueError("`at` must be timezone-aware")
        # requests 가 params 를 인코딩한다 — `+00:00` 을 URL 에 손으로 붙이면 공백이 돼 422.
        params["at"] = at.astimezone(timezone.utc).isoformat()
    try:
        resp = requests.get(
            f"{config.season_pass_host}/api/season-pass/current",
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise SeasonLookupError(str(e)) from e
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise SeasonLookupError(f"{resp.status_code} :: {resp.text[:200]}")
    try:
        body = resp.json()
        window = SeasonWindow(
            season_index=int(body["season_index"]),
            start=_parse_ts(body.get("start_timestamp")),
            end=_parse_ts(body.get("end_timestamp")),
        )
    except (ValueError, KeyError, TypeError) as e:
        # 200 인데 모양이 다르다(점검 페이지·스키마 변경). 상점 전체 500 이 되지 않게 조회 실패로.
        raise SeasonLookupError(f"malformed season response :: {e}") from e
    if at is not None and not window.contains(at):
        raise SeasonLookupError(
            f"season {window.season_index} does not contain {at.isoformat()} "
            "(season-pass without `at` support?)"
        )
    return window


def fetch_season_for_purchase(
    pass_type: str, planet_id: PlanetID, at: datetime
) -> Optional[SeasonWindow]:
    """결제 경로용 — 일시 오류면 한 번 더 묻는다. 실패하면 그 결제는 거절(환불)로 끝나기 때문이다."""
    last = None
    for _ in range(PURCHASE_LOOKUP_TRIES):
        try:
            return fetch_season(pass_type, planet_id, at=at)
        except SeasonLookupError as e:
            last = e
    raise last


#: 값: (창 | None(시즌 없음) | str(조회 실패 메시지), 받은 시각)
_listing_cache: Dict[Tuple[str, bytes], Tuple[object, float]] = {}
_listing_lock = threading.Lock()


def current_season_for_listing(
    pass_type: str, planet_id: PlanetID
) -> Optional[SeasonWindow]:
    """상점 표시용 — 지금 시즌을 짧게 캐시한다. 묻지 못하면 SeasonLookupError.

    캐시는 시즌 창(`contains`)과 TTL 을 둘 다 통과해야 쓴다. 경계를 넘긴 창은 TTL 이 남아도
    버린다 — 지난 시즌 이름을 내보내면 클라가 지난 시즌 상품을 찾아 버린다.
    """
    key = (pass_type, planet_id.value)
    now = datetime.now(timezone.utc)
    mono = time.monotonic()
    with _listing_lock:
        hit = _listing_cache.get(key)
    if hit is not None:
        cached, fetched = hit
        if isinstance(cached, SeasonWindow):
            if mono - fetched < LISTING_CACHE_TTL and cached.contains(now):
                return cached
        elif mono - fetched < LISTING_NEGATIVE_TTL:
            if isinstance(cached, str):
                # 같은 예외 객체를 여러 요청이 다시 던지면 traceback 이 계속 쌓인다 → 매번 새로.
                raise SeasonLookupError(cached)
            return None
    try:
        window = fetch_season(pass_type, planet_id, timeout=LISTING_LOOKUP_TIMEOUT)
    except SeasonLookupError as e:
        with _listing_lock:
            _listing_cache[key] = (str(e), mono)
        raise
    if window is not None and not window.contains(now):
        # 받은 시즌이 이미 끝났다(시계 차이 등) — 캐시하지 않는다.
        return window
    with _listing_lock:
        _listing_cache[key] = (window, mono)
    return window


def clear_listing_cache() -> None:
    with _listing_lock:
        _listing_cache.clear()


def find_component_product(
    sess, fixed_product: Product, kind: FixedPassKind, season_index: int
) -> Optional[Product]:
    """고정 행에 대응하는 회차 행(구성품 정의). 정확히 한 행이고 구성품이 있어야 한다.

    `active` 는 보지 않는다 — 회차 행은 팔지 않으므로 active 가 뜻이 없고, 운영자가 지난 시즌
    행을 끄는 습관이 있어도 그 시즌 결제(경계 늦은 도착)는 404 → 환불로 따로 끝난다.
    """
    sku = season_component_sku(fixed_product.google_sku, season_index)
    rows = (
        sess.scalars(
            select(Product)
            .options(joinedload(Product.fav_list))
            .options(joinedload(Product.fungible_item_list))
            .where(Product.google_sku == sku)
        )
        .unique()
        .all()
    )
    if len(rows) != 1:
        logger.error(
            f"[FIXED_PASS_NO_COMPONENT] {kind.token} season={season_index} "
            f"sku={sku} rows={len(rows)}"
        )
        return None
    row = rows[0]
    if not (row.fav_list or row.fungible_item_list):
        logger.error(
            f"[FIXED_PASS_NO_COMPONENT] {kind.token} season={season_index} "
            f"sku={sku} has no components"
        )
        return None
    return row


# ── 상점 목록(`GET /api/product`) ─────────────────────────────────────────────


def apply_fixed_pass_listing(sess, schema, product: Product, kind: FixedPassKind, planet_id, memo) -> bool:
    """고정 행 스키마에 이번 시즌 이름·구성품을 넣는다. 못 정하면 False(호출자가 구매 불가로 둔다).

    이름은 클라가 상품을 찾는 키다(`{PASS}{시즌}Premium`). 주입하지 않으면 DB 의 고정 행 이름
    (`COURAGEPASSPremium` 처럼 숫자 없이)이 나가서 어떤 클라도 그 상품을 못 찾는다 = 판매 정지.
    `memo` 는 요청 하나 안에서 같은 고정 행을 두 번 풀지 않게 한다.
    """
    if product.google_sku not in memo:
        window = component = None
        try:
            window = current_season_for_listing(kind.pass_type, planet_id)
        except SeasonLookupError as e:
            logger.error(f"[FIXED_PASS_UNRESOLVED] {kind.token} season lookup failed :: {e}")
        if window is not None:
            component = find_component_product(sess, product, kind, window.season_index)
        else:
            logger.error(f"[FIXED_PASS_UNRESOLVED] {kind.token} no current season")
        memo[product.google_sku] = (window, component)
    window, component = memo[product.google_sku]
    if window is None or component is None:
        return False

    schema.name = fixed_pass_display_name(kind, window.season_index)
    schema.fav_list = [FungibleAssetValueSchema.model_validate(x) for x in component.fav_list]
    schema.fungible_item_list = [
        FungibleItemSchema.model_validate(x) for x in component.fungible_item_list
    ]
    return True


def drop_shadowed_pass_rows(category_schema_list) -> None:
    """고정 행이 응답에 있으면 같은 종류의 회차 행을 응답에서 뺀다. 그 뒤에도 이름이 겹치면 뺀다.

    클라는 시즌패스 상품을 **이름으로** 사전에 넣는데(NineChronicles IAPStoreManager
    `SeasonPassProduct.Add`, try 밖), 이름이 겹치면 상점 초기화가 통째로 죽는다. 주입한 이름은
    그 시즌 회차 행의 DB 이름과 같으므로, 회차 행이 NoShow 에 남아 있으면(전환 직후·운영 실수)
    바로 충돌한다. **응답만 거른다** — DB 행(active·기간)은 건드리지 않는다.

    고정 행이 응답에 없으면 아무것도 하지 않는다(응답이 지금과 바이트 단위로 같다).
    """
    fixed_tokens = {
        k.token
        for cat in category_schema_list
        for p in cat.product_list
        if (k := fixed_pass_kind(p.google_sku)) is not None
    }
    if not fixed_tokens:
        return
    seen_names = {}
    for cat in category_schema_list:
        kept = []
        for p in cat.product_list:
            sku = p.google_sku or ""
            if any(re.search(rf"_pkg_{t}\d+premium$", sku) for t in fixed_tokens):
                continue
            if is_pass_sku(sku):
                if p.name in seen_names:
                    logger.error(
                        f"[FIXED_PASS_NAME_CONFLICT] {p.name} :: {sku} dropped "
                        f"(kept {seen_names[p.name]})"
                    )
                    continue
                seen_names[p.name] = sku
            kept.append(p)
        cat.product_list = kept


# ── 구매 한도 ─────────────────────────────────────────────────────────────────

#: 고정 SKU 시즌패스는 **아바타당 시즌당 1회**. 회차 SKU 시절엔 상품이 시즌마다 달라서 상품 단위
#:   누적(account_limit)이 곧 시즌 단위였지만, 고정 행은 시즌을 넘어 같은 상품이라 시즌 창으로 센다.
FIXED_PASS_LIMIT_PER_SEASON = 1


def count_granted_in_season(
    sess, product: Product, receipt, season_index: int, component: Product
) -> int:
    """이 아바타가 이 시즌 패스를 **지급까지 받은** 횟수(현재 영수증 제외).

    시즌은 영수증에 기록한 `data.SeasonPassGrant.season_index` 로 가른다. `purchased_at` 은
    Google 에서 클라가 보낸 값 그대로라 시즌 키로 믿을 수 없고, 시즌 창이 나중에 수정되면
    소급해서 바뀐다. 전환 시즌에 **회차 SKU 로 산 건**(같은 시즌의 회차 행 = `component`)도 센다.

    `VALID` 이면서 `msg` 가 비어 있는 것만 센다 — 시즌패스 영수증은 성공하면 msg 가 없고,
    실패·불확실 건(VALID+msg)은 지급 여부를 모르니 재구매를 막지 않는다(실제로 지급됐다면
    시즌패스가 중복으로 거절한다). INIT 등 미완료 건을 세지 않는 것도 같은 이유다 — 멈춘
    영수증 하나가 그 시즌 구매를 영영 막으면 안 된다.

    ⚠️ receipt 에 (product_id, avatar_addr) 인덱스가 없어 seq scan 이다 — 회차 SKU 의
    `check_purchase_limit` 도 같은 비용이라 회귀는 아니지만, 인덱스 추가는 후속 과제다.
    """
    # 정수 캐스트 대신 문자열 비교 — data 는 클라 JSON 을 그대로 담으니 숫자가 아닌 값이 든
    #   행이 있으면 캐스트가 500 을 낸다. 우리가 쓰는 값은 int 라 `->>` 결과가 "36" 이다.
    granted_season = Receipt.data["SeasonPassGrant"]["season_index"].as_string()
    stmt = select(func.count(Receipt.id)).where(
        Receipt.planet_id == receipt.planet_id,
        Receipt.avatar_addr == receipt.avatar_addr,
        Receipt.status == ReceiptStatus.VALID,
        Receipt.msg.is_(None),
        or_(
            and_(Receipt.product_id == product.id, granted_season == str(int(season_index))),
            Receipt.product_id == component.id,
        ),
    )
    if receipt.id is not None:
        stmt = stmt.where(Receipt.id != receipt.id)
    return sess.scalar(stmt) or 0
