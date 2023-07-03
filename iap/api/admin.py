from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends
from sqlalchemy import select, Date, desc

from common.enums import Store, ReceiptStatus
from common.models.receipt import Receipt
from common.utils import update_google_price
from iap import settings
from iap.dependencies import session
from iap.schemas.receipt import RefundedReceiptSchema

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


@router.post("/update-price")
def update_price(store: Store, sess=Depends(session)):
    updated_product_count, updated_price_count = (0, 0)
    print(settings.GOOGLE_CREDENTIALS)

    if store in (Store.GOOGLE, Store.GOOGLE_TEST):
        updated_product_count, updated_price_count = update_google_price(
            sess, settings.GOOGLE_CREDENTIALS, settings.GOOGLE_PACKAGE_NAME
        )
    elif store in (Store.APPLE, Store.APPLE_TEST):
        pass
    elif store == Store.TEST:
        pass
    else:
        raise ValueError(f"{store.name} is unsupported store.")

    return f"{updated_price_count} prices in {updated_product_count} products are updated."


@router.get("/refunded", response_model=List[RefundedReceiptSchema])
def fetch_refunded(start: Optional[int] = None, limit: int = 100, sess=Depends(session)):
    if not start:
        start = (datetime.utcnow() - timedelta(days=1)).date()
    else:
        start = datetime.fromtimestamp(start)

    return sess.scalars(
        select(Receipt).where(Receipt.status == ReceiptStatus.REFUNDED_BY_BUYER)
        .where(Receipt.updated_at.cast(Date) >= start)
        .order_by(desc(Receipt.updated_at)).limit(limit)
    ).fetchall()
