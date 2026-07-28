from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.home import briefing_data, source_health_data, task_summary_data

router = APIRouter(prefix="/api/v1", tags=["home"])


@router.get("/briefing")
async def briefing(
    request: Request,
    _: Annotated[AuthenticatedSession, Depends(require_session)],
) -> dict[str, object]:
    settings = request.app.state.settings
    data = await briefing_data(request.app.state.db_engine, settings.health_timeout_seconds)
    return envelope(request, data)


@router.get("/tasks/summary")
async def task_summary(
    request: Request,
    _: Annotated[AuthenticatedSession, Depends(require_session)],
) -> dict[str, object]:
    settings = request.app.state.settings
    data = await task_summary_data(request.app.state.db_engine, settings.health_timeout_seconds)
    return envelope(request, data)


@router.get("/sources/health")
async def source_health(
    request: Request,
    _: Annotated[AuthenticatedSession, Depends(require_session)],
) -> dict[str, object]:
    settings = request.app.state.settings
    data = await source_health_data(request.app.state.db_engine, settings.health_timeout_seconds)
    return envelope(request, data)