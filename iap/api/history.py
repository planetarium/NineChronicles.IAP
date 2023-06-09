import logging
import os
import random
from typing import Dict

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common.consts import HOST_LIST
from iap.dependencies import session

router = APIRouter(
    prefix="/history",
    tags=["Garage"],
)

stage = os.environ.get("STAGE", "development")
explorer_url = f"{random.choice(HOST_LIST[stage])}/graphql/explorer"


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
    print(block_data)


@router.get("/sync")
def sync_block_history(start: int = None, end: int = None, limit: int = 100, sess: Session = Depends(session)):
    if end is None:
        tip_query = """query { blockQuery { blocks(desc: true limit: 1) { index } } }"""
        resp = request(explorer_url, {"query": tip_query})
        end = resp["data"]["blockQuery"]["blocks"][0]["index"]

    if start is None:
        start = end - limit
        # Start from last block on DB
        # last_block = sess.execute(select(GarageHistory).order_by(desc(GarageHistory.block_index))).scalars().one()
        # if not last_block:
        #     start = end - limit

    query = f"""
    query {{ blockQuery {{ blocks(desc: true offset: {end - start} limit: {limit} ) {{ 
    hash index timestamp transactions {{ actions {{ json }} }} 
    }} }} }}
    """
    resp = request(explorer_url, {"query": query})

    block_list = resp["data"]["blockQuery"]["blocks"]
    for block in block_list:
        sync_block(block)

    return f"{len(block_list)} blocks synced: from {block_list[0]['index']} to {block_list[-1]['index']}"
