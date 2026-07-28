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


def test_runtime_heartbeat_contains_no_cross_profile_state() -> None:
    application = create_celery_app(demo_settings())
    task = application.tasks["esafe.runtime_heartbeat"]

    result = task.apply().get()

    assert result["profile"] == "DEMO"
    assert result["queue"] == "demo"
    assert result["status"] == "UP"
