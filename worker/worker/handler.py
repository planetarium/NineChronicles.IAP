import dataclasses
import datetime
import json
import logging
import os
import traceback
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, joinedload, scoped_session, sessionmaker

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.enums import TxStatus
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.actions import create_unload_my_garages_action_plain_value
from common.utils.aws import fetch_secrets, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
CURRENT_PLANET = PlanetID.ODIN if os.environ.get("STAGE") == "mainnet" else PlanetID.ODIN_INTERNAL
GQL_URL = f"{os.environ.get('HEADLESS')}/graphql"

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)

planet_dict = {
    PlanetID.ODIN: {
        "agent": "0x1c2ae97380CFB4F732049e454F6D9A25D4967c6f",
        "avatar": "0x41aEFE4cdDFb57C9dFfd490e17e571705c593dDc"
    },
    PlanetID.HEIMDALL: {
        "agent": "0x1c2ae97380CFB4F732049e454F6D9A25D4967c6f",
        "avatar": "0x41aEFE4cdDFb57C9dFfd490e17e571705c593dDc"
    }
}


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
    gql = GQL(GQL_URL)
    if not nonce:
        nonce = gql.get_next_nonce(account.address)

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        .where(Product.id == message.body.get("product_id"))
    )

    planet_id: PlanetID = PlanetID(bytes(message.body["planet_id"], 'utf-8'))
    agent_address = message.body.get("agent_addr")
    avatar_address = message.body.get("avatar_addr")
    memo = json.dumps({"iap": {"g_sku": product.google_sku, "a_sku": product.apple_sku}})
    # Through bridge
    if planet_id != CURRENT_PLANET:
        agent_address = planet_dict[planet_id]["agent"]
        avatar_address = planet_dict[planet_id]["avatar"]
        memo = json.dumps([message.body.get("agent_addr"), message.body.get("avatar_addr"), memo])
    fav_data = [x.to_fav_data(agent_address=agent_address, avatar_address=avatar_address) for x in product.fav_list]

    item_data = [{
        "fungibleId": x.fungible_item_id,
        "count": x.amount
    } for x in product.fungible_item_list]

    unload_from_garage = create_unload_my_garages_action_plain_value(
        id=uuid.uuid1().hex,
        fav_data=fav_data,
        avatar_addr=avatar_address,
        item_data=item_data,
        memo=memo
    )

    unsigned_tx = create_unsigned_tx(
        planet_id=PlanetID.ODIN if os.environ.get("STAGE") == "mainnet" else PlanetID.ODIN_INTERNAL,
        public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
        plain_value=unload_from_garage, timestamp=datetime.datetime.utcnow() + datetime.timedelta(days=1)
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

    sess = None
    results = []
    try:
        sess = scoped_session(sessionmaker(bind=engine))
        uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid") is not None]
        receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        nonce = None
        for i, record in enumerate(message.Records):
            # Always 1 record in message since IAP sends one record at a time.
            # TODO: Handle exceptions and send messages to DLQ
            receipt = receipt_dict.get(record.body.get("uuid"))
            logger.debug(f"UUID : {record.body.get('uuid')}")
            success, msg, error = False, None, None
            if not receipt:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is not exist in Receipt history", None
                logger.error(msg)
            elif receipt.tx_id:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is already treated with Tx : {receipt.tx_id}", None
                logger.warning(msg)
            else:
                receipt.tx_status = TxStatus.CREATED
                try:
                    (success, msg, tx_id), nonce, signed_tx = process(sess, record, nonce=nonce)
                    receipt.nonce = nonce
                    if success:
                        nonce += 1
                    receipt.tx_id = tx_id
                    receipt.tx_status = TxStatus.STAGED
                    receipt.tx = signed_tx.hex()
                    sess.add(receipt)
                    sess.commit()
                except Exception as e:
                    error = traceback.format_exc()

            result = {
                "sqs_message_id": record.messageId,
                "success": success,
                "message": msg,
                "uuid": str(receipt.uuid) if receipt else None,
                "tx_id": str(receipt.tx_id) if receipt else None,
                "nonce": str(receipt.nonce) if receipt else None,
                "order_id": str(receipt.order_id) if receipt else None,
                "error": error
            }
            results.append(result)
            logger.info(json.dumps(result))
    finally:
        if sess is not None:
            sess.close()

    return results
