import json
import os
from collections import defaultdict
from typing import Optional, Tuple

import requests
from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common._graphql import GQL
from common.enums import TxStatus
from common.models.receipt import Receipt
from common.utils.aws import fetch_secrets
from common.utils.garage import update_iap_garage
from common.utils.receipt import PlanetID

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

resp = requests.get(os.environ.get("PLANET_URL"))
data = resp.json()
planet_dict = {
    PlanetID(bytes(x["id"], "utf-8")): x["rpcEndpoints"]["headless.gql"][0]
    for x in data
}

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def process(planet_id: PlanetID, tx_id: str) -> Tuple[str, Optional[TxStatus], Optional[str]]:
    client = GQL(planet_dict[planet_id])
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
        return tx_id, None

    try:
        return tx_id, TxStatus[resp["transaction"]["transactionResult"]["txStatus"]]
    except:
        return tx_id, None


def track_tx(event, context):
    logger.info("Tracking unfinished transactions")
    sess = scoped_session(sessionmaker(bind=engine))
    receipt_list = sess.scalars(select(Receipt).where(Receipt.tx_status == TxStatus.STAGED)).fetchall()
    result = defaultdict(list)
    for receipt in receipt_list:
        tx_id, tx_status, msg = process(PlanetID(receipt.planet_id), receipt.tx_id)
        result[tx_status.name].append(tx_id)
        receipt.tx_status = tx_status
        sess.add(receipt)
    update_iap_garage(sess)
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
