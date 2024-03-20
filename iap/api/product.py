from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from fastapi_cache.decorator import cache
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common.models.product import Product, Category
from common.utils.address import format_addr
from common.utils.receipt import PlanetID
from iap import settings
from iap.dependencies import session
from iap.schemas.product import CategorySchema, ProductSchema, SimpleProductSchema
from iap.utils import get_purchase_history

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[CategorySchema])
def product_list(agent_addr: str, planet_id: str = "", sess=Depends(session)):
    if not planet_id:
        planet_id = PlanetID.ODIN if settings.stage == "mainnet" else PlanetID.ODIN_INTERNAL
    else:
        planet_id = PlanetID(bytes(planet_id, "utf-8"))

    agent_addr = format_addr(agent_addr).lower()
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
        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
            schema = ProductSchema.model_validate(product)
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

            schema_dict[product.id] = schema

        cat_schema.product_list = list(schema_dict.values())
        category_schema_list.append(cat_schema)

    return category_schema_list


@router.get("/all", response_model=List[SimpleProductSchema])
@cache(expire=3600)
def all_product_list(sess=Depends(session)):
    return sess.scalars(select(Product)).fetchall()
