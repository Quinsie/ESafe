import logging
from unittest.mock import Mock

from app.celery_app import create_celery_app
from app.config import Settings


def demo_settings() -> Settings:
    return Settings.model_validate(
        {
            "ESAFE_PROFILE": "DEMO",
            "DATABASE_URL": "postgresql+asyncpg://test:test@db-demo/test",
            "REDIS_URL": "redis://redis-demo:6379/0",
            "CELERY_BROKER_URL": "redis://redis-demo:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis-demo:6379/1",
            "CELERY_QUEUE": "demo",
            "ESAFE_SESSION_SECRET": "test-session-secret-at-least-32-characters",
        }
    )


def test_celery_runtime_is_bound_to_profile_queue() -> None:
    application = create_celery_app(demo_settings())

    assert application.conf.task_default_queue == "demo"
    assert application.conf.task_routes["esafe.*"]["queue"] == "demo"
    assert application.conf.broker_url == "redis://redis-demo:6379/0"
    assert application.backend.as_uri() == "redis://redis-demo:6379/1"
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_runtime_heartbeat_contains_no_cross_profile_state() -> None:
    application = create_celery_app(demo_settings())
    task = application.tasks["esafe.runtime_heartbeat"]

    result = task.apply().get()

    assert result["profile"] == "DEMO"
    assert result["queue"] == "demo"
    assert result["status"] == "UP"


def test_rag_retrieval_task_is_registered_per_profile() -> None:
    application = create_celery_app(demo_settings())

    assert "esafe.retrieve_case_evidence" in application.tasks
    assert "esafe.generate_case_recommendation" in application.tasks


def test_signal_dispatch_is_ten_minutes_with_bounded_jitter(monkeypatch) -> None:
    application = create_celery_app(demo_settings())
    sender = Mock()
    monkeypatch.setattr(application, "send_task", sender)
    monkeypatch.setattr("app.celery_app.secrets.randbelow", lambda _: 17)

    result = application.tasks["esafe.signal_dispatch"].apply().get()

    assert application.conf.beat_schedule["signal-dispatch"]["schedule"] == 600.0
    assert [item["source"] for item in result["scheduled"]] == [
        "NFDS",
        "KMA_WARNING",
        "DISASTER_MESSAGE",
    ]
    assert all(item["countdownSeconds"] == 17 for item in result["scheduled"])
    assert sender.call_count == 3
    assert all(call.kwargs["queue"] == "demo" for call in sender.call_args_list)


def test_live_dispatch_omits_nfds_when_disabled(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "ESAFE_PROFILE": "LIVE",
            "NFDS_ENABLED": False,
            "DATABASE_URL": "postgresql+asyncpg://test:test@db-live/test",
            "REDIS_URL": "redis://redis-live:6379/0",
            "CELERY_BROKER_URL": "redis://redis-live:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis-live:6379/1",
            "CELERY_QUEUE": "live",
            "ESAFE_SESSION_SECRET": "test-session-secret-at-least-32-characters",
        }
    )
    application = create_celery_app(settings)
    sender = Mock()
    monkeypatch.setattr(application, "send_task", sender)
    monkeypatch.setattr("app.celery_app.secrets.randbelow", lambda _: 0)

    result = application.tasks["esafe.signal_dispatch"].apply().get()

    assert [item["source"] for item in result["scheduled"]] == [
        "KMA_WARNING",
        "DISASTER_MESSAGE",
    ]
    assert sender.call_count == 2
