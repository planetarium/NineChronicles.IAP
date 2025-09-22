import datetime
import json
import logging
from typing import Any, Dict, Optional, Tuple

import structlog
from shared._crypto import Account
from shared._graphql import GQL
from shared.enums import PackageName, PlanetID, TxStatus
from shared.lib9c.actions.claim_items import ClaimItems
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue
from shared.models.product import Product
from shared.models.receipt import Receipt
from shared.schemas.message import SendProductMessage
from shared.utils.transaction import append_signature_to_unsigned_tx, create_unsigned_tx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, joinedload, selectinload, scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)
engine = create_engine(str(config.pg_dsn), pool_size=5, max_overflow=5)


def create_tx(sess: Session, account: Account, receipt: Receipt) -> bytes:
    if receipt.tx is not None:
        return bytes.fromhex(receipt.tx)

    logger.debug(f"Looking for product with ID: {receipt.product_id} for receipt: {receipt.uuid}")
    logger.debug(f"Session state: active={sess.is_active}, in_transaction={sess.in_transaction()}")

    # First try a simple query without joins to see if the product exists
    simple_product = sess.scalar(select(Product).where(Product.id == receipt.product_id))
    logger.debug(f"Simple product lookup result: {simple_product}")

    if simple_product is None:
        error_msg = f"Product not found for product_id: {receipt.product_id} in receipt: {receipt.uuid}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Test joinedload to confirm the issue (for debugging)
    try:
        joinedload_product = sess.scalar(
            select(Product)
            .options(joinedload(Product.fav_list))
            .options(joinedload(Product.fungible_item_list))
            .where(Product.id == receipt.product_id)
        )
        logger.debug(f"joinedload result: {joinedload_product}")
        if joinedload_product is None:
            logger.warning("joinedload returned None - this confirms the LEFT JOIN issue!")
    except Exception as e:
        logger.debug(f"joinedload test failed: {e}")

    # Use selectinload to avoid joinedload issues with mixed NULL/non-NULL results
    # This is especially important when fav_count=0 and item_count=1
    try:
        product = sess.scalar(
            select(Product)
            .options(selectinload(Product.fav_list))
            .options(selectinload(Product.fungible_item_list))
            .where(Product.id == receipt.product_id)
        )
        logger.debug(f"Product lookup with selectinload result: {product}")

        # Check if product exists but relationships are empty
        if product is not None:
            logger.debug(f"Product found - fav_list count: {len(product.fav_list)}, fungible_item_list count: {len(product.fungible_item_list)}")
        else:
            logger.warning("selectinload returned None, this should not happen if simple query worked")

    except Exception as e:
        logger.warning(f"selectinload failed: {e}, falling back to separate queries")
        # Fallback: load product and related data separately
        product = simple_product
        # Explicitly load the relationships using separate queries
        try:
            sess.refresh(product, ['fav_list', 'fungible_item_list'])
            logger.debug(f"After refresh - fav_list count: {len(product.fav_list)}, fungible_item_list count: {len(product.fungible_item_list)}")
        except Exception as refresh_error:
            logger.warning(f"refresh failed: {refresh_error}, using manual loading")
            # Manual loading as last resort
            from shared.models.product import FungibleAssetProduct, FungibleItemProduct
            product.fav_list = sess.scalars(
                select(FungibleAssetProduct).where(FungibleAssetProduct.product_id == product.id)
            ).all()
            product.fungible_item_list = sess.scalars(
                select(FungibleItemProduct).where(FungibleItemProduct.product_id == product.id)
            ).all()
            logger.debug(f"After manual loading - fav_list count: {len(product.fav_list)}, fungible_item_list count: {len(product.fungible_item_list)}")

    if product is None:
        error_msg = f"Product not found for product_id: {receipt.product_id} in receipt: {receipt.uuid}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    package_name = PackageName(receipt.package_name)
    avatar_address = Address(receipt.avatar_addr)
    memo = json.dumps(
        {
            "iap": {
                "g_sku": product.google_sku,
                "a_sku": (
                    product.apple_sku_k
                    if package_name == PackageName.NINE_CHRONICLES_K
                    else product.apple_sku
                ),
            }
        }
    )

    claim_data = []

    # Process fungible items
    logger.debug(f"Processing {len(product.fungible_item_list)} fungible items")
    for item in product.fungible_item_list:
        claim_data.append(
            FungibleAssetValue.from_raw_data(
                ticker=item.fungible_item_id, decimal_places=0, amount=item.amount * 1
            )
        )

    # Process fungible assets (fav_list)
    logger.debug(f"Processing {len(product.fav_list)} fungible assets")
    for fav in product.fav_list:
        claim_data.append(
            FungibleAssetValue.from_raw_data(
                ticker=fav.ticker,
                decimal_places=fav.decimal_places,
                amount=fav.amount * 1,
            )
        )

    logger.debug(f"Total claim_data items: {len(claim_data)}")

    action = ClaimItems(
        claim_data=[
            {"avatarAddress": avatar_address, "fungibleAssetValues": claim_data}
        ],
        memo=memo,
    )

    unsigned_tx = create_unsigned_tx(
        planet_id=PlanetID(receipt.planet_id),
        public_key=account.pubkey.hex(),
        address=account.address,
        nonce=receipt.nonce,
        plain_value=action.plain_value,
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(days=7),
    )

    signature = account.sign_tx(unsigned_tx)
    signed_tx = append_signature_to_unsigned_tx(unsigned_tx, signature)
    return signed_tx


