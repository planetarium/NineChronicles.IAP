import dataclasses
import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, joinedload, scoped_session, sessionmaker

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.consts import GQL_DICT
from common.enums import TxStatus, PackageName
from common.lib9c.actions.claim_items import ClaimItems
from common.lib9c.models.address import Address
from common.lib9c.models.fungible_asset_value import FungibleAssetValue
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.aws import fetch_parameter, fetch_secrets, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx

STAGE = os.environ.get("STAGE")
REGION_NAME = os.environ.get("REGION_NAME", "us-east-2")
DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


@dataclass
class SQSMessageRecord:
    messageId: str
    receiptHandle: str
    body: Union[dict, str]
    attributes: dict
    messageAttributes: dict
    md5OfBody: str
    eventSource: str
    eventSourceARN: str
    awsRegion: str

    # Avoid TypeError when init dataclass.
    #  https://stackoverflow.com/questions/54678337/how-does-one-ignore-extra-arguments-passed-to-a-dataclass
    def __init__(self, **kwargs):
        names = set([f.name for f in dataclasses.fields(self)])
        for k, v in kwargs.items():
            if k in names:
                if k == 'body' and isinstance(v, str):
                    v = json.loads(v)
                setattr(self, k, v)


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]


def create_tx(sess: Session, account: Account, receipt: Receipt) -> bytes:
    if receipt.tx is not None:
        return bytes.fromhex(receipt.tx)

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        .where(Product.id == receipt.product_id)
    )

    package_name = PackageName(receipt.package_name)
    avatar_address = Address(receipt.avatar_addr)
    memo = json.dumps({"iap":
                           {"g_sku": product.google_sku,
                            "a_sku": product.apple_sku_k if package_name == PackageName.NINE_CHRONICLES_K
                            else product.apple_sku}
                       })

    claim_data = []
    for item in product.fungible_item_list:
        claim_data.append(FungibleAssetValue.from_raw_data(
            ticker=item.fungible_item_id, decimal_places=0,
            amount=item.amount * (5 if receipt.planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL) else 1)
        ))
    for fav in product.fav_list:
        claim_data.append(FungibleAssetValue.from_raw_data(
            ticker=fav.ticker, decimal_places=fav.decimal_places,
            amount=fav.amount * (5 if receipt.planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL) else 1)
        ))

    action = ClaimItems(claim_data=[{"avatarAddress": avatar_address, "fungibleAssetValues": claim_data}], memo=memo)

    unsigned_tx = create_unsigned_tx(
        planet_id=PlanetID(receipt.planet_id),
        public_key=account.pubkey.hex(), address=account.address, nonce=receipt.nonce,
        plain_value=action.plain_value,
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=7)
    )

    signature = account.sign_tx(unsigned_tx)
    signed_tx = append_signature_to_unsigned_tx(unsigned_tx, signature)
    return signed_tx


def stage_tx(receipt: Receipt) -> Tuple[bool, str, Optional[str]]:
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region_name}")
    gql = GQL(GQL_DICT[receipt.planet_id], HEADLESS_GQL_JWT_SECRET)

    return gql.stage(bytes.fromhex(receipt.tx))


def handle(event, context):
    """
    Receive purchase/buyer data from IAP server and create Tx to 9c.

    Receiving data
    - inventory_addr (str): Target inventory address to receive items
    - product_id (int): Target product ID to send to buyer
    - uuid (uuid): UUID of receipt-tx pair managed by DB
    """
    message = SQSMessage(Records=event.get("Records", {}))
    logger.info(f"SQS Message: {message}")

    results = []
    sess = scoped_session(sessionmaker(bind=engine))
    account = Account(fetch_kms_key_id(STAGE, REGION_NAME))
    gql_dict = {planet: GQL(url, HEADLESS_GQL_JWT_SECRET) for planet, url in GQL_DICT.items()}
    db_nonce_dict = {
        x.planet_id: x.nonce
        for x in sess.execute(select(Receipt.planet_id.label("planet_id"), func.max(Receipt.nonce).label("nonce"))
                              .group_by(Receipt.planet_id)).all()
    }
    nonce_dict = {}
    target_list = []

    # Set nonce first before process
    uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid") is not None]
    receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
    for i, record in enumerate(message.Records):
        try:
            logger.debug(f"UUID : {record.body.get('uuid')}")
            receipt = receipt_dict.get(record.body.get("uuid"))
            if not receipt:
                # Receipt not found
                success, msg, tx_id = False, f"{receipt.uuid} is not exist in Receipt", None
                logger.error(msg)
            elif receipt.tx_id:
                # Tx already staged
                success, msg, tx_id = False, f"{receipt.uuid} is already treated with Tx : {receipt.tx_id}", None
                logger.warning(msg)
            elif receipt.tx:
                # Tx already created
                target_list.append((receipt, record))
                logger.info(f"{receipt.uuid} already has created tx with nonce {receipt.nonce}")
            else:
                # Fresh receipt
                receipt.tx_status = TxStatus.CREATED
                if receipt.nonce is None:
                    receipt.nonce = max(  # max nonce of
                        nonce_dict.get(  # current handling nonce (or nonce in blockchain)
                            receipt.planet_id,
                            gql_dict[receipt.planet_id].get_next_nonce(account.address)
                        ),
                        db_nonce_dict.get(receipt.planet_id, 0) + 1  # DB stored nonce
                    )
                receipt.tx = create_tx(sess, account, receipt).hex()
                nonce_dict[receipt.planet_id] = receipt.nonce + 1
                target_list.append((receipt, record))
                logger.info(f"{receipt.uuid}: Tx created with nonce: {receipt.nonce}")
                sess.add(receipt)
        except Exception as e:
            logger.error(f"Error occurred: {record.body.get('uuid')} :: {e}")
            continue
    sess.commit()

    # Stage created tx
    logger.info(f"Stage {len(target_list)} receipts")
    for receipt, record in target_list:
        try:
            success, msg, tx_id = stage_tx(receipt)
            receipt.tx_id = tx_id
            receipt.tx_status = TxStatus.STAGED
            sess.add(receipt)
            sess.commit()

            result = {
                "sqs_message_id": record.messageId,
                "success": success,
                "message": msg,
                "uuid": str(receipt.uuid) if receipt else None,
                "tx_id": str(receipt.tx_id) if receipt else None,
                "nonce": str(receipt.nonce) if receipt else None,
                "order_id": str(receipt.order_id) if receipt else None,
            }
            results.append(result)
            if success:
                logger.info(json.dumps(result))
            else:
                logger.error(json.dumps(result))
        except Exception as e:
            logger.error(f"Error occurred: {record.body.get('uuid')} :: {e}")
            continue

    if sess is not None:
        sess.close()

    return results
