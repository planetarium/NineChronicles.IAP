from datetime import datetime
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

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[CategorySchema])
def product_list(agent_addr: str,
                 x_iap_packagename: Annotated[PackageName | None, Header()] = PackageName.NINE_CHRONICLES_M,
                 planet_id: str = "", sess=Depends(session),
                 ):
    if not planet_id:
        planet_id = PlanetID.ODIN if config.stage == "mainnet" else PlanetID.ODIN_INTERNAL
    else:
        planet_id = PlanetID(bytes(planet_id, "utf-8"))

    # raise not found exception in thor network
    if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
        raise HTTPException(status_code=404, detail="available product not found")

    agent_addr = format_addr(agent_addr)
    all_category_list = sess.scalars(
        select(Category)
        .options(
            joinedload(Category.product_list).joinedload(Product.fav_list),
            joinedload(Category.product_list).joinedload(Product.fungible_item_list),
        )
        .where(Category.active.is_(True))
    ).unique().fetchall()

    category_schema_list = []
    purchase_history = get_purchase_history(sess, planet_id, agent_addr)
    for category in all_category_list:
        # Do not show Mileage category for thor chain
        if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL) and category.name == "Mileage":
            continue

        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
            schema = ProductSchema.model_validate(product)

            # Change Apple SKU for K
            if x_iap_packagename == PackageName.NINE_CHRONICLES_K:
                schema.apple_sku = product.apple_sku_k

            if (not product.active or
                    ((product.open_timestamp and product.open_timestamp > datetime.now()) or
                     (product.close_timestamp and product.close_timestamp <= datetime.now()))
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

                schema.mileage *= 5
                for item in schema.fungible_item_list:
                    item.amount *= 5
                for fav in schema.fav_list:
                    fav.amount *= 5

            schema_dict[product.id] = schema

        cat_schema.product_list = list(schema_dict.values())
        category_schema_list.append(cat_schema)

    return category_schema_list


@router.get("/all", response_model=List[SimpleProductSchema])
@cache(expire=3600)
def all_product_list(sess=Depends(session)):
    return sess.scalars(select(Product)).fetchall()
