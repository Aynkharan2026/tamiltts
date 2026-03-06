from celery import Celery
from app.config import settings

celery_app = Celery(
    "tamiltts",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.autodiscover_tasks(["app.worker"])

celery_app.conf.beat_schedule = {
    "retry-pending-webhooks": {
        "task": "app.worker.tasks.retry_pending_webhooks",
        "schedule": 300.0,  # every 5 minutes
    },
}
