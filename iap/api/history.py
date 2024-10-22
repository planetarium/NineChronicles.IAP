import json
import os
import random
from dataclasses import dataclass
from typing import Dict

import requests
from fastapi import APIRouter, HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common import logger
from common.consts import HOST_LIST

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
