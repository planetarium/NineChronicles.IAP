from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, List

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi_cache.decorator import cache
from shared.enums import PackageName, PlanetID
from shared.models.product import Category, Product
from shared.schemas.product import CategorySchema, ProductSchema, SimpleProductSchema
from shared.utils.address import format_addr
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import config
from app.dependencies import session
from app.utils import get_purchase_history
from app.voucher_display import attach_voucher_tickets

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


# (PLD-1575) 아래 `ProductCatalog` 의 설계 근거. **docstring 이 아니라 주석으로 둔다** —
#   pydantic 이 enum docstring 을 OpenAPI `components.schemas` 의 description 으로 싣고,
#   `/{stage}/openapi.json` 은 인증 없이 열려 있어 내부 저장소 경로·티켓·배포 논의가 공개
#   계약 문서로 새 나간다(Unity 클라 코드 생성 입력이기도 하다).
#
# **왜 기본값이 `cash` 인가**(= 왜 "제외하려면 `catalog=cash` 를 붙여라"로 만들지 않았는가):
#   · 게임 클라·현금 웹샵이 **코드를 한 줄도 고치지 않고** 안전해진다. 포인트 전용 상품은 현금
#     `price_list` 가 비어 있어 기존 클라가 0원으로 그리거나 깨진다 — 그 노출을 막는 게 이
#     파라미터의 목적인데, 옵트아웃으로 만들면 목적 달성이 클라 배포에 인질로 잡힌다.
#   · 마이그레이션이 `NOT NULL DEFAULT false` 라 기존 상품은 전부 현금 카탈로그다 → 기본 호출의
#     응답은 지금과 **바이트 단위로 같다**(플래그를 켠 상품이 생기기 전까지).
#
# **배포 순서**: 어느 순서든 잘못된 노출은 생기지 않지만 순서 의존이 아예 없는 건 아니다.
#   · 포탈 선배포: FastAPI 는 모르는 쿼리 파라미터를 무시하므로 옛 IAP 에 `catalog=point` 를
#     보내도 400 이 아니라 옛 동작(전 카탈로그)이 온다. 포탈은 그중 `shop_sku` 매핑에 있는
#     productId 만 내보내므로 화면은 그대로다 = 무해.
#   · IAP 선배포: 포탈이 아직 파라미터를 안 붙인 구간에는 포인트 상품이 응답에서 사라져
#     **포인트샵이 빈 목록**이 된다(listShopSkus 가 전 SKU 를 orphan 으로 보고 200 + 빈 items,
#     알람은 울리지 않는다). 노출 사고는 아니지만 가용성 사고라, **포탈 변경이 차단 후속**이다.
#     (2026-09 현재 포탈 포인트샵 자체가 미배포 브랜치라 실사용 영향은 없다.)
#
# **운영 전제 — 포인트 상품을 어느 카테고리에 넣는가**: 이 필터는 상품만 걸러내고 카테고리는
#   비어도 응답에 남긴다(기간 밖 상품만 있는 카테고리가 이미 그렇게 나가고 있어 모양이 바뀌지
#   않는다). 그런데 게임 샵·현금 웹샵은 **돌려준 카테고리 수만큼 탭을 만든다**(게임:
#   `MobileShop.cs` 가 `c.Active && c.Name != "NoShow"`, 포탈 마켓: `CategoryList.tsx` 가 전부
#   렌더) → 포인트 전용 상품만 담긴 활성 카테고리를 새로 만들면 현금 쪽에 **빈 탭**이 생긴다.
#   그래서 포인트 상품은 게임 클라가 건너뛰는 `NoShow` 카테고리에 넣는 것을 전제로 한다
#   (카테고리 자체는 `active=true` 여야 한다 — 끄면 `catalog=point` 도 못 그린다).
#
# 이름을 `catalog`(축)으로 잡고 `include_point_products` 같은 불리언으로 하지 않은 이유:
#   "포인트만"을 표현하려면 불리언이 두 개 필요해지고, 나중에 백오피스 미리보기용 `all` 같은
#   값이 생겨도 기존 클라를 깨지 않고 얹을 수 있다. 값·이름은 저장소 관례대로 소문자다.
class ProductCatalog(str, Enum):
    """`GET /api/product` 가 돌려줄 카탈로그. 두 목록은 겹치지 않는다."""

    #: 현금 결제 카탈로그(기본) = `point_shop_grantable=false` 상품만.
    CASH = "cash"
    #: 포탈 포인트샵 카탈로그 = `point_shop_grantable=true` 상품만.
    POINT = "point"


