from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import joinedload

from common.models.product import Product, Category
from common.utils.address import format_addr
from common.utils.garage import get_iap_garage
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

    iap_garage = {x.fungible_id: x.amount for x in get_iap_garage(sess)}
    garage = {}
    for category in all_category_list:
        if ((category.open_timestamp and category.open_timestamp > datetime.now()) or
                (category.close_timestamp and category.close_timestamp <= datetime.now())):
            continue

        for product in category.product_list:
            if ((product.open_timestamp and product.open_timestamp > datetime.now()) or
                    (product.close_timestamp and product.close_timestamp <= datetime.now())):
                continue

            for fungible_item in product.fungible_item_list:
                garage[fungible_item.fungible_item_id] = iap_garage.get(fungible_item.fungible_item_id, 0)

    category_schema_list = []
    for category in all_category_list:
        cat_schema = CategorySchema.model_validate(category)
        schema_dict = {}
        for product in category.product_list:
            schema_dict[product.id] = ProductSchema.model_validate(product)
            # FIXME: Pinpoint get product buyability
            product_buyable = True
            # Check fungible item stock in garage
            for item in product.fungible_item_list:
                if garage[item.fungible_item_id] < item.amount:
                    schema_dict[product.id].buyable = False
                    product_buyable = False
                    break
            if not product_buyable:
                continue

            # Check purchase history
            schema = schema_dict[product.id]
            if product.daily_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr, hour_limit=24
                )
                schema.buyable = schema.purchase_count < product.daily_limit
            elif product.weekly_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr, hour_limit=24 * 7
                )
                schema.buyable = schema.purchase_count < product.weekly_limit
            elif product.account_limit:
                schema.purchase_count = get_purchase_count(
                    sess, product.id, planet_id=planet_id, agent_addr=agent_addr
                )
                schema.buyable = schema.purchase_count < product.account_limit
        cat_schema.product_list = list(schema_dict.values())
        category_schema_list.append(cat_schema)

    return category_schema_list
