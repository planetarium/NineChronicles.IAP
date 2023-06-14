import json
import os
import random
from dataclasses import dataclass
from typing import Dict

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common import logger
from common.consts import HOST_LIST
from common.models.garage import GarageActionHistory
from iap.dependencies import session

router = APIRouter(
    prefix="/history",
    tags=["Garage"],
)

STAGE = os.environ.get("STAGE", "development")
EXPLORER_URL = f"{random.choice(HOST_LIST[STAGE])}/graphql/explorer"


@dataclass
class LoadSchema:
    pass


@dataclass
class DeliverSchema:
    pass


@dataclass
class UnloadSchema:
    pass


def request(url: str, data: Dict) -> Dict:
    resp = requests.post(url, json=data)
    if resp.status_code != 200:
        err = f"Block tip query to {EXPLORER_URL} failed with status code {resp.status_code}"
        logger.error(err)
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=err)
    r = resp.json()
    if "errors" in r:
        err = f"Block tip query failed with error : {r['errors']}"
        logger.error(err)
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=err)
    return r


def process_load(data: dict):
    pass


def process_deliver(data: dict):
    pass


def process_unload(data: dict):
    pass


def sync_block(block_data):
    # TODO
    GARAGE_ACTION_TYPES = {
        # Load
        "load_into_my_garages": process_load,
        # Deliver
        "deliver_to_others_garages": process_deliver,
        # Unload
        "unload_from_my_garages": process_unload,
    }
    logger.info(f"Process Block {block_data['index']} :: {block_data['hash']}")
    logger.info(f"{len(block_data['transactions'])} Transactions")
    cnt = 0
    # print(block_data)
    # TODO: Need transaction result
    for tx in block_data["transactions"]:
        for action in tx["actions"]:
            json_action = json.loads(action["json"].replace("\\uFEFF", ""))
            if json_action["type_id"].startswith("transfer_asset"):
                logger.info(json_action["values"])
                continue
            if json_action["type_id"] in GARAGE_ACTION_TYPES:
                cnt += 1
                logger.debug(json_action["values"])
                if action["type_id"].startswith("load_into_my_garages"):
                    process_load(json_action["values"])
                elif action["type_id"].startswith("deliver_to_others_garages"):
                    process_deliver(json_action["values"])
                elif action["type_id"].startswith("unload_from_my_garages"):
                    process_unload(json_action["values"])
                else:
                    logger.error(f"{json_action['type_id']} is not valid action type")

        logger.info("=" * 32)
    logger.info(f"{cnt} actions are processed")


@router.get("/sync")
def sync_block_history(start: int = None, end: int = None, limit: int = 100, sess: Session = Depends(session)):
    tip_query = """query { blockQuery { blocks(desc: true limit: 1) { index } } }"""
    resp = request(EXPLORER_URL, {"query": tip_query})
    tip = resp["data"]["blockQuery"]["blocks"][0]["index"]

    if end is None:
        end = tip

    if start is None:
        # Start from last block on DB
        try:
            last_block = sess.execute(
                select(GarageActionHistory).order_by(desc(GarageActionHistory.block_index))
            ).scalars().one()
        except NoResultFound:
            last_block = None

        if not last_block:
            start = end - limit

    logger.info(f"{start} ~ {end}, limit {limit}")

    query = f"""
    query {{ blockQuery {{ blocks(desc: true offset: {tip - start} limit: {limit}) {{ 
    hash index timestamp transactions {{ id signer timestamp actions {{ json }} }} 
    }} }} }}
    """
    resp = request(EXPLORER_URL, {"query": query})

    block_list = resp["data"]["blockQuery"]["blocks"]
    logger.info(f"{len(block_list)} blocks are fetched")
    if len(block_list) == 0:
        msg = f"No block containing transactions found between {start} and {end}"
        logger.warning(msg)
        return msg

    for block in block_list:
        sync_block(block)

    result = f"{len(block_list)} blocks synced: from {block_list[-1]['index']} to {block_list[0]['index']}"
    logger.info(result)
    return result
