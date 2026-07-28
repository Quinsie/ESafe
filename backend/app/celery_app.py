from datetime import UTC, datetime
from typing import Any

from celery import Celery

from app.config import Settings, get_settings


def create_celery_app(settings: Settings) -> Celery:
    application = Celery(
        "esafe",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    application.conf.update(
        task_default_queue=settings.celery_queue,
        task_routes={"esafe.*": {"queue": settings.celery_queue}},
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        enable_utc=True,
        timezone="Asia/Seoul",
        task_track_started=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "runtime-heartbeat": {
                "task": "esafe.runtime_heartbeat",
                "schedule": 30.0,
            }
        },
    )

    @application.task(name="esafe.runtime_heartbeat")
    def runtime_heartbeat() -> dict[str, Any]:
        return {
            "profile": settings.profile,
            "queue": settings.celery_queue,
            "status": "UP",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    return application


celery_app = create_celery_app(get_settings())
