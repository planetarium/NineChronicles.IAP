import structlog
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import config

logger = structlog.get_logger(__name__)

task_exchange = Exchange("tasks", type="direct")

product_queue = Queue(
    "product_queue",
    exchange=task_exchange,
    routing_key="product_tasks",
)
background_job_queue = Queue(
    "background_job_queue",
    exchange=task_exchange,
    routing_key="background_job_tasks",
)


app = Celery("iap_worker", broker=config.broker_url, backend=config.result_backend)

beat_schedule = {
    "track-tx-every-minutes": {
        "task": "iap.track_tx",
        "schedule": crontab(minute="*/1"),
        "options": {"queue": "background_job_queue"},
    },
    "status-monitor-every-minutes": {
        "task": "iap.status_monitor",
        "schedule": crontab(minute="*/10"),
        "options": {"queue": "background_job_queue"},
    },
    "retryer-every-minutes": {
        "task": "iap.retryer",
        "schedule": crontab(minute="*/1"),
        "options": {"queue": "background_job_queue"},
    },
    "track-google-refund-every-minutes": {
        "task": "iap.track_google_refund",
        "schedule": crontab(minute="*/60"),
        "options": {"queue": "background_job_queue"},
    },
    # (PLD-1470) WEB(Stripe) 환불 → 바우처 회수 신호원. 15분 주기 근거는 track_web_refund 모듈 주석 참고
    #   (룩백 24h(config) × 15분 스케줄 = 96배 겹침: 홀드 72h 대비 충분히 촘촘하면서 하루 ~100 콜).
    #   ⚠️ */15 가 아니라 7/22/37/52 분으로 어긋내는 이유: background_job_queue 워커가 concurrency=1 이라
    #      grant(*/2)·reconcile(*/5) 과 매 정각마다 겹치면 서로 큐에서 기다린다(Stripe I/O 대기가 길다).
    "track-web-refund-every-15-minutes": {
        "task": "iap.track_web_refund",
        "schedule": crontab(minute="7,22,37,52"),
        "options": {"queue": "background_job_queue"},
    },
    "voucher-grant-every-2-minutes": {
        "task": "iap.voucher_grant",
        "schedule": crontab(minute="*/2"),
        "options": {"queue": "background_job_queue"},
    },
    "voucher-reconcile-every-5-minutes": {
        "task": "iap.voucher_reconcile",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "background_job_queue"},
    },
}

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=4,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_queues=(product_queue, background_job_queue),
    task_default_queue="product_queue",
    task_default_exchange="tasks",
    task_default_routing_key="product_tasks",
    task_create_missing_queues=True,
    task_default_delivery_mode="persistent",
    worker_direct=True,
    beat_schedule=beat_schedule,
)

app.autodiscover_tasks(["app.tasks"])


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    logger.info("Setting up periodic tasks")


@app.task(bind=True)
def debug_task(self):
    """Task for debugging purposes"""
    logger.info(f"Request: {self.request!r}")
    return "Debug task completed"
