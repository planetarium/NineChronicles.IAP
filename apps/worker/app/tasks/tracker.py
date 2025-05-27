import json
from collections import defaultdict
from typing import Optional, Tuple, Dict

import structlog
from gql.dsl import DSLQuery, dsl_gql
from shared._graphql import GQL
from shared.enums import ReceiptStatus, TxStatus
from shared.models.receipt import Receipt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

LIMIT = 5

engine = create_engine(config.pg_dsn, pool_size=5, max_overflow=5)

# GQL 클라이언트 캐시
_gql_clients: Dict[str, GQL] = {}

def get_gql_client(url: str) -> GQL:
    """URL별로 캐싱된 GQL 클라이언트를 반환합니다."""
    if url not in _gql_clients:
        _gql_clients[url] = GQL(url, HEADLESS_GQL_JWT_SECRET)
    return _gql_clients[url]

def process(url: str, tx_id: str) -> Tuple[str, Optional[TxStatus], Optional[str]]:
    client = GQL(url, config.headless_jwt_secret)
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
        return (
            tx_id,
            TxStatus[resp["transaction"]["transactionResult"]["txStatus"]],
            json.dumps(resp["transaction"]["transactionResult"]["exceptionNames"]),
        )
    except:
        return (
            tx_id,
            None,
            json.dumps(resp["transaction"]["transactionResult"]["exceptionNames"]),
        )


@app.task(
    name="iap.track_tx",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def track_tx(self) -> str:
    logger.info("Tracking unfinished transactions")

    db_start = time.time()
    sess = scoped_session(sessionmaker(bind=engine))
    logger.info(f"[TIME] DB 세션 생성: {(time.time() - db_start) * 1000:.1f}ms")

    query_start = time.time()
    receipt_list = sess.scalars(
        select(Receipt)
        .where(
            Receipt.status == ReceiptStatus.VALID,
            Receipt.tx_status.in_((TxStatus.STAGED, TxStatus.INVALID)),
        )
        .order_by(Receipt.id)
        .limit(LIMIT)
    ).fetchall()
    logger.info(f"[TIME] DB 쿼리 실행: {(time.time() - query_start) * 1000:.1f}ms")

    result = defaultdict(list)
    for receipt in receipt_list:
        tx_id, tx_status, msg = process(
            config.converted_gql_url_map[receipt.planet_id], receipt.tx_id
        )
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
