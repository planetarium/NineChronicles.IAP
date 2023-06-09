import json
import os
from typing import Tuple, List, Dict, Optional, Annotated
from uuid import UUID

import boto3
import requests
from fastapi import APIRouter, Depends, Query
from googleapiclient.errors import HttpError
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
from iap.validator.common import get_order_data

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


def validate_google(sku: str, token: str) -> Tuple[bool, str, GooglePurchaseSchema]:
    client = get_google_client(settings.GOOGLE_CREDENTIAL)
    resp = GooglePurchaseSchema(
        **(client.purchases().products()
           .get(packageName=settings.GOOGLE_PACKAGE_NAME, productId=sku, token=token)
           .execute())
    )
    msg = ""
    if resp.purchaseState != GooglePurchaseState.PURCHASED:
        return False, f"Purchase state of this receipt is not valid: {resp.purchaseState.name}", resp
    return True, msg, resp


def consume_google(sku: str, token: str):
    client = get_google_client(settings.GOOGLE_CREDENTIAL)
    try:
        resp = client.purchases().products().consume(
            packageName=settings.GOOGLE_PACKAGE_NAME, productId=sku, token=token
        )
        logger.debug(resp)
    except HttpError as e:
        logger.error(e)
        raise e


def raise_error(sess, receipt: Receipt, e: Exception):
    sess.add(receipt)
    sess.commit()
    logger.error(f"[{receipt.uuid}] :: {e}")
    raise e


@router.post("/request", response_model=ReceiptDetailSchema)
def request_product(receipt_data: ReceiptSchema, sess=Depends(session)):
    """
    # Purchase Request
    ---

    **Request receipt validation and unload product from IAP garage to buyer.**

    ### Request Body
    - `store` :: int : Store type in IntEnum Please see StoreType Enum.
    - `data` :: str : JSON serialized string of full details of receipt.
        For `TEST` type store, the `data` should have following fields:
        - `productId` :: int : IAP service managed product id.
        - `orderId` :: str : Unique order ID of this purchase. Sending random UUID string is good.
        - `purchaseTime` :: int : Purchase timestamp in unix timestamp format. Note that not in millisecond, just second.
    - `agentAddress` :: str : 9c agent address who bought product on store.
    - `avatarAddress` :: str : 9c avatar address to get items in bought product.
    """
    order_id, product_id, purchased_at = get_order_data(receipt_data)
    prev_receipt = sess.scalar(
        select(Receipt).where(Receipt.store == receipt_data.store, Receipt.order_id == order_id)
    )
    if prev_receipt:
        logger.debug(f"prev. receipt exists: {prev_receipt.uuid}")
        return prev_receipt

    product = None
    # If prev. receipt exists, check current status and returns result
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        # Test based on google for soft launch v1
        product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
            .where(Product.active.is_(True), Product.google_sku == product_id)
        )
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        # FIXME: Get real product when you support apple
        #  This is just to avoid error
        product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
            .where(Product.active.is_(True), Product.id == product_id)
        )
    elif receipt_data.store == Store.TEST:
        product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
            .where(Product.active.is_(True), Product.id == product_id)
        )

    # Save incoming data first
    receipt = Receipt(
        store=receipt_data.store,
        data=receipt_data.data,
        agent_addr=receipt_data.agentAddress,
        avatar_addr=receipt_data.avatarAddress,
        order_id=order_id,
        purchased_at=purchased_at,
        product_id=product.id if product is not None else None,
    )
    sess.add(receipt)
    sess.flush()
    sess.refresh(receipt)

    if not product:
        receipt.status = ReceiptStatus.INVALID
        raise_error(sess, receipt,
                    ValueError(f"{product_id} is not valid product ID for {receipt_data.store.name} store."))

    receipt.status = ReceiptStatus.VALIDATION_REQUEST

    # validate
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        token = receipt_data.order.get("purchaseToken")
        if not (product_id and token):
            receipt.status = ReceiptStatus.INVALID
            raise_error(sess, receipt,
                        ValueError("Invalid Receipt: Both productId and purchaseToken must be present en receipt data"))

        success, msg, purchase = validate_google(product_id, token)
        consume_google(product_id, token)

    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        # TODO: Support Apple
        success, msg = validate_apple()
    elif receipt_data.store == Store.TEST:
        success, msg = True, "This is test"
    else:
        receipt.status = ReceiptStatus.UNKNOWN
        success, msg = False, f"{receipt.store} is not validatable store."

    if not success:
        receipt.status = ReceiptStatus.INVALID
        raise_error(sess, receipt, ValueError(f"Receipt validation failed: {msg}"))

    receipt.status = ReceiptStatus.VALID

    # TODO: check balance and inventory

    msg = {
        "agent_addr": receipt_data.agentAddress,
        "avatar_addr": receipt_data.avatarAddress,
        "product_id": product.id,
        "uuid": str(receipt.uuid),
    }

    resp = sqs.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(msg))
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)
    logger.debug(f"message [{resp['MessageId']}] sent to SQS.")
    return receipt


@router.get("/status", response_model=Dict[UUID, Optional[ReceiptDetailSchema]])
def purchase_status(uuid: Annotated[List[UUID], Query()] = ..., sess=Depends(session)):
    """
    Get current status of receipt.  
    You can validate multiple UUIDs at once.

    **NOTE**  
    For the non-existing UUID, response body of that UUID would be `null`. Please be aware client must handle `null`.
    """
    receipt_dict = {x.uuid: x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid))).fetchall()}
    return {x: receipt_dict.get(x, None) for x in uuid}
