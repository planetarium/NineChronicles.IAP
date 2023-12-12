from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import joinedload

from common.models.product import Product, Category
from common.utils.address import format_addr
from common.utils.receipt import PlanetID
from iap import settings
from iap.dependencies import session
from iap.schemas.product import CategorySchema, ProductSchema
from iap.utils import get_purchase_count

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[CategorySchema])
def product_list(agent_addr: str,
                 planet_id: str = "",
                 sess=Depends(session)):
    if not planet_id:
        planet_id = PlanetID.ODIN if settings.stage == "mainnet" else PlanetID.ODIN_INTERNAL
    else:
        planet_id = PlanetID(bytes(planet_id, "utf-8"))

    agent_addr = format_addr(agent_addr).lower()
    # FIXME: Optimize query
    all_category_list = (
        sess.query(Category).options(joinedload(Category.product_list))
        .join(Product.fav_list)
        .join(Product.fungible_item_list)
        .filter(Category.active.is_(True)).filter(Product.active.is_(True))
        .order_by(Category.order, Product.order)
    ).all()

    category_schema_list = []
    for category in all_category_list:
        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
            # Skip non-active products
            if ((product.open_timestamp and product.open_timestamp > datetime.now()) or
                    (product.close_timestamp and product.close_timestamp <= datetime.now())):
                continue

            # Check purchase history
            schema = ProductSchema.model_validate(product)
            if product.daily_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr, daily_limit=True
                )
                schema.buyable = schema.purchase_count < product.daily_limit
            elif product.weekly_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr, weekly_limit=True
                )
                schema.buyable = schema.purchase_count < product.weekly_limit
            elif product.account_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr
                )
                schema.buyable = schema.purchase_count < product.account_limit
            else:  # Product with no limitation
                schema.buyable = True

            schema_dict[product.id] = schema

        cat_schema.product_list = list(schema_dict.values())
        category_schema_list.append(cat_schema)

    return category_schema_list
