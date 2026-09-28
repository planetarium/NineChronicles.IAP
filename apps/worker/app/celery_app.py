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
    # 결제 성공 신호는 왔는데 영수증이 안 생긴 건을 메운다.
    # 스토어 자동환불까지 72시간 여유가 있어 10분 주기면 충분하다.
    "reconcile-purchase-signal-every-10-minutes": {
        "task": "iap.reconcile_purchase_signal",
        "schedule": crontab(minute="*/10"),
        "options": {"queue": "background_job_queue"},
    },
}

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # (2026-09-29) 결과 백엔드를 태스크 발행 경로에서 뗀다. beat 데드락의 근본 원인이다.
    #   celery 의 send_task 는 `if not ignore_result: self.backend.on_task_call(...)` 이라,
    #   결과를 안 쓰겠다고 선언하면 발행 때마다 Redis 에 PubSub SUBSCRIBE 를 거는 경로가
    #   통째로 사라진다. 그 경로에서 이런 일이 벌어졌다(py-spy 스택으로 확인):
    #     send_task → on_task_call → PubSub.subscribe(SUBSCRIBE 전송) 도중
    #     GC 가 AsyncResult.__del__ 을 실행 → remove_pending_result → cancel_for →
    #     **같은 PubSub 커넥션에 UNSUBSCRIBE 재진입** → redis/client.py 에서 영구 블록.
    #   결과: iap-beat 이 파드 Running 상태 그대로 4시간 20분 정지(2026-09-28 23:45 KST~),
    #   그 사이 track_tx·retryer·voucher_grant 는 물론 **알람(status_monitor)까지 같이 죽어**
    #   아무도 눈치채지 못했다. seasonpass-beat 은 같은 원인으로 2일 18시간 멈춰 있었다.
    #   끌 수 있는 근거: 이 저장소에는 AsyncResult/.get()/.ready() 사용처가 하나도 없다.
    #   결과값은 celery 워커가 자기 로그에 찍고(flower 도 이벤트로 받는다) 백엔드를 안 거친다.
    task_ignore_result=True,
    # 위 설정이 발행 경로를 막아도 백엔드 객체 자체는 남는다. 원격 Redis(iwinv)라 끊김이
    #   상시이므로, 어떤 경로로든 붙을 때 무한 대기하지 않도록 타임아웃을 못 박는다.
    #   기본값은 전부 None = 영원히 블록이고, 그래서 위 데드락이 풀릴 길이 없었다.
    redis_socket_timeout=5.0,
    redis_socket_connect_timeout=5.0,
    redis_socket_keepalive=True,
    redis_retry_on_timeout=True,
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
