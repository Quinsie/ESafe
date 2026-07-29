from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.cases import (
    CaseContractError,
    case_detail,
    case_impact_buildings,
    case_list,
    case_timeline,
)

router = APIRouter(prefix="/api/v1", tags=["cases"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


def _case_error(request: Request, error: CaseContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


def _not_found(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=envelope(
            request,
            None,
            error={"code": "CASE_NOT_FOUND", "message": "Case를 찾을 수 없습니다."},
        ),
    )


@router.get("/cases")
async def get_cases(
    request: Request,
    _: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    status: str | None = None,
    case_type: Annotated[str | None, Query(alias="caseType")] = None,
    source: str | None = None,
    region_code: Annotated[
        str | None, Query(alias="regionCode", pattern="^[0-9]{2,10}$")
    ] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: str = "priority",
) -> Any:
    settings = request.app.state.settings
    try:
        data = await case_list(
            request.app.state.db_engine,
            page=page,
            page_size=page_size,
            status=status,
            case_type=case_type,
            source=source,
            region_code=region_code,
            search=search,
            sort=sort,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except CaseContractError as error:
        return _case_error(request, error)
    return envelope(request, data)


@router.get("/cases/{case_id}")
async def get_case(
    request: Request,
    _: Session,
    case_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await case_detail(
        request.app.state.db_engine,
        case_id,
        settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request)
    return envelope(request, data)


@router.get("/cases/{case_id}/timeline")
async def get_case_timeline(
    request: Request,
    _: Session,
    case_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 50,
) -> Any:
    settings = request.app.state.settings
    data = await case_timeline(
        request.app.state.db_engine,
        case_id,
        page=page,
        page_size=page_size,
        timeout_seconds=settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request)
    return envelope(request, data)


@router.get("/cases/{case_id}/impact-buildings")
async def get_case_impact_buildings(
    request: Request,
    _: Session,
    case_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 100,
    risk_threshold: Annotated[
        int | None, Query(alias="riskThreshold")
    ] = None,
    incident_only: Annotated[bool, Query(alias="incidentOnly")] = False,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: str = "priority",
) -> Any:
    settings = request.app.state.settings
    try:
        data = await case_impact_buildings(
            request.app.state.db_engine,
            case_id,
            page=page,
            page_size=page_size,
            risk_threshold=risk_threshold,
            incident_only=incident_only,
            search=search,
            sort=sort,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except CaseContractError as error:
        return _case_error(request, error)
    if data is None:
        return _not_found(request)
    return envelope(request, data)
