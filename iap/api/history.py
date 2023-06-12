import logging
import os
import random
from typing import Dict

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common.consts import HOST_LIST
from common.models.garage import GarageActionHistory
from iap.dependencies import session

router = APIRouter(
    prefix="/history",
    tags=["Garage"],
)

stage = os.environ.get("STAGE", "development")
explorer_url = f"{random.choice(HOST_LIST[stage])}/graphql/explorer"
logger = logging.getLogger("iap_logger")


def request(url: str, data: Dict) -> Dict:
    resp = requests.post(url, json=data)
    if resp.status_code != 200:
        err = f"Block tip query to {explorer_url} failed with status code {resp.status_code}"
        logging.error(err)
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=err)
    r = resp.json()
    if "errors" in r:
        err = f"Block tip query failed with error : {r['errors']}"
        logging.error(err)
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=err)
    return r


def sync_block(block_data):
    # TODO
    print(block_data)
    print("=" * 32)


@router.get("/sync")
def sync_block_history(start: int = None, end: int = None, limit: int = 100, sess: Session = Depends(session)):
    tip_query = """query { blockQuery { blocks(desc: true limit: 1) { index } } }"""
    resp = request(explorer_url, {"query": tip_query})
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
    hash index timestamp transactions {{ actions {{ json }} }} 
    }} }} }}
    """
    resp = request(explorer_url, {"query": query})

    block_list = resp["data"]["blockQuery"]["blocks"]
    logger.info(f"{len(block_list)} blocks are fetched")
    if len(block_list) == 0:
        msg = f"No block containing transactions found between {start} and {end}"
        logger.warning(msg)
        return msg

    for block in block_list:
        sync_block(block)

    result = f"{len(block_list)} blocks synced: from {block_list[-1]['index']} to {block_list[0]['index']}"
    logging.info(result)
    return result
