from datetime import datetime, timedelta
from typing import Optional, List, Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, Date, desc
from sqlalchemy.orm import joinedload

from common.enums import Store, ReceiptStatus
from common.models.receipt import Receipt
from common.utils.google import update_google_price
from iap import settings
from iap.dependencies import session
from iap.schemas.receipt import RefundedReceiptSchema, FullReceiptSchema

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


# @router.post("/update-price")
# def update_price(store: Store, sess=Depends(session)):
#     updated_product_count, updated_price_count = (0, 0)
#
#     if store in (Store.GOOGLE, Store.GOOGLE_TEST):
#         updated_product_count, updated_price_count = update_google_price(
#             sess, settings.GOOGLE_CREDENTIAL, settings.GOOGLE_PACKAGE_NAME
#         )
#     elif store in (Store.APPLE, Store.APPLE_TEST):
#         pass
#     elif store == Store.TEST:
#         pass
#     else:
#         raise ValueError(f"{store.name} is unsupported store.")
#
#     return f"{updated_price_count} prices in {updated_product_count} products are updated."


@router.get("/refunded", response_model=List[RefundedReceiptSchema])
def fetch_refunded(
        start: Annotated[
            Optional[int], Query(description="Where to start to find refunded receipt in unix timestamp format. "
                                             "If not provided, search starts from 24 hours ago.")
        ] = None,
        limit: Annotated[int, Query(description="Limitation of receipt in response.")] = 100,
        sess=Depends(session)):
    """
    # List refunded receipts
    ---
    
    Get list of refunded receipts. This only returns user-refunded receipts.
    """
    if not start:
        start = (datetime.utcnow() - timedelta(hours=24)).date()
    else:
        start = datetime.fromtimestamp(start)

    return sess.scalars(
        select(Receipt).where(Receipt.status == ReceiptStatus.REFUNDED_BY_BUYER)
        .where(Receipt.updated_at.cast(Date) >= start)
        .order_by(desc(Receipt.updated_at)).limit(limit)
    ).fetchall()


@router.get("/receipt", response_model=List[FullReceiptSchema])
def receipt_list(page: int = 0, pp: int = 50, sess=Depends(session)):
    return sess.scalars(
        select(Receipt).options(joinedload(Receipt.product))
        .order_by(desc(Receipt.purchased_at))
        .offset(pp * page).limit(pp)
    ).fetchall()
