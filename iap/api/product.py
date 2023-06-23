from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import joinedload

from common.models.product import Product
from iap.dependencies import session
from iap.schemas.product import ProductSchema
from iap.utils import get_purchase_count

router = APIRouter(
    prefix="/product",
    tags=["Product"],
)


@router.get("", response_model=List[ProductSchema])
def product_list(agent_addr: str, sess=Depends(session)):
    all_product_list = (
        sess.query(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.item_list))
        .filter_by(active=True)
        .order_by(Product.display_order)
    ).all()
    for product in all_product_list:
        # TODO: Check balance

        # Check purchase history
        if product.daily_limit:
            product.active = get_purchase_count(sess, agent_addr, product.id, hour_limit=24) < product.daily_limit
        elif product.weekly_limit:
            product.active = get_purchase_count(sess, agent_addr, product.id, hour_limit=24 * 7) < product.weekly_limit

    return all_product_list
