import datetime
import json
import logging
import os
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
GQL_URL = f"{os.environ.get('headless')}/graphql"

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)

planet_dict = {}
try:
    resp = requests.get(os.environ.get("PLANET_URL"))
    data = resp.json()
    GQL_URL = None
    for planet in data:
        if PlanetID(bytes(planet["id"], "utf-8")) == CURRENT_PLANET:
            GQL_URL = planet["rpcEndpoints"]["headless.gql"][0]
            planet_dict = {
                PlanetID(bytes(k, "utf-8")): v for k, v in planet["bridges"].items()
            }
except:
    # Fail over
    planet_dict = json.loads(os.environ.get("BRIDGE_DATA", "{}"))


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
        self.body = json.loads(self.body) if isinstance(self.body, str) else self.body


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]


def process(sess: Session, message: SQSMessageRecord, nonce: int = None) -> Tuple[Tuple[bool, str, Optional[str]], int]:
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
        id=uuid.uuid1().hex(),
        fav_data=fav_data,
        avatar_addr=avatar_address,
        item_data=item_data,
        memo=memo
    )

    unsigned_tx = create_unsigned_tx(
        planet_id=planet_id, public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
        plain_value=unload_from_garage, timestamp=datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    )
    signature = account.sign_tx(unsigned_tx)
    signed_tx = append_signature_to_unsigned_tx(unsigned_tx, signature)
    return gql.stage(signed_tx), nonce


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
        receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        nonce = None
        for i, record in enumerate(message.Records):
            # Always 1 record in message since IAP sends one record at a time.
            # TODO: Handle exceptions and send messages to DLQ
            receipt = receipt_dict.get(record.body.get("uuid"))
            if not receipt:
                success, msg, tx_id = False, f"{record.body.get('uuid')} is not exist in Receipt history", None
                logger.error(msg)
            else:
                receipt.tx_status = TxStatus.CREATED
                (success, msg, tx_id), nonce = process(sess, record, nonce=nonce)
                if success:
                    nonce += 1
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
