import logging
import os
from collections import defaultdict
from typing import Optional, Tuple

from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

from common.enums import TxStatus
from common.models.receipt import Receipt
from common.utils import fetch_secrets
from common._graphql import GQL

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def process(tx_id: str) -> Tuple[str, Optional[TxStatus]]:
    client = GQL()
    query = dsl_gql(
        DSLQuery(
            client.ds.StandaloneQuery.transaction.select(
                client.ds.TransactionHeadlessQuery.transactionResult.args(
                    txId=tx_id
                ).select(
                    client.ds.TxResultType.txStatus,
                    client.ds.TxResultType.blockIndex,
                    client.ds.TxResultType.blockHash,
                    client.ds.TxResultType.exceptionName,
                )
            )
        )
    )
    resp = client.execute(query)
    logging.debug(resp)

    if "errors" in resp:
        logging.error(f"GQL failed to get transaction status: {resp['errors']}")
        return tx_id, None

    try:
        return tx_id, TxStatus[resp["transaction"]["transactionResult"]["txStatus"]]
    except:
        return tx_id, None


def track_tx(event, context):
    logging.info("Tracking unfinished transactions")
    sess = scoped_session(sessionmaker(bind=engine))
    receipt_list = sess.scalars(select(Receipt).where(Receipt.tx_status == TxStatus.STAGED)).fetchall()
    result = defaultdict(list)
    for receipt in receipt_list:
        tx_id, tx_status = process(receipt.tx_id)
        result[tx_status.name].append(tx_id)
        receipt.tx_status = tx_status
        sess.add(receipt)

    sess.commit()

    logging.info(f"{len(receipt_list)} transactions are found to track status")
    for status, tx_list in result.items():
        if status is None:
            logging.error(f"{len(tx_list)} transactions are not able to track.")
            for tx in tx_list:
                logging.error(tx)
        elif status == TxStatus.STAGED:
            logging.info(f"{len(tx_list)} transactions are still staged.")
        else:
            logging.info(f"{len(tx_list)} transactions are changed to {status}")
