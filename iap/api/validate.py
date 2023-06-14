import requests
from fastapi import APIRouter, Depends

from common.enums import Store
from common.models.receipt import Receipt
from iap import settings
from iap.dependencies import session
from iap.schemas.receipt import ReceiptSchema, ReceiptValidateResultSchema

router = APIRouter(
    prefix="/validate",
    tags=["Validate"],
)


def validate_apple(receipt: Receipt) -> ReceiptValidateResultSchema:
    resp = requests.post(settings.APPLE_VALIDATION_URL, json={"receipt-data": receipt.receipt_data})
    result = ReceiptValidateResultSchema()
    if resp.status_code != 200:
        result.store = receipt.store
        result.id = receipt.receipt_id
        result.valid = False

    return result


def validate_google(receipt: Receipt) -> ReceiptValidateResultSchema:
    # TODO: Set mobile app, IAP developer API credentials
    #  Create test item
    #  Buy test item
    #  Validate
    return ReceiptValidateResultSchema(store=receipt.store, valid=True, id=receipt.receipt_id)


@router.post("", response_model=ReceiptValidateResultSchema)
def validate_recipe(receipt: ReceiptSchema, sess=Depends(session)):
    """
    Validate In-app purchase receipt
    """
    receipt_data = sess.query(Receipt).filter_by(id=receipt.id).first()
    if not receipt_data:
        receipt_data = Receipt(store=receipt.store, receipt_id=receipt.id, receipt_data=receipt.data)

    # Validate to store
    match receipt.store:
        case Store.GOOGLE | Store.GOOGLE_TEST:
            resp = validate_google(receipt_data)
        case Store.APPLE | Store.APPLE_TEST:
            resp = validate_apple(receipt_data.receipt_data)
        case Store.TEST | _:
            resp = requests.Response()
            resp.status_code = 200

    if resp.status_code != 200:
        return ReceiptValidateResultSchema(
            store=receipt.store,
            id=receipt.id,
            valid=False,
        )

    # Create message and send to Queue

    #
