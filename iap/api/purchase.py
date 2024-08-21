import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional, Annotated
from uuid import UUID, uuid4

import boto3
import requests
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload
from starlette.responses import JSONResponse

from common.enums import ReceiptStatus, Store, PackageName
from common.models.product import Product
from common.models.receipt import Receipt
from common.models.user import AvatarLevel
from common.utils.aws import fetch_parameter
from common.utils.receipt import PlanetID
from iap import settings
from iap.dependencies import session
from iap.exceptions import ReceiptNotFoundException
from iap.main import logger
from iap.schemas.receipt import ReceiptSchema, ReceiptDetailSchema, FreeReceiptSchema
from iap.utils import create_season_pass_jwt, get_purchase_count
from iap.validator.apple import validate_apple
from iap.validator.common import get_order_data
from iap.validator.google import validate_google, ack_google

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

sqs = boto3.client("sqs", region_name=settings.REGION_NAME)
SQS_URL = os.environ.get("SQS_URL")
VOUCHER_SQS_URL = os.environ.get("VOUCHER_SQS_URL")


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


def check_required_level(sess, receipt: Receipt, product: Product) -> Receipt:
    if product.required_level:
        cached_data = sess.scalar(select(AvatarLevel).where(
            AvatarLevel.avatar_addr == receipt.avatar_addr,
            AvatarLevel.planet_id == receipt.planet_id)
        )
        if not cached_data:
            cached_data = AvatarLevel(
                agent_addr=receipt.agent_addr,
                avatar_addr=receipt.avatar_addr,
                planet_id=receipt.planet_id,
                level=-1
            )

        # Fetch and update current level
        if cached_data.level < product.required_level:
            gql_url = None
            if receipt.planet_id in (PlanetID.ODIN, PlanetID.ODIN_INTERNAL):
                gql_url = os.environ.get("ODIN_GQL_URL")
            elif receipt.planet_id in (PlanetID.HEIMDALL, PlanetID.HEIMDALL_INTERNAL):
                gql_url = os.environ.get("HEIMDALL_GQL_URL")

            query = f"""{{ stateQuery {{ avatar (avatarAddress: "{receipt.avatar_addr}") {{ level}} }} }}"""
            try:
                resp = requests.post(gql_url, json={"query": query}, timeout=1)
                cached_data.level = resp.json()["data"]["stateQuery"]["avatar"]["level"]
            except:
                # Whether request is failed or no fitted data found
                pass

        # NOTE: Do not commit here to prevent unintended data save during process
        sess.add(cached_data)

        # Final check
        if cached_data.level < product.required_level:
            receipt.status = ReceiptStatus.REQUIRED_LEVEL
            msg = f"Avatar level {cached_data.level} does not met required level {product.required_level}"
            receipt.msg = msg
            raise_error(sess, receipt, ValueError(msg))

    return receipt


def check_purchase_limit(sess, receipt: Receipt, product: Product, limit_type: str, limit: int,
                         use_avatar: bool = False) -> Receipt:
    purchase_count = get_purchase_count(
        sess, product.id, planet_id=PlanetID(receipt.planet_id),
        agent_addr=receipt.agent_addr if not use_avatar else None,
        avatar_addr=receipt.avatar_addr if use_avatar else None,
        daily_limit=limit_type == "daily", weekly_limit=limit_type == "weekly"
    )
    if purchase_count > limit:
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(sess, receipt, ValueError(f"{limit_type.capitalize()} purchase limit exceeded."))

    return receipt


