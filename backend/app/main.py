from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.auth import AuthError
from app.api.auth import router as auth_router
from app.api.automation import router as automation_router
from app.api.cases import router as cases_router
from app.api.health import router as health_router
from app.api.home import router as home_router
from app.api.responses import envelope
from app.api.similarity import router as similarity_router
from app.api.spatial import router as spatial_router
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
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(automation_router)
app.include_router(home_router)
app.include_router(spatial_router)
app.include_router(similarity_router)
app.include_router(cases_router)


@app.exception_handler(AuthError)
async def authentication_error(request: Request, exc: AuthError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Session"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            request,
            None,
            error={"code": exc.code, "message": exc.message},
        ),
        headers=headers,
    )


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