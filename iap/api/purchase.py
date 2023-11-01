import json
import os
from typing import Tuple, List, Dict, Optional, Annotated
from uuid import UUID

import boto3
import jwt
import requests
from fastapi import APIRouter, Depends, Query
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common.enums import ReceiptStatus, Store, GooglePurchaseState
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.apple import get_jwt
from common.utils.google import get_google_client
from iap import settings
from iap.dependencies import session
from iap.main import logger
from iap.schemas.receipt import ReceiptSchema, ReceiptDetailSchema, GooglePurchaseSchema, ApplePurchaseSchema
from iap.utils import get_purchase_count
from iap.validator.common import get_order_data

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

sqs = boto3.client("sqs", region_name=settings.REGION_NAME)
SQS_URL = os.environ.get("SQS_URL")


def validate_apple(tx_id: str) -> Tuple[bool, str, Optional[ApplePurchaseSchema]]:
    headers = {
        "Authorization": f"Bearer {get_jwt(settings.APPLE_CREDENTIAL, settings.APPLE_BUNDLE_ID, settings.APPLE_KEY_ID, settings.APPLE_ISSUER_ID)}"
    }
    resp = requests.get(settings.APPLE_VALIDATION_URL.format(transactionId=tx_id), headers=headers)
    if resp.status_code != 200:
        return False, f"Purchase state of this receipt is not valid: {resp.text}", None
    try:
        data = jwt.decode(resp.json()["signedTransactionInfo"], options={"verify_signature": False})
        logger.debug(data)
        schema = ApplePurchaseSchema(**data)
    except:
        return False, f"Malformed apple transaction data for {tx_id}", None
    else:
        return True, "", schema


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
    - `agentAddress` :: str : 9c agent address who bought product on store.
    - `avatarAddress` :: str : 9c avatar address to get items in bought product.
    - `data` :: str : JSON serialized string of details of receipt.

        For `TEST` type store, the `data` should have following fields:
            - `productId` :: int : IAP service managed product ID.
            - `orderId` :: str : Unique order ID of this purchase. Sending random UUID string is good.
            - `purchaseTime` :: int : Purchase timestamp in unix timestamp format. Note that not in millisecond, just second.

        For `APPLE`-ish type store, the `data` must have following fields:
            - `Payload` :: str : Encoded full receipt payload data.
            - `Store` :: str : Store name. Should be `AppleAppStore`.
            - `TransactionID` :: str : Apple IAP transaction ID formed like `2000000432373050`.
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
        product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
            .where(Product.active.is_(True), Product.google_sku == product_id)
        )
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        # NOTE: We can get productId after validation in apple.
        #  So validate this later in apple.
        # product = sess.scalar(
        #     select(Product)
        #     .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        #     .where(Product.active.is_(True), Product.apple_sku == product_id)
        # )
        pass
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
        planet_id=receipt_data.planetId.value,
    )
    sess.add(receipt)
    sess.flush()
    sess.refresh(receipt)

    if receipt_data.store not in (Store.APPLE, Store.APPLE_TEST) and not product:
        receipt.status = ReceiptStatus.INVALID
        raise_error(sess, receipt,
                    ValueError(f"{product_id} is not valid product ID for {receipt_data.store.name} store."))

    receipt.status = ReceiptStatus.VALIDATION_REQUEST

    # validate
    ## Google
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        token = receipt_data.order.get("purchaseToken")
        if not (product_id and token):
            receipt.status = ReceiptStatus.INVALID
            raise_error(sess, receipt,
                        ValueError("Invalid Receipt: Both productId and purchaseToken must be present en receipt data"))

        success, msg, purchase = validate_google(product_id, token)
        # FIXME: google API result may not include productId.
        #  Can we get productId allways?
        # if purchase.productId != product.google_sku:
        #     receipt.status = ReceiptStatus.INVALID
        #     raise_error(sess, receipt, ValueError(
        #         f"Invalid Product ID: Given {product.google_sku} is not identical to found from receipt: {purchase.productId}"))
        # NOTE: Consume can be executed only by purchase owner.
        # consume_google(product_id, token)
    ## Apple
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        success, msg, purchase = validate_apple(order_id)
        if success:
            data = receipt_data.data.copy()
            data.update(**purchase.json_data)
            receipt.data = data
            receipt.purchased_at = purchase.originalPurchaseDate
            # Get product from validation result and check product existence.
            product = sess.scalar(
                select(Product)
                .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
                .where(Product.active.is_(True), Product.apple_sku == purchase.productId)
            )
        if not product:
            receipt.status = ReceiptStatus.INVALID
            raise_error(sess, receipt,
                        ValueError(f"{purchase.productId} is not valid product ID for {receipt_data.store.name} store."))
    ## Test
    elif receipt_data.store == Store.TEST:
        success, msg = True, "This is test"
    ## INVALID
    else:
        receipt.status = ReceiptStatus.UNKNOWN
        success, msg = False, f"{receipt.store} is not validatable store."

    if not success:
        receipt.status = ReceiptStatus.INVALID
        raise_error(sess, receipt, ValueError(f"Receipt validation failed: {msg}"))

    receipt.status = ReceiptStatus.VALID

    # Check purchase limit
    if (product.daily_limit and
            get_purchase_count(sess, receipt.agent_addr, product.id, hour_limit=24) > product.daily_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Daily purchase limit exceeded."))
    elif (product.weekly_limit and
          get_purchase_count(sess, receipt.agent_addr, product.id, hour_limit=24 * 7) > product.weekly_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Weekly purchase limit exceeded."))
    elif (product.account_limit and
          get_purchase_count(sess, receipt.agent_addr, product.id) > product.account_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Account purchase limit exceeded."))

    msg = {
        "agent_addr": receipt_data.agentAddress,
        "avatar_addr": receipt_data.avatarAddress,
        "product_id": product.id,
        "uuid": str(receipt.uuid),
        "planet_id": receipt_data.planetId.decode('utf-8'),
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