_CATALOG_DESC = "카탈로그 선택. 기본 `cash`(현금 상품만) / `point`(포인트샵 전용 상품만). 두 목록은 안 겹친다"


@router.get("", response_model=List[CategorySchema])
def product_list(
    agent_addr: str,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    planet_id: str = "",
    catalog: Annotated[
        ProductCatalog, Query(description=_CATALOG_DESC)
    ] = ProductCatalog.CASH,
    sess=Depends(session),
):
    if not planet_id:
        planet_id = (
            PlanetID.ODIN if config.stage == "mainnet" else PlanetID.ODIN_INTERNAL
        )
    else:
        planet_id = PlanetID(bytes(planet_id, "utf-8"))

    agent_addr = format_addr(agent_addr)
    all_category_list = (
        sess.scalars(
            select(Category)
            .options(
                joinedload(Category.product_list).joinedload(Product.fav_list),
                joinedload(Category.product_list).joinedload(
                    Product.fungible_item_list
                ),
            )
            .where(Category.active.is_(True))
        )
        .unique()
        .fetchall()
    )

    category_schema_list = []
    # (PLD-1472) 복권 티켓을 붙일 대상. 응답에 실리는 것만 모아 **마지막에 한 번** 조회한다
    #   (여기서 상품마다 조회하면 카테고리×상품 수만큼 쿼리가 늘어난다 = N+1).
    voucher_targets = []
    # (PLD-1575) 카탈로그 판정은 루프 밖에서 한 번. 위 쿼리가 이미 상품을 다 로드했으므로
    #   필터는 파이썬에서 한다 — **쿼리를 추가하지 않는다.**
    #   ⚠️ 반대로 **줄이지도 못한다**: 바로 아래 `CategorySchema.model_validate(category)` 가
    #      필터 전에 카테고리의 전 상품을 `ProductSchema` 로 검증하면서 `price_list`(joinedload
    #      대상이 아니다) lazy load 를 상품 수만큼 유발하고, 그 결과는 루프 끝의
    #      `cat_schema.product_list = …` 로 버려진다. 선행 문제이지 이 변경이 만든 건 아니지만,
    #      `catalog=point` 도 전 카탈로그만큼의 price 쿼리를 지불한다는 뜻이다(캐시 없음).
    #      고치려면 필터된 목록으로 카테고리를 검증해야 한다 — 이 PR 범위 밖.
    want_point_catalog = catalog == ProductCatalog.POINT
    purchase_history = get_purchase_history(sess, planet_id, agent_addr)
    for category in all_category_list:
        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
            # (PLD-1575) 카탈로그가 다른 상품은 먼저 걷어낸다 — 기본(`cash`)에서 포인트 전용
            #   상품이 게임 클라·현금 웹샵으로 새 나가는 걸 막는 지점이 여기다(근거는 위
            #   `ProductCatalog` 주석). 아래 기존 필터(active·기간·구매 이력·복권 티켓)는 두
            #   카탈로그 모두 그대로 통과한다.
            if bool(product.point_shop_grantable) != want_point_catalog:
                continue

            schema = ProductSchema.model_validate(product)

            # Change Apple SKU for K
            if x_iap_packagename == PackageName.NINE_CHRONICLES_K:
                schema.apple_sku = product.apple_sku_k

            if not product.active or (
                (
                    product.open_timestamp
                    and product.open_timestamp > datetime.now(timezone.utc)
                )
                or (
                    product.close_timestamp
                    and product.close_timestamp <= datetime.now(timezone.utc)
                )
            ):
                schema.active = False
                schema.buyable = False
                continue

            # Check purchase history
            if product.daily_limit:
                schema.purchase_count = purchase_history["daily"][product.id]
                schema.buyable = schema.purchase_count < product.daily_limit
            elif product.weekly_limit:
                schema.purchase_count = purchase_history["weekly"][product.id]
                schema.buyable = schema.purchase_count < product.weekly_limit
            elif product.account_limit:
                schema.purchase_count = purchase_history["account"][product.id]
                schema.buyable = schema.purchase_count < product.account_limit
            else:  # Product with no limitation
                schema.buyable = True

            # Thor chain
            # (PLD-1575) **현금 카탈로그에만** 적용한다. 이 2배는 THOR 결제 프로모션이고
            #   (`shared/utils/grant.py` `THOR_PROMO_MULTIPLIER` — "결제 프로모션이라 무상
            #   지급에는 적용하지 않는다"), 포인트샵 지급 경로는 항상 1배다
            #   (`apps/worker/app/tasks/grant_task.py` `GRANT_MULTIPLIER = 1`).
            #   포탈 포인트샵은 이 응답의 `fav_list`/`fungible_item_list` 를 그대로 화면에
            #   그리므로, 여기서 부풀리면 **표시 2배 / 지급 1배**가 되어 포인트를 차감한 유저에게
            #   틀린 수량을 광고한다 — 바로 아래 복권 티켓과 같은 표시=지급 불변식이다.
            #   에셋 경로(`_THOR.png`)도 같이 건다: 포인트 전용 상품에 THOR 변형 에셋이 있을
            #   이유가 없어 그대로 두면 포탈이 없는 이미지를 렌더한다.
            if not want_point_catalog and planet_id in (
                PlanetID.THOR,
                PlanetID.THOR_INTERNAL,
            ):
                schema.path = schema.path.replace(".png", "_THOR.png")
                schema.popup_path_key += "_THOR"

                schema.mileage *= 2
                for item in schema.fungible_item_list:
                    item.amount *= 2
                for fav in schema.fav_list:
                    fav.amount *= 2

            schema_dict[product.id] = schema
            voucher_targets.append((product.id, schema))

        cat_schema.product_list = list(schema_dict.values())
        category_schema_list.append(cat_schema)

    # (PLD-1472) 복권 티켓은 응답 전체를 모아 쿼리 한 번으로 붙인다.
    #   ⚠️ 위 Thor 2배(mileage·아이템·FAV)의 대상이 **아니다**. 발급은 워커가 매핑 count 를 그대로
    #      쓰므로 여기서 부풀리면 표시 장수와 실제 지급 장수가 어긋난다.
    attach_voucher_tickets(sess, voucher_targets)

    return category_schema_list


