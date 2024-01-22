import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional, Annotated
from uuid import UUID, uuid4

import boto3
import requests
from fastapi import APIRouter, Depends, Query
from googleapiclient.errors import HttpError
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload
from starlette.responses import JSONResponse

from common.enums import ReceiptStatus, Store
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.aws import fetch_parameter
from common.utils.google import get_google_client
from common.utils.receipt import PlanetID
from iap import settings
from iap.dependencies import session
from iap.exceptions import ReceiptNotFoundException
from iap.main import logger
from iap.schemas.receipt import ReceiptSchema, ReceiptDetailSchema, FreeReceiptSchema
from iap.utils import create_season_pass_jwt, get_purchase_count
from iap.validator.apple import validate_apple
from iap.validator.common import get_order_data
from iap.validator.google import validate_google

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

sqs = boto3.client("sqs", region_name=settings.REGION_NAME)
SQS_URL = os.environ.get("SQS_URL")
VOUCHER_SQS_URL = os.environ.get("VOUCHER_SQS_URL")


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


@router.get("/log")
def log_request_product(planet_id: str, agent_address: str, avatar_address: str, product_id: str,
                        order_id: Optional[str] = "", data: Optional[str] = ""):
    """
    # Purchase log
    ---
    
    Logs purchase request data
    """
    logger.info(f"[PURCHASE_LOG] {planet_id} :: {agent_address} :: {avatar_address} :: {product_id} :: {order_id}")
    if data:
        logger.info(data)
    return JSONResponse(status_code=200, content=f"Order {order_id} for product {product_id} logged.")


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
    if not receipt_data.planetId:
        receipt_data.planetId = PlanetID.ODIN if settings.stage == "mainnet" else PlanetID.ODIN_INTERNAL

    order_id, product_id, purchased_at = get_order_data(receipt_data)
    prev_receipt = sess.scalar(
        select(Receipt).where(Receipt.store == receipt_data.store, Receipt.order_id == order_id)
    )
    if prev_receipt:
        logger.debug(f"prev. receipt exists: {prev_receipt.uuid}")
        return prev_receipt

    if not receipt_data.agentAddress:
        raise ReceiptNotFoundException("", order_id)

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
        agent_addr=receipt_data.agentAddress.lower(),
        avatar_addr=receipt_data.avatarAddress.lower(),
        order_id=order_id,
        purchased_at=purchased_at,
        product_id=product.id if product is not None else None,
        planet_id=receipt_data.planetId.value,
    )
    sess.add(receipt)
    sess.commit()
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

        success, msg, purchase = validate_google(order_id, product_id, token)
        # FIXME: google API result may not include productId.
        #  Can we get productId always?
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
                        ValueError(
                            f"{purchase.productId} is not valid product ID for {receipt_data.store.name} store."))
        receipt.product_id = product.id
    ## Test
    elif receipt_data.store == Store.TEST:
        if os.environ.get("STAGE") == "mainnet":
            success, msg = False, f"{receipt.store} is not allowed."
        else:
            success, msg = True, "This is test"
    ## INVALID
    else:
        receipt.status = ReceiptStatus.UNKNOWN
        success, msg = False, f"{receipt.store} is not validatable store."

    if not success:
        receipt.msg = msg
        receipt.status = ReceiptStatus.INVALID
        raise_error(sess, receipt, ValueError(f"Receipt validation failed: {msg}"))

    receipt.status = ReceiptStatus.VALID
    logger.info(f"Send voucher request: {receipt.uuid}")
    resp = sqs.send_message(QueueUrl=VOUCHER_SQS_URL,
                            MessageBody=json.dumps({
                                "receipt_id": receipt.id,
                                "uuid": str(receipt.uuid),
                                "product_id": receipt.product_id,
                                "product_name": receipt.product.name,
                                "agent_addr": receipt.agent_addr,
                                "avatar_addr": receipt.avatar_addr,
                                "planet_id": receipt_data.planetId.decode(),
                            }))
    logger.info(f"Voucher message: {resp['MessageId']}")

    now = datetime.now()
    if ((product.open_timestamp and product.open_timestamp > now) or
            (product.close_timestamp and product.close_timestamp < datetime.now())):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    # Check purchase limit
    # FIXME: Can we get season pass product without magic string?
    if "SeasonPass" in product.name:
        # NOTE: Check purchase limit using avatar_addr, not agent_addr
        if (product.account_limit and
                get_purchase_count(sess, product.id, planet_id=receipt_data.planetId,
                                   avatar_addr=receipt.avatar_addr.lower()) > product.account_limit):
            receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
            raise_error(sess, receipt, ValueError("Account purchase limit exceeded."))

        prefix, body = product.google_sku.split("seasonpass")
        try:
            season = int(body[-1])
        except:
            season = 0
        season_pass_host = fetch_parameter(
            settings.REGION_NAME,
            f"{os.environ.get('STAGE')}_9c_SEASON_PASS_HOST", False
        )["Value"]
        claim_list = [{"ticker": x.fungible_item_id, "amount": x.amount, "decimal_places": 0}
                      for x in product.fungible_item_list]
        claim_list.extend([{"ticker": x.ticker, "amount": x.amount, "decimal_places": x.decimal_places}
                           for x in product.fav_list])
        resp = requests.post(f"{season_pass_host}/api/user/upgrade",
                             json={
                                 "planet_id": receipt_data.planetId.value.decode("utf-8"),
                                 "agent_addr": receipt.agent_addr.lower(),
                                 "avatar_addr": receipt.avatar_addr.lower(),
                                 "season_id": int(season),
                                 "is_premium": True if (not body[:-1] or "all" in body) else False,
                                 "is_premium_plus": "plus" in body or "all" in body,
                                 "g_sku": product.google_sku, "a_sku": product.apple_sku,
                                 # SeasonPass only uses claims
                                 "reward_list": claim_list,
                             },
                             headers={"Authorization": f"Bearer {create_season_pass_jwt()}"})
        if resp.status_code != 200:
            receipt.msg = f"{resp.status_code} :: {resp.text}"
            msg = f"SeasonPass Upgrade Failed: {resp.text}"
            logging.error(msg)
            raise_error(sess, receipt, Exception(msg))
    else:
        if (product.daily_limit and
                get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                                   agent_addr=receipt.agent_addr.lower(), daily_limit=True) > product.daily_limit):
            receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
            raise_error(sess, receipt, ValueError("Daily purchase limit exceeded."))
        elif (product.weekly_limit and
              get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                                 agent_addr=receipt.agent_addr.lower(), weekly_limit=True) > product.weekly_limit):
            receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
            raise_error(sess, receipt, ValueError("Weekly purchase limit exceeded."))
        elif (product.account_limit and
              get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                                 agent_addr=receipt.agent_addr.lower()) > product.account_limit):
            receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
            raise_error(sess, receipt, ValueError("Account purchase limit exceeded."))

        msg = {
            "agent_addr": receipt_data.agentAddress.lower(),
            "avatar_addr": receipt_data.avatarAddress.lower(),
            "product_id": product.id,
            "uuid": str(receipt.uuid),
            "planet_id": receipt_data.planetId.decode('utf-8'),
        }

        resp = sqs.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(msg))
        logger.debug(f"message [{resp['MessageId']}] sent to SQS.")

    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    return receipt


