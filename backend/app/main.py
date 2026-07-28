from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.health import envelope, router
from app.config import get_settings
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level)
PUBLIC_INTERNAL_ERROR_MESSAGE = "요청을 처리하지 못했습니다."


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.settings = settings
    application.state.db_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    application.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    structlog.get_logger("lifecycle").info("application_started", profile=settings.profile)
    yield
    await application.state.redis.aclose()
    await application.state.db_engine.dispose()
    structlog.get_logger("lifecycle").info("application_stopped", profile=settings.profile)


app = FastAPI(
    title="ESafe API",
    version=settings.app_version,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    structlog.get_logger("error").exception("unhandled_exception", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=envelope(
            request,
            None,
            error={"code": "INTERNAL_ERROR", "message": PUBLIC_INTERNAL_ERROR_MESSAGE},
        ),
    )
