import os
from typing import List

from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import select, distinct

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.models.garage import GarageItemStatus
from common.models.product import FungibleItemProduct
from common.utils.aws import fetch_kms_key_id


def update_iap_garage(sess):
    client = GQL()
    account = Account(fetch_kms_key_id(os.environ.get("STAGE", "development"), os.environ.get("REGION_NAME")))
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
        return {}

    data = {x["fungibleItemId"]: x["count"] for x in resp["stateQuery"]["garages"]["fungibleItemGarages"]}
    target_garages = sess.scalars(
        select(GarageItemStatus).where(GarageItemStatus.address == account.address)
    ).all()
    for garage_status in target_garages:
        amount = data.pop(garage_status.fungible_id, 0)
        garage_status.amount = amount or 0
    sess.add_all(target_garages)
    logger.info(f"{len(target_garages)} garages are updated")

    for fungible_id, amount in data.items():
        sess.add(GarageItemStatus(address=account.address, fungible_id=fungible_id, amount=amount or 0))
    logger.info(f"{len(data)} garages are added")
    return data


def get_iap_garage(sess) -> List[GarageItemStatus]:
    """
    Get NCG balance and fungible item count of IAP address.
    :return:
    """
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    account = Account(fetch_kms_key_id(stage, region_name))

    fungible_id_list = sess.scalars(select(distinct(FungibleItemProduct.fungible_item_id))).fetchall()
    return sess.scalars(
        select(GarageItemStatus).where(
            GarageItemStatus.address == account.address,
            GarageItemStatus.fungible_id.in_(fungible_id_list)
        )
    )
