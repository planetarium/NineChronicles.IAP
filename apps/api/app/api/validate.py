import requests
from fastapi import APIRouter, Depends
from sqlalchemy import select
from shared.enums import Store
from shared.models.receipt import Receipt
from shared.models.product import Product, Price
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
    # Product must be found for price validation
    product = sess.scalar(
        select(Product)
        .where(Product.active.is_(True), Product.id == receipt.data.get("productId"))
    )
    if not product:
        return ReceiptDetailSchema(
            store=receipt.store,
            valid=False,
            id=receipt.order_id,
            msg=f"Product not found: {receipt.data.get('productId')}"
        )

    # 상품 가격 조회 (스토어 타입 무시하고 첫 번째 가격 사용)
    price = sess.scalar(
        select(Price)
        .where(Price.product_id == product.id)
        .limit(1)
    )
    if not price:
        return ReceiptDetailSchema(
            store=receipt.store,
            valid=False,
            id=receipt.order_id,
            msg=f"Price not found for product {product.id}"
        )

    stripe_key = (
        config.stripe_test_secret_key
        if receipt.store == Store.WEB_TEST
        else config.stripe_secret_key
    )

    success, msg, purchase = validate_web(
        stripe_secret_key=stripe_key,
        stripe_api_version=config.stripe_api_version,
        payment_intent_id=receipt.order_id,
        expected_product_id=int(receipt.data.get("productId")),  # int로 변환
        expected_amount=float(price.price),  # Decimal을 float로 변환
        db_product=product
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
