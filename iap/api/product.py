from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload, contains_eager

from common.models.product import Product, Price
from common.utils import format_addr
from iap.dependencies import session
from iap.schemas.product import ProductSchema
from iap.utils import get_purchase_count, get_iap_garage

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[ProductSchema])
def product_list(agent_addr: str, sess=Depends(session)):
    agent_addr = format_addr(agent_addr)
    all_product_list = sess.execute(
        select(Product).filter_by(active=True)
        .join(Product.price_list).where(Price.active.is_(True))
        .options(contains_eager(Product.price_list))
        .options(joinedload(Product.fav_list))
        .options(joinedload(Product.fungible_item_list))
        .order_by(Product.display_order)
    ).unique().scalars().all()

    garage = {x["fungibleItemId"]: x["count"] if x["count"] is not None else 0
              for x in get_iap_garage(sess)}

    schema_dict = {x.id: ProductSchema.from_orm(x) for x in all_product_list}

    for product in all_product_list:
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
            schema.purchase_count = get_purchase_count(sess, agent_addr, product.id, hour_limit=24)
            schema.buyable = schema.purchase_count < product.daily_limit
        elif product.weekly_limit:
            schema.purchase_count = get_purchase_count(sess, agent_addr, product.id, hour_limit=24 * 7)
            schema.buyable = schema.purchase_count < product.weekly_limit

    return list(schema_dict.values())
