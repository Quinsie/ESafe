from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    profile: Literal["LIVE", "DEMO"] = Field(default="LIVE", alias="ESAFE_PROFILE")
    database_url: str = Field(
        default="postgresql+asyncpg://esafe:development@127.0.0.1:5432/esafe_live",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    session_secret: str = Field(
        default="development-only-change-before-deploy",
        alias="ESAFE_SESSION_SECRET",
        min_length=32,
    )
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
        return "??? ??" if self.profile == "LIVE" else "?? ???"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
