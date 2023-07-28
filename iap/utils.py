import datetime
import os
from typing import List, Optional, Dict

from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import func, distinct, select, Date, cast

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.enums import ReceiptStatus
from common.models.product import FungibleItemProduct
from common.models.receipt import Receipt
from common.utils import fetch_kms_key_id


def get_purchase_count(sess, agent_addr: str, product_id: int, hour_limit: int) -> int:
    """
    Scan purchase history and get purchase count in given time limit.

    :param sess: DB Session
    :param agent_addr: 9c Agent address
    :param product_id: Target product ID to scan.
    :param hour_limit: purchase history limit in hours. 24 for daily limit, 168(24*7) for weekly limit
    :return:
    """
    # NOTE: Subtract 24 hours from incoming hour_limit.
    #  Because last 24 hours means today. Using `datetime.date()` function, timedelta -24 hours makes yesterday.
    start = (datetime.datetime.utcnow() - datetime.timedelta(hours=hour_limit-24)).date()
    purchase_count = (
        sess.query(func.count(Receipt.id)).filter_by(product_id=product_id, agent_addr=agent_addr)
        .filter(Receipt.status.in_(
            (ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.VALID)
        ))
        .filter(cast(Receipt.purchased_at, Date) >= start)
    ).scalar()
    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {purchase_count} times in {hour_limit} hours from {start}"
    )
    return purchase_count


def get_iap_garage(sess) -> List[Optional[Dict]]:
    """
    Get NCG balance and fungible item count of IAP address.
    :return:
    """
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    client = GQL()
    account = Account(fetch_kms_key_id(stage, region_name))

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
        raise Exception(msg)

    return resp["stateQuery"]["garages"]["fungibleItemGarages"]
