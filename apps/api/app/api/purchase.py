import base64
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from math import floor
from typing import Annotated, Dict, List, Optional
from uuid import UUID, uuid4

import requests
import structlog
from fastapi import APIRouter, Depends, Header, Query
from shared._graphql import GQL
from shared.enums import (
    PackageName,
    PlanetID,
    ProductType,
    ReceiptStatus,
    Store,
    TxStatus,
)
from shared.models.product import Price, Product
from shared.models.receipt import Receipt
from shared.models.user import AvatarLevel
from shared.schemas.message import SendProductMessage
from shared.schemas.receipt import (
    FreeReceiptSchema,
    PurchaseHistorySchema,
    ReceiptDetailSchema,
    ReceiptSchema,
    SimpleReceiptSchema,
)
from shared.utils.apple import get_jwt
from shared.validator.apple import validate_apple
from shared.validator.common import get_order_data
from shared.validator.google import ack_google, validate_google
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import joinedload, with_loader_criteria
from starlette.responses import JSONResponse

from app.celery import send_to_worker
from app.config import config
from app.dependencies import session
from app.exceptions import InsufficientUserDataException, ReceiptNotFoundException
from app.utils import (
    create_season_pass_jwt,
    get_mileage,
    get_purchase_count,
    upsert_mileage,
)

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

logger = structlog.get_logger(__name__)


def raise_error(sess, receipt: Receipt, e: Exception):
    sess.add(receipt)
    sess.commit()
    logger.error(f"[{receipt.uuid}] :: {e}")
    raise e


@router.get("/log")
def log_request_product(
    planet_id: str,
    agent_address: str,
    avatar_address: str,
    product_id: str,
    order_id: Optional[str] = "",
    data: Optional[str] = "",
):
    """
    # Purchase log
    ---

    Logs purchase request data
    """
    logger.info(
        f"[PURCHASE_LOG] {planet_id} :: {agent_address} :: {avatar_address} :: {product_id} :: {order_id}"
    )
    if data:
        logger.info(data)
    return JSONResponse(
        status_code=200, content=f"Order {order_id} for product {product_id} logged."
    )


def check_required_level(sess, receipt: Receipt, product: Product) -> Receipt:
    if product.required_level:
        cached_data = sess.scalar(
            select(AvatarLevel).where(
                AvatarLevel.avatar_addr == receipt.avatar_addr,
                AvatarLevel.planet_id == receipt.planet_id,
            )
        )
        if not cached_data:
            cached_data = AvatarLevel(
                agent_addr=receipt.agent_addr,
                avatar_addr=receipt.avatar_addr,
                planet_id=receipt.planet_id,
                level=-1,
            )

        # Fetch and update current level
        if cached_data.level < product.required_level:
            gql_url = config.converted_gql_url_map[receipt.planet_id]

            gql = GQL(gql_url, jwt_secret=config.headless_jwt_secret)
            query = f"""{{ stateQuery {{ avatar (avatarAddress: "{receipt.avatar_addr}") {{ level}} }} }}"""
            resp = None
            try:
                resp = requests.post(
                    gql_url,
                    json={"query": query},
                    headers={"Authorization": f"Bearer {gql.create_token()}"},
                    timeout=1,
                )
                cached_data.level = resp.json()["data"]["stateQuery"]["avatar"]["level"]
            except Exception as e:
                logger.error(f"{resp.status_code} :: {resp.text}" if resp else e)

        # NOTE: Do not commit here to prevent unintended data save during process
        sess.add(cached_data)

        # Final check
        if cached_data.level < product.required_level:
            receipt.status = ReceiptStatus.REQUIRED_LEVEL
            msg = f"Avatar level {cached_data.level} does not met required level {product.required_level}"
            receipt.msg = msg
            raise_error(sess, receipt, ValueError(msg))

    return receipt


def check_purchase_limit(
    sess,
    receipt: Receipt,
    product: Product,
    limit_type: str,
    limit: int,
    use_avatar: bool = False,
) -> Receipt:
    purchase_count = get_purchase_count(
        sess,
        product.id,
        planet_id=PlanetID(receipt.planet_id),
        agent_addr=receipt.agent_addr if not use_avatar else None,
        avatar_addr=receipt.avatar_addr if use_avatar else None,
        daily_limit=limit_type == "daily",
        weekly_limit=limit_type == "weekly",
    )
    if purchase_count > limit:
        receipt.status = ReceiptStatus.PURCHASE_LIMIT_EXCEED
        raise_error(
            sess,
            receipt,
            ValueError(f"{limit_type.capitalize()} purchase limit exceeded."),
        )

    return receipt


