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
        task_routes={
            "esafe.generate_document_artifact": {"queue": f"{settings.celery_queue}-documents"},
            "esafe.*": {"queue": settings.celery_queue},
        },
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
            **(
                {
                    "signal-dispatch": {
                        "task": "esafe.signal_dispatch",
                        "schedule": 600.0,
                    }
                }
                if settings.profile == "LIVE"
                else {}
            ),
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
        if settings.profile == "DEMO":
            return {
                "profile": settings.profile,
                "scheduled": [],
                "status": "SCENARIO_CONTROLLED",
                "timestamp": datetime.now(UTC).isoformat(),
            }
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
        if settings.profile == "DEMO":
            raise RuntimeError("DEMO signals are available only through scenario controls")
        from app.signals.contracts import SignalSource
        from app.signals.ingestion import run_signal_poll

        try:
            source = SignalSource(source_name)
        except ValueError as error:
            raise ValueError(f"unsupported signal source: {source_name}") from error
        return asyncio.run(run_signal_poll(settings, source))

    @application.task(
        name="esafe.retrieve_case_evidence",
        shared=False,
        lazy=False,
    )
    def retrieve_case_evidence(case_id: str) -> dict[str, Any]:
        from uuid import UUID

        from app.rag_search import run_case_retrieval

        return asyncio.run(run_case_retrieval(settings, UUID(case_id)))

    @application.task(
        name="esafe.generate_case_recommendation",
        shared=False,
        lazy=False,
    )
    def generate_case_recommendation(case_id: str) -> dict[str, Any]:
        from uuid import UUID

        from redis.asyncio import Redis

        from app.recommendations import run_case_recommendation

        async def execute() -> dict[str, Any]:
            try:
                return await run_case_recommendation(settings, UUID(case_id))
            finally:
                redis = Redis.from_url(settings.redis_url, decode_responses=True)
                try:
                    await redis.delete(f"recommendation:active:{settings.profile}:{case_id}")
                finally:
                    await redis.aclose()

        return asyncio.run(execute())

    @application.task(
        name="esafe.generate_document_artifact",
        shared=False,
        lazy=False,
    )
    def generate_document_artifact_task(artifact_id: str) -> dict[str, Any]:
        from uuid import UUID

        from app.documents import generate_document_artifact

        return asyncio.run(generate_document_artifact(settings, UUID(artifact_id)))

    @application.task(
        name="esafe.run_inspection_simulation",
        shared=False,
        lazy=False,
    )
    def run_inspection_simulation_task(simulation_id: str) -> dict[str, Any]:
        from uuid import UUID

        from app.inspection_engine import run_inspection_simulation

        return asyncio.run(run_inspection_simulation(settings, UUID(simulation_id)))

    return application


celery_app = create_celery_app(get_settings())
