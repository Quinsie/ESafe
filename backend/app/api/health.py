from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.config import Settings
from app.db import dependency_health, reference_dataset_metadata

router = APIRouter(prefix="/api/v1")
Authenticated = Annotated[AuthenticatedSession, Depends(require_session)]


@router.get("/health/live")
async def liveness(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return envelope(
        request,
        {
            "status": "UP",
            "service": "esafe-api",
            "version": settings.app_version,
            "commit": settings.build_commit,
        },
    )


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    dependencies = await dependency_health(
        request.app.state.db_engine,
        request.app.state.redis,
        settings.health_timeout_seconds,
    )
    ready = all(item["status"] == "UP" for item in dependencies.values())
    payload = envelope(request, {"status": "UP" if ready else "DOWN", **dependencies})
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@router.get("/meta")
async def metadata(request: Request, _session: Authenticated) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return envelope(
        request,
        {
            "profile": settings.profile,
            "profileBadge": settings.profile_badge,
            "version": settings.app_version,
            "commit": settings.build_commit,
        },
    )


@router.get("/reference/meta")
async def reference_metadata(request: Request, _session: Authenticated) -> JSONResponse:
    settings: Settings = request.app.state.settings
    metadata = await reference_dataset_metadata(
        request.app.state.db_engine, settings.health_timeout_seconds
    )
    if metadata is None:
        return JSONResponse(
            status_code=503,
            content=envelope(
                request,
                None,
                error={
                    "code": "REFERENCE_DATA_NOT_READY",
                    "message": "기준 데이터가 준비되지 않았습니다.",
                },
            ),
        )
    return JSONResponse(status_code=200, content=envelope(request, metadata))