@router.post("/free", response_model=ReceiptDetailSchema)
def free_product(receipt_data: FreeReceiptSchema, sess=Depends(session)):
    """
    # Purchase Free Product
    ---

    **Purchase free product and unload product from IAP garage to buyer.**

    ### Request Body
    - `store` :: int : Store type in IntEnum. Please see `StoreType` Enum.
    - `agentAddress` :: str : 9c agent address of buyer.
    - `avatarAddress` :: str : 9c avatar address to get items.
    - `sku` :: str : Purchased product SKU
    """
    if not receipt_data.planetId:
        raise ReceiptNotFoundException("", "")

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        .where(
            Product.active.is_(True),
            or_(Product.google_sku == receipt_data.sku, Product.apple_sku == receipt_data.sku)
        )
    )
    order_id = f"FREE-{uuid4()}"
    receipt = Receipt(
        store=receipt_data.store,
        data={"SKU": receipt_data.sku, "OrderId": order_id},
        agent_addr=receipt_data.agentAddress.lower(),
        avatar_addr=receipt_data.avatarAddress.lower(),
        order_id=order_id,
        purchased_at=datetime.utcnow(),
        product_id=product.id if product is not None else None,
        planet_id=receipt_data.planetId.value,
    )
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    # Validation
    if not product:
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = f"Product {receipt_data.product_id} not exists or inactive"
        raise_error(sess, receipt, ValueError(f"Product {receipt_data.product_id} not found or inactive"))

    if not product.is_free:
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = "This product it not for free"
        raise_error(sess, receipt, ValueError(f"Requested product {product.id}::{product.name} is not for free"))

    if ((product.open_timestamp and product.open_timestamp > datetime.now()) or
            (product.close_timestamp and product.close_timestamp < datetime.now())):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    # Purchase Limit
    if (product.daily_limit and
            get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                               agent_addr=receipt.agent_addr.lower(), daily_limit=True) > product.daily_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Daily purchase limit exceeded."))
    elif (product.weekly_limit and
          get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                             agent_addr=receipt.agent_addr.lower(), weekly_limit=True) > product.weekly_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Weekly purchase limit exceeded."))
    elif (product.account_limit and
          get_purchase_count(sess, product.id, planet_id=PlanetID(receipt.planet_id),
                             agent_addr=receipt.agent_addr.lower()) > product.account_limit):
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError("Account purchase limit exceeded."))

    # Required level
    if product.required_level:
        query = f"""{{ stateQuery {{ avatar (avatarAddress: "{receipt_data.avatarAddress}") {{ level}} }} }}"""
        try:
            resp = requests.post(os.environ.get("HEADLESS"), json={"query": query}, timeout=1)
            avatar_level = resp.json()["data"]["stateQuery"]["avatar"]["level"]
        except:
            # Whether request is failed or no fitted data found
            avatar_level = 0

        if avatar_level < product.required_level:
            receipt.status = ReceiptStatus.REQUIRED_LEVEL
            raise_error(sess, receipt,
                        ValueError(f"Avatar level {avatar_level} does not met required level {product.required_level}"))

    receipt.status = ReceiptStatus.VALID
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    msg = {
        "agent_addr": receipt_data.agentAddress.lower(),
        "avatar_addr": receipt_data.avatarAddress.lower(),
        "product_id": product.id,
        "uuid": str(receipt.uuid),
        "planet_id": receipt_data.planetId.decode('utf-8'),
    }

    resp = sqs.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(msg))
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
