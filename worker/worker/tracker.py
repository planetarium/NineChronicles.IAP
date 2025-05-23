import json
import os
import time
import boto3
from collections import defaultdict
from typing import Optional, Tuple, Dict

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

LIMIT = 5

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)

# GQL 클라이언트 캐시
_gql_clients: Dict[str, GQL] = {}

def get_gql_client(url: str) -> GQL:
    """URL별로 캐싱된 GQL 클라이언트를 반환합니다."""
    if url not in _gql_clients:
        _gql_clients[url] = GQL(url, HEADLESS_GQL_JWT_SECRET)
    return _gql_clients[url]

def process(url: str, tx_id: str) -> Tuple[str, Optional[TxStatus], Optional[str]]:
    start_time = time.time()
    client = get_gql_client(url)
    logger.info(f"[TIME] GQL 클라이언트 준비: {(time.time() - start_time) * 1000:.1f}ms")

    query_start = time.time()
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
    logger.info(f"[TIME] GQL 쿼리 준비: {(time.time() - query_start) * 1000:.1f}ms")

    execute_start = time.time()
    resp = client.execute(query)
    logger.info(f"[TIME] GQL 쿼리 실행: {(time.time() - execute_start) * 1000:.1f}ms")
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
    start_time = time.time()
    logger.info("Tracking unfinished transactions")

    db_start = time.time()
    sess = scoped_session(sessionmaker(bind=engine))
    logger.info(f"[TIME] DB 세션 생성: {(time.time() - db_start) * 1000:.1f}ms")

    query_start = time.time()
    receipt_list = sess.scalars(
        select(Receipt).where(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_((TxStatus.STAGED, TxStatus.INVALID))
        ).order_by(Receipt.id).limit(LIMIT)
    ).fetchall()
    logger.info(f"[TIME] DB 쿼리 실행: {(time.time() - query_start) * 1000:.1f}ms")

    result = defaultdict(list)
    for idx, receipt in enumerate(receipt_list, 1):
        tx_start = time.time()
        tx_id, tx_status, msg = process(GQL_DICT[receipt.planet_id], receipt.tx_id)
        if tx_status is not None:
            result[tx_status.name].append(tx_id)
            receipt.tx_status = tx_status
        if msg:
            receipt.msg = "\n".join([receipt.msg or "", msg])
        sess.add(receipt)
        logger.info(f"[TIME] 트랜잭션 처리 {idx}/{len(receipt_list)}: {(time.time() - tx_start) * 1000:.1f}ms")

    commit_start = time.time()
    sess.commit()
    logger.info(f"[TIME] DB 커밋: {(time.time() - commit_start) * 1000:.1f}ms")

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

    logger.info(f"[TIME] 전체 실행 시간: {(time.time() - start_time) * 1000:.1f}ms")