@router.get("/invalid-receipt-count", response_model=int)
def check_invalid_receipt(
    sess=Depends(session),
):
    """Notify all invalid receipt"""
    invalid_list_count = (
        sess.query(func.count(Receipt.id))
        .join(Product)
        .filter(
            Receipt.status == ReceiptStatus.VALID,
            or_(
                Receipt.tx_status.in_(
                    [TxStatus.INVALID, TxStatus.STAGED, TxStatus.FAILURE]
                ),
                Receipt.tx_status.is_(None),
            ),
            Product.google_sku.notlike("%pass%"),
            Receipt.created_at
            <= (datetime.now(tz=timezone.utc) - timedelta(minutes=5)),
            Receipt.created_at >= datetime(2025, 1, 1),
        )
        .scalar()
    )

    return invalid_list_count


@router.post("/retry", response_model=ReceiptDetailSchema)
def retry_product(
    receipt_data: SimpleReceiptSchema,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    sess=Depends(session),
):
    """
    # Purchase retry
    ---

    ** Retry from client's pending IAP purchase data.**
    """
    order_id, product_id, purchased_at = get_order_data(receipt_data)
    prev_receipt = sess.scalar(
        select(Receipt).where(
            Receipt.store == receipt_data.store, Receipt.order_id == order_id
        )
    )

    # Cannot handle missing receipt
    if not prev_receipt:
        raise ReceiptNotFoundException("", order_id)

    # Already handled
    if prev_receipt.tx_status is not None:
        logger.info(
            f"[Retry] {order_id} has already been handled :: {prev_receipt.uuid}"
        )
        return prev_receipt

    # Insufficient user data
    empty_data = []
    if not prev_receipt.planet_id:
        empty_data.append("planet_id")
    if not prev_receipt.agent_addr:
        empty_data.append("agent_addr")
    if not prev_receipt.avatar_addr:
        empty_data.append("avatar_addr")

    if empty_data:
        raise InsufficientUserDataException(prev_receipt.uuid, order_id, empty_data)

    # Can do retry
    receipt_schema = ReceiptSchema(
        data=receipt_data.data,
        store=receipt_data.store,
        agentAddress=prev_receipt.agent_addr,
        avatarAddress=prev_receipt.avatar_addr,
        planetId=prev_receipt.planet_id,
    )
    return request_product(receipt_schema, x_iap_packagename=x_iap_packagename)