@router.post("/request", response_model=ReceiptDetailSchema)
def request_product(receipt_data: ReceiptSchema,
                    x_iap_packagename: Annotated[PackageName | None, Header()] = PackageName.NINE_CHRONICLES_M,
                    sess=Depends(session)
                    ):
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
        package_name=x_iap_packagename.value,
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

        success, msg, purchase = validate_google(receipt.package_name, order_id, product_id, token)
        # FIXME: google API result may not include productId.
        #  Can we get productId always?
        # if purchase.productId != product.google_sku:
        #     receipt.status = ReceiptStatus.INVALID
        #     raise_error(sess, receipt, ValueError(
        #         f"Invalid Product ID: Given {product.google_sku} is not identical to found from receipt: {purchase.productId}"))
        if success:
            ack_google(x_iap_packagename, product_id, token)
    ## Apple
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        success, msg, purchase = validate_apple(receipt.package_name, order_id)
        if success:
            data = receipt_data.data.copy()
            data.update(**purchase.json_data)
            receipt.data = data
            receipt.purchased_at = purchase.originalPurchaseDate
            # Get product from validation result and check product existence.
            stmt = (select(Product)
                    .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
                    .where(Product.active.is_(True))
                    )

            if x_iap_packagename == PackageName.NINE_CHRONICLES_M:
                stmt = stmt.where(Product.apple_sku == purchase.productId)
            elif x_iap_packagename == PackageName.NINE_CHRONICLES_K:
                stmt = stmt.where(Product.apple_sku_k == purchase.productId)
            else:
                raise_error(sess, receipt, ValueError(f"{x_iap_packagename} is not valid package name."))
            product = sess.scalar(stmt)

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

    receipt = check_required_level(sess, receipt, product)

    # Check purchase limit
    # FIXME: Can we get season pass product without magic string?
    if "SeasonPass" in product.name:
        # NOTE: Check purchase limit using avatar_addr, not agent_addr
        receipt = check_purchase_limit(sess, receipt, product, limit_type="account", limit=product.account_limit,
                                       use_avatar=True)

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
        if product.daily_limit:
            receipt = check_purchase_limit(sess, receipt, product, "daily", product.daily_limit)
        if product.weekly_limit:
            receipt = check_purchase_limit(sess, receipt, product, "weekly", product.weekly_limit)
        if product.account_limit:
            receipt = check_purchase_limit(sess, receipt, product, "account", product.account_limit)

        msg = {
            "agent_addr": receipt_data.agentAddress.lower(),
            "avatar_addr": receipt_data.avatarAddress.lower(),
            "product_id": product.id,
            "uuid": str(receipt.uuid),
            "planet_id": receipt_data.planetId.decode('utf-8'),
            "package_name": receipt.package_name,
        }

        resp = sqs.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(msg))
        logger.debug(f"message [{resp['MessageId']}] sent to SQS.")

    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    return receipt


@router.post("/free", response_model=ReceiptDetailSchema)
def free_product(receipt_data: FreeReceiptSchema,
                 x_iap_packagename: Annotated[PackageName | None, Header()] = PackageName.NINE_CHRONICLES_M,
                 sess=Depends(session)):
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
            or_(
                Product.google_sku == receipt_data.sku,
                Product.apple_sku == receipt_data.sku,
                Product.apple_sku_k == receipt_data.sku
            )
        )
    )
    order_id = f"FREE-{uuid4()}"
    receipt = Receipt(
        store=receipt_data.store,
        package_name=x_iap_packagename.value,
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
        receipt.msg = f"Product {receipt_data.sku} not exists or inactive"
        raise_error(sess, receipt, ValueError(f"Product {receipt_data.sku} not found or inactive"))

    if not product.is_free:
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = "This product it not for free"
        raise_error(sess, receipt, ValueError(f"Requested product {product.id}::{product.name} is not for free"))

    if ((product.open_timestamp and product.open_timestamp > datetime.now()) or
            (product.close_timestamp and product.close_timestamp < datetime.now())):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    # Purchase Limit
    if product.daily_limit:
        receipt = check_purchase_limit(sess, receipt, product, limit_type="daily", limit=product.daily_limit)
    if product.weekly_limit:
        receipt = check_purchase_limit(sess, receipt, product, limit_type="weekly", limit=product.weekly_limit)
    if product.account_limit:
        receipt = check_purchase_limit(sess, receipt, product, limit_type="account", limit=product.account_limit)

    # Required level
    receipt = check_required_level(sess, receipt, product)

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
        "package_name": receipt.package_name,
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
