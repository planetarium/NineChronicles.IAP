import json
import time
from collections import defaultdict
from typing import Dict, Optional, Tuple

import structlog
from gql.dsl import DSLQuery, dsl_gql
from shared._graphql import GQL
from shared.enums import ReceiptStatus, Store, TxStatus
from shared.models.receipt import Receipt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

LIMIT = 50

engine = create_engine(
    config.pg_dsn,
    pool_size=10,  # 기본 연결 수 증가
    max_overflow=20,  # 오버플로우 연결 수 증가
    pool_timeout=60,  # 연결 타임아웃 증가
    pool_recycle=3600,  # 연결 재사용 시간 (1시간)
    pool_pre_ping=True  # 연결 상태 확인
)

# GQL 클라이언트 캐시
_gql_clients: Dict[str, GQL] = {}


def get_gql_client(url: str) -> GQL:
    """URL별로 캐싱된 GQL 클라이언트를 반환합니다."""
    if url not in _gql_clients:
        _gql_clients[url] = GQL(url, config.headless_jwt_secret)
    return _gql_clients[url]


def process(url: str, tx_id: str) -> Tuple[str, Optional[TxStatus], Optional[str]]:
    client = GQL(url, config.headless_jwt_secret)
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

    execute_start = time.time()
    resp = client.execute(query)

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

    try:
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

        commit_start = time.time()
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

    finally:
        if sess is not None:
            sess.close()
            logger.debug("track_tx session closed successfully")
