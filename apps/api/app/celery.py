import json
from typing import Any, Dict

import structlog
from celery import Celery

from app.config import config

logger = structlog.get_logger(__name__)

celery_app = Celery(
    "iap_worker",
    broker=str(config.broker_url),
    backend=config.result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # (2026-09-29) 워커와 같은 이유로 결과 백엔드를 발행 경로에서 뗀다 —
    #   근거·사고 경위는 apps/worker/app/celery_app.py 의 같은 설정 주석에 있다.
    #   여기가 더 급한 이유: send_to_worker() 는 **구매 요청을 처리하는 중에** 불린다.
    #   워커의 beat 이 멈추면 지급이 밀리는 선에서 끝나지만, 이 프로세스가 같은
    #   PubSub 재진입에 걸리면 그 순간 유저의 결제 요청 자체가 응답 없이 매달린다.
    #   아래 send_task 가 쓰는 task.id 는 로컬에서 만들어지므로 이 설정과 무관하다.
    task_ignore_result=True,
    redis_socket_timeout=5.0,
    redis_socket_connect_timeout=5.0,
    redis_socket_keepalive=True,
    redis_retry_on_timeout=True,
    timezone="UTC",
    enable_utc=True,
)


def send_to_worker(task_name: str, message: Dict[str, Any]) -> str:
    """
    Send a task to the Celery worker

    Args:
        task_name: The name of the task to execute
        message: The message data to send with the task

    Returns:
        str: Task ID
    """
    try:
        logger.info(f"Sending task to Celery worker: {task_name}", message=message)
        queue = "product_queue"

        task = celery_app.send_task(task_name, args=[message], queue=queue)
        logger.info(
            f"Task sent to Celery worker: {task_name}", task_id=task.id, queue=queue
        )
        return task.id
    except Exception as exc:
        logger.error(
            f"Error sending task to Celery worker: {task_name}",
            message=message,
            exc_info=exc,
        )
        raise