@router.post("/request", response_model=ReceiptDetailSchema)
def request_product(
    receipt_data: ReceiptSchema,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    sess=Depends(session),
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
        receipt_data.planetId = (
            PlanetID.ODIN if config.stage == "mainnet" else PlanetID.ODIN_INTERNAL
        )

    order_id, product_id, purchased_at = get_order_data(receipt_data)
    prev_receipt = sess.scalar(
        select(Receipt).where(
            Receipt.store == receipt_data.store, Receipt.order_id == order_id
        )
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
            .options(joinedload(Product.fav_list))
            .options(joinedload(Product.fungible_item_list))
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
            .options(joinedload(Product.fav_list))
            .options(joinedload(Product.fungible_item_list))
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
        raise_error(
            sess,
            receipt,
            ValueError(
                f"{product_id} is not valid product ID for {receipt_data.store.name} store."
            ),
        )

    receipt.status = ReceiptStatus.VALIDATION_REQUEST

    # validate
    ## Google
    if receipt_data.store in (Store.GOOGLE, Store.GOOGLE_TEST):
        token = receipt_data.order.get("purchaseToken")
        if not (product_id and token):
            receipt.status = ReceiptStatus.INVALID
            raise_error(
                sess,
                receipt,
                ValueError(
                    "Invalid Receipt: Both productId and purchaseToken must be present en receipt data"
                ),
            )

        success, msg, purchase = validate_google(
            config.google_credential, receipt.package_name, order_id, product_id, token
        )
        # FIXME: google API result may not include productId.
        #  Can we get productId always?
        # if purchase.productId != product.google_sku:
        #     receipt.status = ReceiptStatus.INVALID
        #     raise_error(sess, receipt, ValueError(
        #         f"Invalid Product ID: Given {product.google_sku} is not identical to found from receipt: {purchase.productId}"))
        if success:
            ack_google(config.google_credential, x_iap_packagename, product_id, token)
    ## Apple
    elif receipt_data.store in (Store.APPLE, Store.APPLE_TEST):
        encoded_tx_id = urllib.parse.quote_plus(order_id)
        success, msg, purchase = validate_apple(
            get_jwt(
                base64.b64decode(config.apple_credential)
                .decode("utf-8")
                .replace("\\n", "\n"),
                receipt.package_name,
                config.apple_key_id,
                config.apple_issuer_id,
            ),
            config.apple_validation_url.format(transactionId=encoded_tx_id),
            order_id,
        )
        if success:
            data = receipt_data.data.copy()
            data.update(**purchase.json_data)
            receipt.data = data
            receipt.purchased_at = purchase.originalPurchaseDate
            # Get product from validation result and check product existence.
            stmt = (
                select(Product)
                .options(joinedload(Product.fav_list))
                .options(joinedload(Product.fungible_item_list))
                .where(Product.active.is_(True))
            )

            if x_iap_packagename == PackageName.NINE_CHRONICLES_M:
                stmt = stmt.where(Product.apple_sku == purchase.productId)
            elif x_iap_packagename == PackageName.NINE_CHRONICLES_K:
                stmt = stmt.where(Product.apple_sku_k == purchase.productId)
            else:
                raise_error(
                    sess,
                    receipt,
                    ValueError(f"{x_iap_packagename} is not valid package name."),
                )
            product = sess.scalar(stmt)

        if not product:
            receipt.status = ReceiptStatus.INVALID
            raise_error(
                sess,
                receipt,
                ValueError(
                    f"{purchase.productId} is not valid product ID for {receipt_data.store.name} store."
                ),
            )
        receipt.product_id = product.id
    ## Test
    elif receipt_data.store == Store.TEST:
        if config.stage == "mainnet":
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

    now = datetime.now(timezone.utc)
    if (product.open_timestamp and product.open_timestamp > now) or (
        product.close_timestamp and product.close_timestamp < datetime.now(timezone.utc)
    ):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    receipt = check_required_level(sess, receipt, product)

    # Handle season pass products differently
    # FIXME: Can we get season pass product without magic string?
    if "pass" in product.google_sku:
        """
        SKU Rule : {store}_pkg_{passType}{seasonIndex}{suffix}
        passType : [[seasonpass | couragepass] | adventurebosspass | worldclearpass]
        seasonIndex: integer. Season index is sequential for each type.
        suffix:
          - "" : premium
          - "plus": premium+ for premium
          - "all" : premium & premium+
          - "premium": new premium type. premium & premium+
        """
        # NOTE: Check purchase limit using avatar_addr, not agent_addr
        receipt = check_purchase_limit(
            sess,
            receipt,
            product,
            limit_type="account",
            limit=product.account_limit,
            use_avatar=True,
        )

        prefix, body = product.google_sku.split("pass")
        try:
            if "season" in prefix or "courage" in prefix:
                pass_type = "CouragePass"
            elif "adventure" in prefix:
                pass_type = "AdventureBossPass"
            elif "world" in prefix:
                pass_type = "WorldClearPass"
            else:
                pass_type = None
            season_index = int("".join([x for x in body if x.isdigit()]))
        except:
            pass_type = None
            season_index = 0
        season_pass_host = config.season_pass_host
        claim_list = [
            {
                "ticker": x.fungible_item_id,
                "amount": x.amount,
                "decimal_places": 0,
            }
            for x in product.fungible_item_list
        ]
        claim_list.extend(
            [
                {
                    "ticker": x.ticker,
                    "amount": floor(x.amount),
                    "decimal_places": x.decimal_places,
                }
                for x in product.fav_list
            ]
        )
        season_pass_type = "".join([x for x in body if x.isalpha()])
        resp = requests.post(
            f"{season_pass_host}/api/user/upgrade",
            json={
                "planet_id": receipt_data.planetId.value.decode("utf-8"),
                "agent_addr": receipt.agent_addr.lower(),
                "avatar_addr": receipt.avatar_addr.lower(),
                "pass_type": pass_type,
                "season_index": int(season_index),
                "is_premium": season_pass_type in ("", "all", "premium"),
                "is_premium_plus": season_pass_type in ("plus", "all", "premium"),
                "g_sku": product.google_sku,
                "a_sku": product.apple_sku,
                # SeasonPass only uses claims
                "reward_list": claim_list,
            },
            headers={"Authorization": f"Bearer {create_season_pass_jwt()}"},
        )
        if resp.status_code != 200:
            receipt.msg = f"{resp.status_code} :: {resp.text}"
            msg = f"SeasonPass Upgrade Failed: {resp.text}"
            logging.error(msg)
            raise_error(sess, receipt, Exception(msg))
    else:
        if product.daily_limit:
            receipt = check_purchase_limit(
                sess, receipt, product, "daily", product.daily_limit
            )
        if product.weekly_limit:
            receipt = check_purchase_limit(
                sess, receipt, product, "weekly", product.weekly_limit
            )
        if product.account_limit:
            receipt = check_purchase_limit(
                sess, receipt, product, "account", product.account_limit
            )

        msg = {
            "agent_addr": receipt_data.agentAddress.lower(),
            "avatar_addr": receipt_data.avatarAddress.lower(),
            "product_id": product.id,
            "uuid": str(receipt.uuid),
            "planet_id": receipt_data.planetId.decode("utf-8"),
            "package_name": receipt.package_name,
        }

        send_product_message = SendProductMessage(uuid=str(receipt.uuid))
        task_id = send_to_worker("iap.send_product", send_product_message.model_dump())
        logging.debug(
            f"Task for product {receipt.uuid} sent to Celery worker with task_id: {task_id}"
        )

    receipt = upsert_mileage(sess, product, receipt)
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    return receipt


@router.post("/free", response_model=ReceiptDetailSchema)
def free_product(
    receipt_data: FreeReceiptSchema,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    sess=Depends(session),
):
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
        .options(joinedload(Product.fav_list))
        .options(joinedload(Product.fungible_item_list))
        .where(
            Product.active.is_(True),
            or_(
                Product.google_sku == receipt_data.sku,
                Product.apple_sku == receipt_data.sku,
                Product.apple_sku_k == receipt_data.sku,
            ),
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
        purchased_at=datetime.now(timezone.utc),
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
        raise_error(
            sess,
            receipt,
            ValueError(f"Product {receipt_data.sku} not found or inactive"),
        )

    if product.product_type != ProductType.FREE:
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = "This product it not for free"
        raise_error(
            sess,
            receipt,
            ValueError(
                f"Requested product {product.id}::{product.name} is not for free"
            ),
        )

    if (
        product.open_timestamp and product.open_timestamp > datetime.now(timezone.utc)
    ) or (
        product.close_timestamp and product.close_timestamp < datetime.now(timezone.utc)
    ):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    # Purchase Limit
    if product.daily_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="daily", limit=product.daily_limit
        )
    if product.weekly_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="weekly", limit=product.weekly_limit
        )
    if product.account_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="account", limit=product.account_limit
        )

    # Required level
    receipt = check_required_level(sess, receipt, product)

    receipt.status = ReceiptStatus.VALID
    receipt = upsert_mileage(sess, product, receipt)
    sess.add(receipt)
    sess.commit()
    sess.refresh(receipt)

    msg = {
        "agent_addr": receipt_data.agentAddress.lower(),
        "avatar_addr": receipt_data.avatarAddress.lower(),
        "product_id": product.id,
        "uuid": str(receipt.uuid),
        "planet_id": receipt_data.planetId.decode("utf-8"),
        "package_name": receipt.package_name,
    }

    send_product_message = SendProductMessage(uuid=str(receipt.uuid))
    task_id = send_to_worker("iap.send_product", send_product_message.model_dump())
    logging.debug(
        f"Task for product {receipt.uuid} sent to Celery worker with task_id: {task_id}"
    )

    return receipt