@router.get("/all", response_model=List[SimpleProductSchema])
@cache(expire=3600)
def all_product_list(sess=Depends(session)):
    """전 상품 목록."""
    # (PLD-1575) 여기엔 카탈로그 분리를 **의식적으로 넣지 않았다.** 이름과 달리 이 엔드포인트는
    #   포인트 전용 상품도 그대로 내보낸다. 이유: 응답이 `SimpleProductSchema`(가격 없음)라
    #   "0원으로 그려진다"는 원래 문제가 없고, 알려진 소비자가 없다(게임 클라·포탈 grep 0건).
    #   소비자가 생기면 `/api/product` 와 같은 축을 여기에도 붙일 것.
    # ⚠️ 복권 티켓 매핑(`product_voucher_grant`)과 이 엔드포인트의 캐시 관계 — 선언과 실제가 다르다.
    #   선언상 `@cache(expire=3600)` 이므로 매핑을 백오피스에서 바꿔도 최대 1시간 늦게 반영돼야 한다.
    #   그런데 fastapi-cache 기본 key_builder 가 **kwargs 를 그대로 키에 넣는데**, 여기 kwargs 에는
    #   요청마다 새로 만들어지는 `sess`(scoped_session) 가 있어 키가 매번 달라진다 → 실측 5회 요청에
    #   5회 모두 MISS. 즉 **현재는 캐시가 사실상 동작하지 않아 지연도 없다**(대신 InMemoryBackend 에
    #   요청당 항목이 쌓이고 다시 읽히지 않아 만료 삭제도 안 된다 — 이 PR 범위 밖의 선행 문제).
    #   그래서 여기서는 캐시를 살리지도, TTL 을 손대지도 않는다. 살리는 순간 위 1시간 지연이
    #   **그때 처음** 생기므로 의식적으로 결정해야 한다. 살릴 때의 선택지:
    #     (a) TTL 단축, (b) 매핑 변경 시 admin PUT/DELETE 에서 `FastAPICache.clear`,
    #     (c) 캐시 키에 매핑 버전(max(updated_at)) 포함.
    #   (b)/(c) 는 백엔드가 프로세스 내 InMemoryBackend 라(main.py) 파드마다 따로 만료된다는 점까지
    #   같이 봐야 한다. 어느 쪽이든 게임 샵 UI 가 쓰는 건 캐시 없는 `GET /api/product` 라 영향은 없다.
    product_list = sess.scalars(select(Product)).fetchall()
    schema_list = [SimpleProductSchema.model_validate(p) for p in product_list]
    # 상품별 조회 금지(N+1) — 전 상품분을 한 번에 붙인다.
    attach_voucher_tickets(sess, zip((p.id for p in product_list), schema_list))
    return schema_list
