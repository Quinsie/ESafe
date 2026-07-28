from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import dependency_health

router = APIRouter(prefix="/api/v1")


def envelope(request: Request, data: Any, *, error: dict[str, str] | None = None) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "data": data,
        "meta": {
            "requestId": request.state.request_id,
            "profile": settings.profile,
            "asOf": datetime.now(UTC).isoformat(),
            "sourceStatus": [],
        },
        "error": error,
    }


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
async def metadata(request: Request) -> dict[str, Any]:
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
