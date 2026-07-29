import asyncio
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from celery import Celery

from app.config import Settings, get_settings


def create_celery_app(settings: Settings) -> Celery:
    # Query strings can contain API credentials. Never allow dependency
    # request logging to emit full upstream URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
            },
            "signal-dispatch": {
                "task": "esafe.signal_dispatch",
                "schedule": 600.0,
            },
        },
    )

    @application.task(name="esafe.runtime_heartbeat", shared=False, lazy=False)
    def runtime_heartbeat() -> dict[str, Any]:
        return {
            "profile": settings.profile,
            "queue": settings.celery_queue,
            "status": "UP",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @application.task(name="esafe.signal_dispatch", shared=False, lazy=False)
    def signal_dispatch() -> dict[str, Any]:
        sources = ["KMA_WARNING", "DISASTER_MESSAGE"]
        if settings.profile == "DEMO" or settings.nfds_enabled:
            sources.insert(0, "NFDS")
        scheduled = []
        for source in sources:
            countdown = secrets.randbelow(61)
            application.send_task(
                "esafe.poll_signal",
                args=[source],
                countdown=countdown,
                queue=settings.celery_queue,
            )
            scheduled.append({"source": source, "countdownSeconds": countdown})
        return {
            "profile": settings.profile,
            "scheduled": scheduled,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @application.task(name="esafe.poll_signal", shared=False, lazy=False)
    def poll_signal(source_name: str) -> dict[str, object]:
        from app.signals.contracts import SignalSource
        from app.signals.ingestion import run_signal_poll

        try:
            source = SignalSource(source_name)
        except ValueError as error:
            raise ValueError(f"unsupported signal source: {source_name}") from error
        return asyncio.run(run_signal_poll(settings, source))

    return application


celery_app = create_celery_app(get_settings())
