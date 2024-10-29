import dataclasses
import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from sqlalchemy import create_engine, select
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

    # Avoid TypeError when init dataclass. https://stackoverflow.com/questions/54678337/how-does-one-ignore-extra-arguments-passed-to-a-dataclass # noqa
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


def process(sess: Session, message: SQSMessageRecord, nonce: int = None) -> Tuple[
    Tuple[bool, str, Optional[str]], int, bytes
]:
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region_name}")
    account = Account(fetch_kms_key_id(stage, region_name))
    planet_id: PlanetID = PlanetID(bytes(message.body["planet_id"], 'utf-8'))

    gql = GQL(GQL_DICT[planet_id], HEADLESS_GQL_JWT_SECRET)
    if not nonce:
        nonce = gql.get_next_nonce(account.address)

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        .where(Product.id == message.body.get("product_id"))
    )

    package_name = PackageName(message.body.get("package_name"))
    avatar_address = Address(message.body.get("avatar_addr"))
    memo = json.dumps({"iap":
                           {"g_sku": product.google_sku,
                            "a_sku": product.apple_sku_k if package_name == PackageName.NINE_CHRONICLES_K
                            else product.apple_sku}
                       })

    claim_data = []
    for item in product.fungible_item_list:
        claim_data.append(FungibleAssetValue.from_raw_data(
            ticker=item.fungible_item_id, decimal_places=0, amount=item.amount
        ))
    for fav in product.fav_list:
        claim_data.append(FungibleAssetValue.from_raw_data(
            ticker=fav.ticker, decimal_places=fav.decimal_places, amount=fav.amount
        ))

    action = ClaimItems(claim_data=[{"avatarAddress": avatar_address, "fungibleAssetValues": claim_data}], memo=memo)

    unsigned_tx = create_unsigned_tx(
        planet_id=planet_id,
        public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
        plain_value=action.plain_value, timestamp=datetime.datetime.utcnow() + datetime.timedelta(days=7)
    )

    signature = account.sign_tx(unsigned_tx)
    signed_tx = append_signature_to_unsigned_tx(unsigned_tx, signature)
    return gql.stage(signed_tx), nonce, signed_tx


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
    uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid") is not None]
    receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
    nonce_dict = {}
    for i, record in enumerate(message.Records):
        try:
            receipt = receipt_dict.get(record.body.get("uuid"))
            logger.debug(f"UUID : {record.body.get('uuid')}")
            if not receipt:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is not exist in Receipt history", None
                logger.error(msg)
            elif receipt.tx_id:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is already treated with Tx : {receipt.tx_id}", None
                logger.warning(msg)
            else:
                receipt.tx_status = TxStatus.CREATED
                (success, msg, tx_id), nonce_dict[receipt.planet_id], signed_tx = process(
                    sess, record, nonce=nonce_dict.get(receipt.planet_id, None)
                )
                receipt.nonce = nonce_dict[receipt.planet_id]
                if success:
                    nonce_dict[receipt.planet_id] += 1
                receipt.tx_id = tx_id
                receipt.tx_status = TxStatus.STAGED
                receipt.tx = signed_tx.hex()
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
