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
from shared.enums import PlanetID
from shared.models.product import (
    SEASON_PASS_SKU_TOKEN,
    FixedPassKind,
    Product,
    fixed_pass_display_name,
    fixed_pass_kind,
    season_component_sku,
)
from shared.schemas.product import FungibleAssetValueSchema, FungibleItemSchema
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import config

logger = logging.getLogger(__name__)

#: 시즌패스 조회 timeout(초). 상점 목록과 결제 경로 둘 다 이 호출을 기다린다.
SEASON_LOOKUP_TIMEOUT = 2
#: 상점 표시용 캐시 수명(초). 시즌 경계는 아래 `contains` 로 따로 끊으므로, 이 값은 시즌
#:   정의가 시즌 중간에 고쳐졌을 때(PUT) 얼마나 늦게 따라갈지만 정한다.
LISTING_CACHE_TTL = 60
#: 시즌이 없다는 응답(404)을 캐시하는 시간(초). 경계 직후 새 시즌 등록이 늦으면 반복 조회가
#:   상점 요청마다 나가지 않게 한다.
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
    pass_type: str, planet_id: PlanetID, at: Optional[datetime] = None
) -> Optional[SeasonWindow]:
    """`at`(기본: 지금)에 진행 중인 시즌. 시즌이 없으면 None, 묻지 못하면 SeasonLookupError."""
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
            timeout=SEASON_LOOKUP_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SeasonLookupError(str(e)) from e
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise SeasonLookupError(f"{resp.status_code} :: {resp.text[:200]}")
    body = resp.json()
    return SeasonWindow(
        season_index=int(body["season_index"]),
        start=_parse_ts(body.get("start_timestamp")),
        end=_parse_ts(body.get("end_timestamp")),
    )


_listing_cache: Dict[Tuple[str, bytes], Tuple[Optional[SeasonWindow], float]] = {}
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
        window, fetched = hit
        ttl = LISTING_CACHE_TTL if window else LISTING_NEGATIVE_TTL
        if mono - fetched < ttl and (window is None or window.contains(now)):
            return window
    window = fetch_season(pass_type, planet_id)
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
