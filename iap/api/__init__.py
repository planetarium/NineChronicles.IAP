from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from common import logger
from common.models.receipt import Receipt
from common.models.voucher import VoucherRequest
from iap.api import history, purchase, product, admin, l10n
from iap.dependencies import session

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    history,
    purchase,
    product,
    l10n,
    admin,
]


@router.get("/receipt-voucher")
def receipt_voucher_count(sess: Session = Depends(session)):
    receipt_id_list = sess.scalars(select(Receipt.id).where(
        Receipt.created_at >= datetime(2023, 12, 13, tzinfo=timezone.utc),
        Receipt.created_at <= datetime.now(tz=timezone.utc) - timedelta(minutes=3),
    )).fetchall()
    voucher_list = sess.scalars(select(VoucherRequest)).fetchall()
    missing_receipt = set(receipt_id_list) - set([x.receipt_id for x in voucher_list])

    if missing_receipt:
        logger.error(missing_receipt)
        return JSONResponse(status_code=503, content=f"{len(missing_receipt)} receipt does not have voucher!")

    failed_voucher_list = [x.uuid for x in voucher_list if x.status != 200]
    if failed_voucher_list:
        logger.error(failed_voucher_list)
        return JSONResponse(status_code=500, content=f"{len(failed_voucher_list)} voucher not success.")

    return JSONResponse(status_code=200, content="All receipt has own voucher")


for view in __all__:
    router.include_router(view.router)
