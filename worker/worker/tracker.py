import json
import os
import boto3
from collections import defaultdict
from typing import Optional, Tuple

from datetime import datetime, timezone, timedelta
from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common._graphql import GQL
from common.consts import GQL_DICT
from common.enums import TxStatus, ReceiptStatus
from common.models.receipt import Receipt
from common.utils.aws import fetch_secrets, fetch_parameter

STAGE = os.environ.get("STAGE")
DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]

SQS_URL = os.environ.get("SQS_URL")
sqs = boto3.client("sqs", region_name=os.environ.get("REGION_NAME"))

LIMIT = 200

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def process(url: str, tx_id: str) -> Tuple[str, Optional[TxStatus], Optional[str]]:
    client = GQL(url, HEADLESS_GQL_JWT_SECRET)
    query = dsl_gql(
        DSLQuery(
            client.ds.StandaloneQuery.transaction.select(
                client.ds.TransactionHeadlessQuery.transactionResult.args(
                    txId=tx_id
                ).select(
                    client.ds.TxResultType.txStatus,
                    client.ds.TxResultType.blockIndex,
                    client.ds.TxResultType.blockHash,
                    client.ds.TxResultType.exceptionNames,
                )
            )
        )
    )
    resp = client.execute(query)
    logger.debug(resp)

    if "errors" in resp:
        logger.error(f"GQL failed to get transaction status: {resp['errors']}")
        return tx_id, None, json.dumps(resp["errors"])

    try:
        return tx_id, TxStatus[resp["transaction"]["transactionResult"]["txStatus"]], json.dumps(
            resp["transaction"]["transactionResult"]["exceptionNames"])
    except:
        return tx_id, None, json.dumps(resp["transaction"]["transactionResult"]["exceptionNames"])


def track_tx(event, context):
    logger.info("Tracking unfinished transactions")
    sess = scoped_session(sessionmaker(bind=engine))
    receipt_list = sess.scalars(
        select(Receipt).where(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_((TxStatus.STAGED, TxStatus.INVALID))
        ).order_by(Receipt.id).limit(LIMIT)
    ).fetchall()

    now = datetime.now(tz=timezone.utc)
    created_receipt_list = sess.scalars(
        select(Receipt).where(
            Receipt.created_at <= now - timedelta(minutes=5),
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status == TxStatus.CREATED
        ).order_by(Receipt.id).limit(LIMIT)
    ).fetchall()

    if created_receipt_list:
        for created_receipt in created_receipt_list:
            msg = {
                "uuid": str(created_receipt.uuid),
            }

            sqs.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(msg))
        logger.info(f"Found created receipt [{len(created_receipt_list)}], re queuing.")

    result = defaultdict(list)
    for receipt in receipt_list:
        tx_id, tx_status, msg = process(GQL_DICT[receipt.planet_id], receipt.tx_id)
        if tx_status is not None:
            result[tx_status.name].append(tx_id)
            receipt.tx_status = tx_status
        if msg:
            receipt.msg = "\n".join([receipt.msg or "", msg])
        sess.add(receipt)
    sess.commit()

    logger.info(f"{len(receipt_list)} transactions are found to track status")
    for status, tx_list in result.items():
        if status is None:
            logger.error(f"{len(tx_list)} transactions are not able to track.")
            for tx in tx_list:
                logger.error(tx)
        elif status == TxStatus.STAGED:
            logger.info(f"{len(tx_list)} transactions are still staged.")
        else:
            logger.info(f"{len(tx_list)} transactions are changed to {status}")
