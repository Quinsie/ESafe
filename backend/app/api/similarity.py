from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.similarity import (
    SimilarityContractError,
    candidate_buildings,
    comparison,
    incident_search,
)

router = APIRouter(prefix="/api/v1/similar", tags=["similarity"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


def _similarity_error(request: Request, error: SimilarityContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(request, None, error={"code": error.code, "message": error.message}),
    )


@router.get("/incidents")
async def incidents(
    request: Request,
    _: Session,
    region: Annotated[str | None, Query(pattern="^[0-9]{2,10}$")] = None,
    building: UUID | None = None,
    case: UUID | None = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    incident_type: Annotated[str | None, Query(alias="incidentType", max_length=64)] = None,
    facility_type: Annotated[str | None, Query(alias="facilityType", max_length=64)] = None,
    damage: Annotated[str | None, Query(max_length=64)] = None,
    query_text: Annotated[str | None, Query(alias="q", max_length=80)] = None,
    sort: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=50)] = 20,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await incident_search(
            request.app.state.db_engine,
            region,
            building,
            case,
            from_date,
            to_date,
            incident_type,
            facility_type,
            damage,
            query_text,
            sort or ("match" if building or case else "recent"),
            page,
            page_size,
            settings.health_timeout_seconds,
        )
    except SimilarityContractError as error:
        return _similarity_error(request, error)
    return envelope(request, data)


@router.get("/facilities")
async def facilities(
    request: Request,
    _: Session,
    reference_incident: Annotated[UUID, Query(alias="referenceIncident")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=50)] = 20,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await candidate_buildings(
            request.app.state.db_engine,
            reference_incident,
            page,
            page_size,
            settings.health_timeout_seconds,
        )
    except SimilarityContractError as error:
        return _similarity_error(request, error)
    return envelope(request, data)


@router.get("/compare")
async def compare(
    request: Request,
    _: Session,
    reference_incident: Annotated[UUID, Query(alias="referenceIncident")],
    candidate_building: Annotated[UUID, Query(alias="candidateBuilding")],
) -> Any:
    settings = request.app.state.settings
    try:
        data = await comparison(
            request.app.state.db_engine,
            reference_incident,
            candidate_building,
            settings.health_timeout_seconds,
        )
    except SimilarityContractError as error:
        return _similarity_error(request, error)
    return envelope(request, data)
