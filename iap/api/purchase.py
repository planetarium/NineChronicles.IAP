import json
import os
from typing import Tuple

import boto3
import requests
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common.enums import ReceiptStatus, Store
from common.models.product import Product
from common.models.receipt import Receipt
from iap import settings
from iap.dependencies import session
from iap.main import logger
from iap.schemas.receipt import PurchaseProcessResultSchema, ReceiptSchema

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


def validate_google() -> Tuple[bool, str]:
    return True, ""


@router.post("/request", response_model=PurchaseProcessResultSchema)
def request_product(receipt: ReceiptSchema, sess=Depends(session)):
    # TODO: Find prev. receipt if duplicated requests come in
    ## If prev. receipt exists, check current status and returns result

    # Save incoming data first
    receipt = Receipt(store=receipt.store, data=receipt.data, inventoryAddress=receipt.inventoryAddress)
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    receipt.status = ReceiptStatus.VALIDATION_REQUEST
    # validate
    if receipt.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        success, msg = validate_google()
    elif receipt.store in (Store.APPLE, Store.APPLE_TEST):
        success, msg = validate_apple()
    elif receipt.store == Store.TEST:
        success, msg = True, "This is test"
    else:
        receipt.status = ReceiptStatus.UNKNOWN
        logger.error(f"[{receipt.uuid}] :: {receipt.store} is not validatable store.")
        raise ValueError(f"{receipt.store} is not validatable store.")

    if not success:
        receipt.status = ReceiptStatus.INVALID
        logger.error(f"[{receipt.uuid}] :: {msg}")
        raise ValueError(f"Receipt validation Failed:{msg}")

    # TODO: Find fav and item list based on purchased product
    target_product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.item_list))
        # FIXME: Change condition using SKU
        .where(Product.id == 1)
    )

    # TODO: check balance and inventory

    msg = {
        "inventory_addr": receipt.inventoryAddress,
        "product_id": target_product.id,
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
