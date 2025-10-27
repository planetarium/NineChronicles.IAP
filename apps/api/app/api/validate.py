import requests
from fastapi import APIRouter, Depends
from shared.enums import Store
from shared.models.receipt import Receipt
from shared.schemas.receipt import ReceiptDetailSchema, ReceiptSchema
from shared.validator.web import validate_web, validate_web_test

from app.config import config
from app.dependencies import session

router = APIRouter(
    prefix="/validate",
    tags=["Validate"],
)


def validate_apple(receipt: Receipt) -> ReceiptDetailSchema:
    resp = requests.post(config.apple_validation_url, json={"receipt-data": receipt.receipt_data})
    result = ReceiptDetailSchema()
    if resp.status_code != 200:
        result.store = receipt.store
        result.id = receipt.receipt_id
        result.valid = False

    return result


def validate_google(receipt: Receipt) -> ReceiptDetailSchema:
    # TODO: Set mobile app, IAP developer API credentials
    #  Create test item
    #  Buy test item
    #  Validate
    return ReceiptDetailSchema(store=receipt.store, valid=True, id=receipt.receipt_id)


def validate_web_payment(receipt: Receipt) -> ReceiptDetailSchema:
    # Web payment validation through external API
    if receipt.store == Store.WEB:
        success, msg, purchase = validate_web(
            config.web_payment_api_url,
            config.web_payment_credential,
            receipt.order_id,
            receipt.data.get("productId"),
            receipt.data
        )
    else:  # Store.WEB_TEST
        success, msg, purchase = validate_web_test(
            receipt.order_id,
            receipt.data.get("productId"),
            receipt.data
        )

    return ReceiptDetailSchema(
        store=receipt.store,
        valid=success,
        id=receipt.order_id,
        msg=msg if not success else None
    )


@router.post("", response_model=ReceiptDetailSchema)
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
        case Store.WEB | Store.WEB_TEST:
            resp = validate_web_payment(receipt_data)
        case Store.TEST | _:
            resp = requests.Response()
            resp.status_code = 200

    if resp.status_code != 200:
        return ReceiptDetailSchema(
            store=receipt.store,
            id=receipt.id,
            valid=False,
        )

    # Create message and send to Queue

    #
