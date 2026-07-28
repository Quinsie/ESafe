from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    profile: Literal["LIVE", "DEMO"] = Field(default="LIVE", alias="ESAFE_PROFILE")
    database_url: str = Field(
        default="postgresql+asyncpg://esafe:development@127.0.0.1:5432/esafe_live",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str = Field(
        default="redis://127.0.0.1:6379/1",
        alias="CELERY_RESULT_BACKEND",
    )
    celery_queue: str = Field(default="live", alias="CELERY_QUEUE")
    session_secret: str = Field(
        default="development-only-change-before-deploy",
        alias="ESAFE_SESSION_SECRET",
        min_length=32,
    )
    public_user_id: str = Field(default="user", alias="ESAFE_PUBLIC_USER_ID", min_length=1)
    public_user_password: SecretStr | None = Field(
        default=None,
        alias="ESAFE_PUBLIC_USER_PASSWORD",
    )
    cookie_secure: bool = Field(default=False, alias="ESAFE_COOKIE_SECURE")
    public_origins_csv: str = Field(
        default="http://127.0.0.1:8080",
        alias="ESAFE_PUBLIC_ORIGINS",
    )
    nfds_enabled: bool = Field(default=True, alias="NFDS_ENABLED")
    session_idle_seconds: int = Field(default=8 * 60 * 60, ge=60)
    session_absolute_seconds: int = Field(default=12 * 60 * 60, ge=60)
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=5 * 60, ge=1, le=3600)
    app_version: str = Field(default="0.1.0", alias="ESAFE_APP_VERSION")
    build_commit: str = Field(default="unknown", alias="ESAFE_BUILD_COMMIT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    health_timeout_seconds: float = Field(
        default=2.0,
        alias="ESAFE_HEALTH_TIMEOUT_SECONDS",
        ge=0.05,
        le=10.0,
    )

    @property
    def profile_badge(self) -> str:
        return "실시간 연동" if self.profile == "LIVE" else "체험 데이터"

    @property
    def session_cookie_name(self) -> str:
        return f"esafe_{self.profile.lower()}_session"

    @property
    def csrf_cookie_name(self) -> str:
        return f"esafe_{self.profile.lower()}_csrf"

    @property
    def session_cookie_path(self) -> str:
        return f"/{self.profile.lower()}/"

    @property
    def public_origins(self) -> frozenset[str]:
        return frozenset(
            origin.strip().rstrip("/")
            for origin in self.public_origins_csv.split(",")
            if origin.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()