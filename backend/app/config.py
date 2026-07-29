from decimal import Decimal
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
    vworld_tile_url: str | None = Field(default=None, alias="VWORLD_TILE_URL")
    nfds_enabled: bool = Field(default=True, alias="NFDS_ENABLED")
    data_go_kr_service_key: SecretStr | None = Field(
        default=None,
        alias="DATA_GO_KR_SERVICE_KEY",
    )
    upstage_api_key: SecretStr | None = Field(default=None, alias="UPSTAGE_API_KEY")
    upstage_base_url: str = Field(
        default="https://api.upstage.ai/v1",
        alias="UPSTAGE_BASE_URL",
    )
    upstage_chat_model: str = Field(default="solar-pro3", alias="UPSTAGE_CHAT_MODEL")
    upstage_chat_timeout_seconds: float = Field(
        default=180.0,
        ge=30.0,
        le=300.0,
        alias="UPSTAGE_CHAT_TIMEOUT_SECONDS",
    )
    upstage_embed_query_model: str = Field(
        default="solar-embedding-2-query",
        alias="UPSTAGE_EMBED_QUERY_MODEL",
    )
    upstage_embed_passage_model: str = Field(
        default="solar-embedding-2-passage",
        alias="UPSTAGE_EMBED_PASSAGE_MODEL",
    )
    upstage_cost_hard_stop_usd: Decimal = Field(
        default=Decimal("450"),
        gt=0,
        alias="UPSTAGE_COST_HARD_STOP_USD",
    )
    ai_control_database_url: str | None = Field(
        default=None,
        alias="AI_CONTROL_DATABASE_URL",
    )
    document_storage_root: str = Field(
        default="/srv/esafe/storage/documents",
        alias="DOCUMENT_STORAGE_ROOT",
    )
    document_pdf_renderer: str = Field(
        default="/app/document_runtime/render_pdf.mjs",
        alias="DOCUMENT_PDF_RENDERER",
    )
    document_render_timeout_seconds: float = Field(
        default=90.0,
        ge=10.0,
        le=300.0,
        alias="DOCUMENT_RENDER_TIMEOUT_SECONDS",
    )
    nfds_monitor_url: str = Field(
        default="https://www.nfds.go.kr/dashboard/monitorData.do",
        alias="NFDS_MONITOR_URL",
    )
    kma_warning_base_url: str = Field(
        default="https://apis.data.go.kr/1360000/WthrWrnInfoService",
        alias="KMA_WARNING_BASE_URL",
    )
    disaster_message_url: str = Field(
        default="https://www.safetydata.go.kr/disaster-data/disasterNotification",
        alias="DISASTER_MESSAGE_URL",
    )
    signal_user_agent: str = Field(
        default="ESafe-MVP/0.1 (+public-safety-monitoring)",
        alias="ESAFE_SIGNAL_USER_AGENT",
    )
    signal_http_timeout_seconds: float = Field(
        default=20.0, ge=2.0, le=60.0, alias="ESAFE_SIGNAL_HTTP_TIMEOUT_SECONDS"
    )
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
