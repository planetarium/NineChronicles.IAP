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
