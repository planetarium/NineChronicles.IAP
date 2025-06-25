from typing import Dict, List, Optional, Tuple

import requests
import structlog
from shared.schemas.message import SendProductMessage
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from app.celery_app import app
from app.config import config

logger = structlog.get_logger(__name__)

engine = create_engine(config.pg_dsn, pool_size=5, max_overflow=5)


def get_pending_receipts(session) -> List[Dict]:
    """CREATED, STAGED 또는 INVALID 상태이고 tx가 있는 영수증 중 생성된 지 10분 이상 지난 것들을 nonce 오름차순으로 조회"""
    query = text(
        """
        SELECT id, tx, planet_id, nonce, tx_status, created_at 
        FROM receipt 
        WHERE tx_status IN ('CREATED', 'INVALID') 
        AND tx IS NOT NULL 
        AND created_at < NOW() - INTERVAL '10 minutes'
        """
    )

    result = []
    for row in session.execute(query):
        result.append(
            {
                "id": row[0],
                "tx": row[1],
                "planet_id": row[2],
                "nonce": row[3],
                "tx_status": row[4],
                "created_at": row[5],
            }
        )

    return result


def get_null_tx_status_receipts(session) -> List[Dict]:
    """tx_status가 NULL이고 특정 조건에 맞는 영수증들을 조회"""
    query = text(
        """
        SELECT r.uuid
        FROM receipt r
        JOIN product p ON p.id = r.product_id
        WHERE r.tx_status IS NULL
        AND r.created_at <= '2025-06-25 17:17'
        AND r.created_at >= '2025-01-01'
        AND p.google_sku NOT LIKE '%pass%'
        AND r.status = 'VALID'
        ORDER BY r.id DESC
        """
    )

    result = []
    for row in session.execute(query):
        result.append(
            {
                "uuid": row[0],
            }
        )

    return result


def send_uuid_to_worker(uuid: str) -> bool:
    """워커에 uuid만 보내서 처리하도록 요청"""
    try:
        send_product_message = SendProductMessage(uuid=uuid)
        task = app.send_task(
            "iap.send_product",
            args=[send_product_message.model_dump()],
            queue="product_queue",
        )
        logger.info(f"UUID {uuid}를 워커에 전송했습니다. task_id: {task.id}")
        return True
    except Exception as e:
        logger.error(f"UUID {uuid} 워커 전송 실패: {e}")
        return False


def stage_transaction(planet_id: str, tx: str) -> Optional[str]:
    """GraphQL API로 트랜잭션 제출"""
    endpoint = config.gql_url_map.get(planet_id)
    if not endpoint:
        logger.error(f"알 수 없는 planet_id: {planet_id}")
        return None

    query = (
        """
    mutation {
      stageTransaction(payload: "%s")
    }
    """
        % tx
    )

    try:
        response = requests.post(endpoint, json={"query": query})

        if response.status_code != 200:
            logger.error(f"API 요청 실패: {response.status_code} - {response.text}")
            return None

        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL 오류: {data['errors']}")
            return None

        return data["data"]["stageTransaction"]

    except Exception as e:
        logger.error(f"요청 중 오류 발생: {e}")
        return None


def update_receipt_status(session, receipt_id: int, tx_id: str):
    """영수증 상태 업데이트"""
    query = text(
        "UPDATE receipt SET tx_status = 'STAGED', tx_id = :tx_id WHERE id = :receipt_id"
    )
    session.execute(query, {"tx_id": tx_id, "receipt_id": receipt_id})
    session.commit()
    logger.info(f"receipt_id={receipt_id}의 상태를 STAGED로 업데이트, tx_id={tx_id}")


@app.task(
    name="iap.retryer",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    queue="background_job_queue",
)
def retryer(self):
    """보류 중인 영수증 처리"""

    sess = scoped_session(sessionmaker(bind=engine))

    try:
        receipts = get_pending_receipts(sess)
        logger.info(
            f"처리할 영수증 {len(receipts)}개 발견 (생성된 지 10분 이상 지난 것들만)"
        )

        if not receipts:
            logger.info("처리할 영수증이 없습니다.")
            return

        created_count = sum(1 for r in receipts if r["tx_status"] == "CREATED")
        staged_count = sum(1 for r in receipts if r["tx_status"] == "STAGED")
        invalid_count = sum(1 for r in receipts if r["tx_status"] == "INVALID")
        logger.info(
            f"CREATED 상태: {created_count}개, STAGED 상태: {staged_count}개, INVALID 상태: {invalid_count}개"
        )

        logger.info("nonce 오름차순으로 처리를 시작합니다.")

        for receipt in receipts:
            receipt_id = receipt["id"]
            tx = receipt["tx"]
            planet_id = bytes(receipt["planet_id"]).decode()
            tx_status = receipt["tx_status"]
            nonce = receipt["nonce"]
            created_at = receipt["created_at"]

            logger.info(
                f"영수증 {receipt_id} 처리 중 (planet_id: {planet_id}, 현재 상태: {tx_status}, nonce: {nonce}, 생성 시간: {created_at})"
            )

            tx_id = stage_transaction(planet_id, tx)

            if tx_id:
                update_receipt_status(sess, receipt_id, tx_id)
            else:
                logger.info(f"영수증 {receipt_id}에 대한 트랜잭션 스테이징 실패")

        null_tx_receipts = get_null_tx_status_receipts(sess)
        logger.info(f"tx_status가 NULL인 영수증 {len(null_tx_receipts)}개 발견")

        if null_tx_receipts:
            logger.info("tx_status가 NULL인 영수증들을 워커에 전송합니다.")

            success_count = 0
            for receipt in null_tx_receipts:
                uuid = receipt["uuid"]

                logger.info(f"영수증 {receipt_id} (uuid: {uuid} 워커 전송 중")

                if send_uuid_to_worker(uuid):
                    success_count += 1

            logger.info(
                f"워커 전송 완료: {success_count}/{len(null_tx_receipts)}개 성공"
            )

    finally:
        sess.close()
