from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.demo.playback import scenario_catalog
from app.workflow import WorkflowContractError

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


@router.get("/scenarios")
async def get_scenarios(
    request: Request,
    _: Session,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await scenario_catalog(
            request.app.state.db_engine,
            profile=settings.profile,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)
