from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.automation_api import (
    AutomationContractError,
    automation_activity,
    automation_policies,
)

router = APIRouter(prefix="/api/v1", tags=["automation"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


def _automation_error(
    request: Request,
    error: AutomationContractError,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


@router.get("/automation/runs")
async def get_automation_activity(
    request: Request,
    _: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    status: str | None = None,
    entry_type: Annotated[str | None, Query(alias="entryType")] = None,
    source: str | None = None,
    hours: Annotated[int | None, Query(ge=1)] = 24,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await automation_activity(
            request.app.state.db_engine,
            page=page,
            page_size=page_size,
            status=status,
            entry_type=entry_type,
            source=source,
            hours=hours,
            search=search,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except AutomationContractError as error:
        return _automation_error(request, error)
    return envelope(request, data)


@router.get("/automation/policies")
async def get_automation_policies(
    request: Request,
    _: Session,
) -> Any:
    return envelope(request, automation_policies(request.app.state.settings))
