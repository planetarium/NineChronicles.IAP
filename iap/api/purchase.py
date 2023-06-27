import json
import os
from typing import Tuple, List, Dict, Optional
from uuid import UUID

import boto3
import requests
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common.enums import ReceiptStatus, Store, GooglePurchaseState
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils import get_google_client
from iap import settings
from iap.dependencies import session
from iap.main import logger
from iap.schemas.receipt import ReceiptSchema, ReceiptDetailSchema, GooglePurchaseSchema

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

sqs = boto3.client("sqs", region_name=settings.REGION_NAME)
SQS_URL = os.environ.get("SQS_URL")


# TODO: validate from store
def validate_apple() -> Tuple[bool, str]:
    resp = requests.post(settings.APPLE_VALIDATION_URL, )
    return True, ""


def validate_google(sku: str, token: str, receipt: Receipt) -> Tuple[bool, str, Receipt]:
    client = get_google_client(settings.GOOGLE_CREDENTIALS)
    resp = GooglePurchaseSchema(
        **(client.purchases().products()
           .get(packageName=settings.GOOGLE_PACKAGE_NAME, product_id=sku, token=token)
           .execute())
    )
    msg = ""
    if resp.purchaseState != GooglePurchaseState.PURCHASED:
        receipt.status = ReceiptStatus.INVALID
        msg = f"Purchase state of this receipt is not valid: {resp.purchaseState.name}"
    return True, msg, receipt


@router.post("/request", response_model=ReceiptDetailSchema)
def request_product(receipt_data: ReceiptSchema, sess=Depends(session)):
    # If prev. receipt exists, check current status and returns result
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST, Store.TEST):
        data = json.loads(receipt_data.data)
        prev_receipt = sess.scalar(select(Receipt).where(Receipt.order_id == data.get('orderId')))
        if prev_receipt:
            return prev_receipt
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        pass

    # Save incoming data first
    receipt = Receipt(
        store=receipt_data.store, data=receipt_data.data,
        agent_addr=receipt_data.agentAddress,
        inventory_addr=receipt_data.inventoryAddress
    )
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    receipt.status = ReceiptStatus.VALIDATION_REQUEST
    # validate
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        data = json.loads(receipt_data.data)
        product_id = data.get("productId")
        token = data.get("purchaseToken")
        if not (product_id and token):
            receipt.status = ReceiptStatus.INVALID
            raise ValueError("Invalid Receipt: Both productId and purchaseToken must be present en receipt data")

        success, msg, receipt = validate_google(product_id, token, receipt)
        product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
            .where(Product.active.is_(True), Product.google_sku == product_id)
        )
        if not product:
            receipt.status = ReceiptStatus.INVALID
            logger.error(f"{product_id} from google store does not exist or is not active")
            raise ValueError(f"Product {product_id} does not exist or is not active.")
        receipt.product_id = product.id

    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        success, msg = validate_apple()
    elif receipt_data.store == Store.TEST:
        success, msg = True, "This is test"
    else:
        receipt.status = ReceiptStatus.UNKNOWN
        logger.error(f"[{receipt.uuid}] :: {receipt.store} is not validatable store.")
        raise ValueError(f"{receipt.store} is not validatable store.")

    if not success:
        receipt.status = ReceiptStatus.INVALID
        logger.error(f"[{receipt.uuid}] :: {msg}")
        raise ValueError(f"Receipt validation failed: {msg}")

    receipt.status = ReceiptStatus.VALID

    # TODO: check balance and inventory

    msg = {
        "inventory_addr": receipt_data.inventoryAddress,
        "product_id": product.id,
        "uuid": receipt.uuid,
    }

    try:
        resp = sqs.send_message(QueueUrl=SQS_URL, messageBody=json.dumps(msg))
    except Exception as e:
        logger.error(f"[{receipt.uuid}] :: SQS message failed: {e}")
        raise e
    else:
        logger.debug(f"message [{resp['MessageId']}] sent to SQS.")
        return receipt
    finally:
        sess.add(receipt)
        sess.commit()


@router.get("/status", response_model=Dict[UUID, Optional[ReceiptDetailSchema]])
def purchase_status(uuid_list: List[UUID] = None, sess=Depends(session)):
    """
    Get current status of receipt.
    You can provide receipt uuid or store-provided order id, but not both at the same time.

    :param uuid_list:
    :param sess:
    :return:
    """
    if uuid_list is None:
        uuid_list = []

    receipt_dict = {x.uuid: x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list))).fetchall()}
    return {x: receipt_dict.get(x, None) for x in uuid_list}