@router.post("/mileage", response_model=ReceiptDetailSchema)
def mileage_product(
    receipt_data: FreeReceiptSchema,
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
    sess=Depends(session),
):
    """
    # Purchase Mileage Product
    ---

    **Purchase mileage product and unload product from IAP garage to buyer.**

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
        .options(joinedload(Product.fav_list))
        .options(joinedload(Product.fungible_item_list))
        .where(
            Product.active.is_(True),
            or_(
                Product.google_sku == receipt_data.sku,
                Product.apple_sku == receipt_data.sku,
                Product.apple_sku_k == receipt_data.sku,
            ),
        )
    )
    order_id = f"MILE-{uuid4()}"
    receipt = Receipt(
        store=receipt_data.store,
        package_name=x_iap_packagename.value,
        data={"SKU": receipt_data.sku, "OrderId": order_id},
        agent_addr=receipt_data.agentAddress.lower(),
        avatar_addr=receipt_data.avatarAddress.lower(),
        order_id=order_id,
        purchased_at=datetime.now(timezone.utc),
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
        raise_error(
            sess,
            receipt,
            ValueError(f"Product {receipt_data.sku} not found or inactive"),
        )

    if product.product_type != ProductType.MILEAGE:
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = "This product it not for free"
        raise_error(
            sess,
            receipt,
            ValueError(
                f"Requested product {product.id}::{product.name} is not mileage product"
            ),
        )

    if receipt.planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
        receipt.status = ReceiptStatus.INVALID
        receipt.msg = f"No mileage product for thor chain"
        raise_error(
            sess,
            receipt,
            ValueError(
                f"You cannot purchase mileage product {product.id}::{product.name} in Thor chain"
            ),
        )

    if (
        product.open_timestamp and product.open_timestamp > datetime.now(timezone.utc)
    ) or (
        product.close_timestamp and product.close_timestamp < datetime.now(timezone.utc)
    ):
        receipt.status = ReceiptStatus.TIME_LIMIT
        raise_error(sess, receipt, ValueError(f"Not in product opening time"))

    # Fetch and validate mileage
    target_mileage = get_mileage(sess, receipt_data.agentAddress)

    if target_mileage.mileage < product.mileage_price:
        receipt.status = ReceiptStatus.NOT_ENOUGH_MILEAGE
        msg = f"{target_mileage.mileage} is not enough to buy product {product.id}: {product.mileage_price} required"
        receipt.msg = msg
        raise_error(sess, receipt, ValueError(msg))

    # Required level
    receipt = check_required_level(sess, receipt, product)

    # Purchase Limit
    if product.daily_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="daily", limit=product.daily_limit
        )
    if product.weekly_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="weekly", limit=product.weekly_limit
        )
    if product.account_limit:
        receipt = check_purchase_limit(
            sess, receipt, product, limit_type="account", limit=product.account_limit
        )

    # Handle mileage
    target_mileage.mileage -= product.mileage_price
    receipt = upsert_mileage(sess, product, receipt, target_mileage)
    receipt.status = ReceiptStatus.VALID
    sess.commit()
    sess.refresh(receipt)

    msg = {
        "agent_addr": receipt_data.agentAddress.lower(),
        "avatar_addr": receipt_data.avatarAddress.lower(),
        "product_id": product.id,
        "uuid": str(receipt.uuid),
        "planet_id": receipt_data.planetId.decode("utf-8"),
        "package_name": receipt.package_name,
    }

    send_product_message = SendProductMessage(uuid=str(receipt.uuid))
    task_id = send_to_worker("iap.send_product", send_product_message.model_dump())
    logging.debug(
        f"Task for product {receipt.uuid} sent to Celery worker with task_id: {task_id}"
    )

    return receipt


@router.get("/history", response_model=List[PurchaseHistorySchema])
def purchase_history(
    agent_addr: str,
    offset: int = 0,
    limit: int = 10,
    epoch: Optional[datetime] = None,
    product_id: Optional[int] = None,
    sess=Depends(session),
):
    """
    Get succeeded IAP type purchase list.

    :param agent_addr: Agent address to find.
    :param offset: Offset to find. Ignore latest K receipts
    :param limit: Limit to get receipt. Maximum 100 receipt can be fetched.
    :param epoch: Optional. If provided, search only purchased after epoch.
    :param product_id: Optional. If product_id provided, search only this product's purchase history.
    :return: receipt detail list.
    """
    q = (
        select(Receipt)
        .join(Receipt.product)  # Receipt -> Product
        .where(
            Receipt.agent_addr == agent_addr,
            Receipt.status == ReceiptStatus.VALID,
            Product.product_type == ProductType.IAP,
        )
        .options(
            joinedload(Receipt.product).joinedload(Product.price_list),
            with_loader_criteria(Price, Price.currency == "USD"),
        )
    )

    if epoch:
        q = q.filter(Receipt.purchased_at >= epoch)
    if product_id:
        q = q.filter(Receipt.product_id == product_id)
    if offset:
        q = q.offset(offset)
    if limit:
        q = q.limit(min(limit, 100))

    return sess.scalars(q.order_by(desc(Receipt.id))).unique().all()


@router.get("/status", response_model=Dict[UUID, Optional[ReceiptDetailSchema]])
def purchase_status(uuid: Annotated[List[UUID], Query()] = ..., sess=Depends(session)):
    """
    Get current status of receipt.
    You can validate multiple UUIDs at once.

    **NOTE**
    For the non-existing UUID, response body of that UUID would be `null`. Please be aware client must handle `null`.
    """
    receipt_dict = {
        x.uuid: x
        for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid))).fetchall()
    }
    return {x: receipt_dict.get(x, None) for x in uuid}
