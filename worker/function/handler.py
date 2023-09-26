import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import Session, joinedload, scoped_session, sessionmaker

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.enums import TxStatus
from common.models.product import Product
from common.models.receipt import Receipt
from common.models.sign import SignHistory
from common.utils.aws import fetch_secrets, fetch_kms_key_id, fetch_parameter
from common.utils.google import Spreadsheet
from schema.sqs import SQSMessageRecord, SQSMessage

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
GOOGLE_CREDENTIAL = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_GOOGLE_CREDENTIAL",
    True
)["Value"]

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)



def process_iap(sess: Session, gql: GQL, account: Account, history: SignHistory) -> Tuple[bool, str, Optional[str]]:
    request_data = json.loads(history.data)
    if not request_data:
        return False, "No request data", None

    product = sess.scalar(
        select(Product)
        .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
        .where(Product.id == request_data.get("product_id"))
    )

    fav_data = [{
        "balanceAddr": request_data.get("agent_addr"),
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
        "unload_from_garage", pubkey=account.pubkey, nonce=gql.nonce,
        fav_data=fav_data, avatar_addr=request_data.get("avatar_addr"), item_data=item_data,
    )
    signature = account.sign_tx(unsigned_tx)
    signed_tx = gql.sign(unsigned_tx, signature)
    return gql.stage(signed_tx)


def process_golden_dust(sess: Session, message: SQSMessageRecord) -> Tuple[bool, str, Optional[str]]:
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region_name}")


def collect(sess, message: SQSMessage, account: Account, gql: GQL) -> List[SignHistory]:
    print(f"{len(message.Records)} records to collect")
    next_nonce = gql.get_next_nonce(account.address)
    prev_nonce = sess.scalar(select(SignHistory.nonce).order_by(desc(SignHistory.nonce)).limit(1))
    nonce = max(next_nonce, (prev_nonce or -1) + 1)
    print(f"Use nonce from {nonce}")
    history_list = []
    for record in message.Records:
        history_list.append(SignHistory(
            request_type=record.body["type"], data=json.dumps(record.body.get("data", {})), nonce=nonce
        ))
        nonce += 1
    sess.add_all(history_list)
    sess.commit()
    sess.refresh_all(history_list)
    print(f"{len(history_list)} nonce used. Next nonce is {nonce}")
    return history_list


def handle(event, context):
    """
    Receive purchase/buyer data from IAP server and create Tx to 9c.

    Receiving data
    - inventory_addr (str): Target inventory address to receive items
    - product_id (int): Target product ID to send to buyer
    - uuid (uuid): UUID of receipt-tx pair managed by DB
    """
    message = SQSMessage(Records=event.get("Records", []))
    logging.debug("=== Message from SQS ====\n")
    logging.debug(message)
    logging.debug("=== Message end ====\n")

    sess = None
    golden_dust_worksheet = Spreadsheet(GOOGLE_CREDENTIAL, os.environ.get("GOLDEN_DUST_WORK_SHEET_ID"))
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region_name}")
    account = Account(fetch_kms_key_id(stage, region_name))
    gql = GQL()

    try:
        sess = scoped_session(sessionmaker(bind=engine))
        # uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid") is not None]
        # receipt_dict = {str(x.uuid): x for x in sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        history_list = collect(sess, message, account, gql)
        print(history_list)
        # for i, record in enumerate(message.Records):
        #     # Always 1 record in message since IAP sends one record at a time.
        #     # TODO: Handle exceptions and send messages to DLQ
        #
        #     receipt = receipt_dict.get(record.body.get("uuid"))
        #     if not receipt:
        #         success, msg, tx_id = False, f"{record.body.get('uuid')} is not exist in Receipt history", None
        #         logger.error(msg)
        #     else:
        #         receipt.tx_status = TxStatus.CREATED
        #         success, msg, tx_id = process(sess, record)
        #         receipt.tx_id = tx_id
        #         receipt.tx_status = TxStatus.STAGED
        #         sess.add(receipt)
        #         sess.commit()
        #     print(
        #         f"{i + 1}/{len(message.Records)} : {'Success' if success else 'Fail'} with message: "
        #         f"\n\tTx. ID: {tx_id}"
        #         f"\n\t{msg}"
        #     )
    finally:
        if sess is not None:
            sess.close()
