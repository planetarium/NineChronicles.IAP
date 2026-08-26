from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, Header, HTTPException
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


@router.get("", response_model=List[CategorySchema])
def product_list(
    agent_addr: str,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    planet_id: str = "",
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
    purchase_history = get_purchase_history(sess, planet_id, agent_addr)
    for category in all_category_list:
        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
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
            if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
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
