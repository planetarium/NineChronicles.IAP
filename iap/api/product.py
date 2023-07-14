from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload, contains_eager

from common.models.product import Product, Price
from iap.dependencies import session
from iap.schemas.product import ProductSchema
from iap.utils import get_purchase_count

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[ProductSchema])
def product_list(agent_addr: str, sess=Depends(session)):
    all_product_list = sess.execute(
        select(Product).filter_by(active=True)
        .join(Product.price_list).where(Price.active.is_(True))
        .options(contains_eager(Product.price_list))
        .options(joinedload(Product.fav_list))
        .options(joinedload(Product.fungible_item_list))
        .order_by(Product.display_order)
    ).unique().scalars().all()

    # TODO: Change query to dict and compare balance and requirement
    # garage = get_iap_garage(sess)
    # FIXME: This is sample data
    garage = {
        "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe": 100,
        "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a": 1000,
    }

    schema_dict = {x.id: ProductSchema.from_orm(x) for x in all_product_list}

    for product in all_product_list:
        # Check fungible item stock in garage
        for item in product.fungible_item_list:
            if garage[item.fungible_item_id] < item.amount:
                schema_dict[product.id].buyable = False
                break

        # Check purchase history
        schema = schema_dict[product.id]
        if product.daily_limit:
            schema.purchase_count = get_purchase_count(sess, agent_addr, product.id, hour_limit=24)
            schema.buyable = schema.purchase_count < product.daily_limit
        elif product.weekly_limit:
            schema.purchase_count = get_purchase_count(sess, agent_addr, product.id, hour_limit=24 * 7)
            schema.buyable = schema.purchase_count < product.weekly_limit

    return list(schema_dict.values())
