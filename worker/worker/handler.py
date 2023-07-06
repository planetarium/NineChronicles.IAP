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
from common.enums import TxStatus
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils import fetch_secrets, fetch_kms_key_id

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

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

    def __post_init__(self):
        self.body = json.loads(self.body) if type(self.body) == str else self.body


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]


def process(sess: Session, message: SQSMessageRecord) -> Tuple[bool, str, Optional[str]]:
    stage = os.environ.get("STAGE", "development")
    region = os.environ.get("REGION_NAME", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region}")
    account = Account(fetch_kms_key_id(stage, region))
    gql = GQL()
    nonce = gql.get_next_nonce(account.address)

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
    )

    fav_data = [{
        "balanceAddr": message.body.get("agent_addr"),
        "fungibleAssetValue": {
            "currency": x.currency.name,
            "majorUnit": x.amount,
            "minorUnit": 0
        }
    } for x in product.fav_list]

    item_data = [{
        "fungibleId": x.fungible_item_id,
        "count": x.amount
    } for x in product.fungible_item_list]

    unsigned_tx = gql.create_action(
        "unload_from_garage", pubkey=account.pubkey, nonce=nonce,
        fav_data=fav_data, avatar_addr=message.body.get("avatar_addr"), item_data=item_data,
    )
    signature = account.sign_tx(unsigned_tx)
    signed_tx = gql.sign(unsigned_tx, signature)
    return gql.stage(signed_tx)


def handle(event, context):
    """
    Receive purchase/buyer data from IAP server and create Tx to 9c.

    Receiving data
    - inventory_addr (str): Target inventory address to receive items
    - product_id (int): Target product ID to send to buyer
    - uuid (uuid): UUID of receipt-tx pair managed by DB
    """
    message = SQSMessage(Records=event.get("Records", {}))
    logging.debug("=== Message from SQS ====\n")
    logging.debug(message)
    logging.debug("=== Message end ====\n")

    sess = None
    try:
        sess = scoped_session(sessionmaker(bind=engine))
        uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid") is not None]
        print(uuid_list)
        receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        print(receipt_dict)
        for i, record in enumerate(message.Records):
            # Always 1 record in message since IAP sends one record at a time.
            # TODO: Handle exceptions and send messages to DLQ
            receipt = receipt_dict.get(record.body.get("uuid"))
            if not receipt:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is not exist in Receipt history", None
                logger.error(msg)
            else:
                receipt.tx_status = TxStatus.CREATED
                success, msg, tx_id = process(sess, record)
                receipt.tx_id = tx_id
                receipt.tx_status = TxStatus.STAGED
                sess.add(receipt)
                sess.commit()
            print(
                f"{i + 1}/{len(message.Records)} : {'Success' if success else 'Fail'} with message: "
                f"\n\tTx. ID: {tx_id}"
                f"\n\t{msg}"
            )
    finally:
        if sess is not None:
            sess.close()