def stage_tx(receipt: Receipt) -> Tuple[bool, str, Optional[str]]:
    logging.debug(f"STAGE: {config.stage} || REGION: {config.region_name}")
    gql = GQL(
        config.converted_gql_url_map[receipt.planet_id], config.headless_jwt_secret
    )

    return gql.stage(bytes.fromhex(receipt.tx))


def handle(message: SendProductMessage):
    """
    Receive purchase/buyer data from IAP server and create Tx to 9c.

    Receiving data
    - inventory_addr (str): Target inventory address to receive items
    - product_id (int): Target product ID to send to buyer
    - uuid (uuid): UUID of receipt-tx pair managed by DB
    """
    results = []
    sess = scoped_session(sessionmaker(bind=engine))

    receipt = sess.scalar(select(Receipt).where(Receipt.uuid == message.uuid))
    logger.debug(f"Receipt lookup result for UUID {message.uuid}: {receipt}")

    if not receipt:
        # Receipt not found
        success, msg, tx_id = (
            False,
            f"Receipt with UUID {message.uuid} not found in database",
            None,
        )
        logger.error(msg)
        return results

    if receipt.tx_status is not None and receipt.tx_status == TxStatus.SUCCESS:
        logger.info(f"{message.uuid} is already sent with Tx : {receipt.tx_id}")
        return

    account = Account(config.kms_key_id)
    gql_dict = {
        planet: GQL(url, config.headless_jwt_secret)
        for planet, url in config.converted_gql_url_map.items()
    }
    db_nonce_dict = {
        x.planet_id: x.nonce
        for x in sess.execute(
            select(
                Receipt.planet_id.label("planet_id"),
                func.max(Receipt.nonce).label("nonce"),
            ).group_by(Receipt.planet_id)
        ).all()
    }
    nonce_dict = {}
    target_list = []

    logger.debug(f"UUID : {message.uuid}")
    if receipt.tx_id:
        # Tx already staged
        success, msg, tx_id = (
            False,
            f"{receipt.uuid} is already treated with Tx : {receipt.tx_id}",
            None,
        )
        logger.warning(msg)
    elif receipt.tx:
        # Tx already created
        target_list.append((receipt, message.uuid))
        logger.info(f"{receipt.uuid} already has created tx with nonce {receipt.nonce}")
    else:
        # Fresh receipt
        receipt.tx_status = TxStatus.CREATED
        if receipt.nonce is None:
            receipt.nonce = max(  # max nonce of
                nonce_dict.get(  # current handling nonce (or nonce in blockchain)
                    receipt.planet_id,
                    gql_dict[receipt.planet_id].get_next_nonce(account.address),
                ),
                db_nonce_dict.get(receipt.planet_id, 0) + 1,  # DB stored nonce
            )
        receipt.tx = create_tx(sess, account, receipt).hex()
        nonce_dict[receipt.planet_id] = receipt.nonce + 1
        target_list.append((receipt, message.uuid))
        logger.info(f"{receipt.uuid}: Tx created with nonce: {receipt.nonce}")
        sess.add(receipt)
    sess.commit()

    # Stage created tx
    logger.info(f"Stage {len(target_list)} receipts")
    for _receipt, _uuid in target_list:
        success, msg, tx_id = stage_tx(_receipt)
        _receipt.tx_id = tx_id
        _receipt.tx_status = TxStatus.STAGED
        sess.add(_receipt)
        sess.commit()

        result = {
            "sqs_message_id": _uuid,
            "success": success,
            "message": msg,
            "uuid": str(_receipt.uuid) if _receipt else None,
            "tx_id": str(_receipt.tx_id) if _receipt else None,
            "nonce": str(_receipt.nonce) if _receipt else None,
            "order_id": str(_receipt.order_id) if _receipt else None,
        }
        results.append(result)
        if success:
            logger.info(json.dumps(result))
        else:
            logger.error(json.dumps(result))

    if sess is not None:
        sess.close()

    return results


@app.task(
    name="iap.send_product",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    priority=0,
    queue="product_queue",
)
def send_product(self, message: Dict[str, Any]) -> str:
    """
    Process claim messages as a Celery task

    Args:
        self: Task instance
        message: The message data from RabbitMQ/task queue

    Returns:
        str: Processing result message
    """
    try:
        logger.info("Send product", message=message)
        send_product_message = SendProductMessage.model_validate(message)
        handle(send_product_message)
        return "Send product successfully"
    except Exception as exc:
        logger.error("Error processing send product", message=message, exc_info=exc)
        self.retry(exc=exc)
