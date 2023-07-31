import logging
import os
from collections import defaultdict
from typing import Optional, Tuple

from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import create_engine, select, distinct
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.enums import TxStatus
from common.models.garage import GarageItemStatus
from common.models.product import FungibleItemProduct
from common.models.receipt import Receipt
from common.utils import fetch_secrets, fetch_kms_key_id

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def update_iap_garage(sess):
    client = GQL()
    account = Account(fetch_kms_key_id(os.environ.get("STAGE"), os.environ.get("REGION_NAME")))
    fungible_id_list = sess.scalars(select(distinct(FungibleItemProduct.fungible_item_id))).fetchall()
    query = dsl_gql(
        DSLQuery(
            client.ds.StandaloneQuery.stateQuery.select(
                client.ds.StateQuery.garages.args(
                    agentAddr=account.address,
                    fungibleItemIds=fungible_id_list,
                ).select(
                    client.ds.GaragesType.agentAddr,
                    client.ds.GaragesType.fungibleItemGarages.select(
                        client.ds.FungibleItemGarageWithAddressType.fungibleItemId,
                        client.ds.FungibleItemGarageWithAddressType.count,
                    )
                )
            )
        )
    )
    resp = client.execute(query)
    if "errors" in resp:
        msg = f"GQL failed to get IAP garage: {resp['errors']}"
        logger.error(msg)
        # TODO: Send message to recognize
        # raise Exception(msg)
    else:
        data = {x["fungibleItemId"]: x["count"] for x in resp["stateQuery"]["garages"]["fungibleItemGarages"]}
        target_garages = sess.scalars(
            select(GarageItemStatus).where(GarageItemStatus.address == account.address)
        ).all()
        for garage_status in target_garages:
            garage_status.amount = data.pop(garage_status.fungible_id, 0)
        sess.add_all(target_garages)
        logger.info(f"{len(target_garages)} garages are updated")

        for fungible_id, amount in data.items():
            sess.add(GarageItemStatus(address=account.address, fungible_id=fungible_id, amount=amount))
        logger.info(f"{len(data)} garages are added")


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
    update_iap_garage(sess)

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
