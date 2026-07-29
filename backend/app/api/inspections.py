# ruff: noqa: E501
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.celery_app import celery_app
from app.inspection_approval import request_inspection_approval
from app.inspection_views import select_scenario, simulation_detail, target_list
from app.inspections import InspectionContractError, create_simulation, inspection_options

router = APIRouter(prefix="/api/v1/inspections", tags=["inspections"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]


class SimulationBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    region_code: str | None = Field(default=None, alias="regionCode", pattern="^[0-9]{2,10}$")
    building_id: UUID | None = Field(default=None, alias="buildingId")
    case_id: UUID | None = Field(default=None, alias="caseId")
    facility_types: list[str] = Field(default_factory=list, alias="facilityTypes", max_length=16)
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    team_count: int = Field(alias="teamCount", ge=1, le=100)
    daily_capacity_per_team: int = Field(alias="dailyCapacityPerTeam", ge=1, le=500)
    top_percentile: float = Field(alias="topPercentile", gt=0, le=100)
    minimum_score: float = Field(alias="minimumScore", ge=0, le=1)


class ScenarioSelectionBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    scenario_id: UUID = Field(alias="scenarioId")
    expected_version: int = Field(alias="expectedVersion", ge=1)


def _error(request: Request, error: InspectionContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(request, None, error={"code": error.code, "message": error.message}),
    )


@router.get("/options")
async def get_options(request: Request, _: Session) -> Any:
    data = await inspection_options(
        request.app.state.db_engine,
        request.app.state.settings.health_timeout_seconds,
    )
    return envelope(request, data)


@router.post("/simulations", status_code=202)
async def post_simulation(
    request: Request,
    session: WriteSession,
    body: SimulationBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key or len(idempotency_key) > 160:
        return _error(
            request,
            InspectionContractError(
                422,
                "IDEMPOTENCY_KEY_REQUIRED",
                "안전한 재요청을 위한 Idempotency-Key가 필요합니다.",
            ),
        )
    settings = request.app.state.settings
    try:
        data = await create_simulation(
            request.app.state.db_engine,
            profile=settings.profile,
            region_code=body.region_code,
            building_id=body.building_id,
            case_id=body.case_id,
            facility_types=body.facility_types,
            start_date=body.start_date,
            end_date=body.end_date,
            team_count=body.team_count,
            daily_capacity_per_team=body.daily_capacity_per_team,
            top_percentile=body.top_percentile,
            minimum_score=body.minimum_score,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except InspectionContractError as error:
        return _error(request, error)
    celery_app.send_task(
        "esafe.run_inspection_simulation",
        args=[data["inspectionSimulationId"]],
        task_id=data["inspectionSimulationId"],
        queue=settings.celery_queue,
    )
    return envelope(request, data)


@router.get("/simulations/{simulation_id}")
async def get_simulation(request: Request, _: Session, simulation_id: UUID) -> Any:
    try:
        data = await simulation_detail(
            request.app.state.db_engine,
            simulation_id,
            request.app.state.settings.health_timeout_seconds,
        )
    except InspectionContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/simulations/{simulation_id}/selection")
async def post_selection(
    request: Request,
    session: WriteSession,
    simulation_id: UUID,
    body: ScenarioSelectionBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key or len(idempotency_key) > 160:
        return _error(
            request,
            InspectionContractError(
                422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key가 필요합니다."
            ),
        )
    try:
        data = await select_scenario(
            request.app.state.db_engine,
            profile=request.app.state.settings.profile,
            simulation_id=simulation_id,
            scenario_id=body.scenario_id,
            expected_version=body.expected_version,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except InspectionContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.get("/simulations/{simulation_id}/targets")
async def get_targets(
    request: Request,
    _: Session,
    simulation_id: UUID,
    scenario_id: Annotated[UUID | None, Query(alias="scenarioId")] = None,
    include: str = "ALL",
    team_number: Annotated[int | None, Query(alias="teamNumber", ge=1)] = None,
    query: Annotated[str | None, Query(alias="q", max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> Any:
    try:
        data = await target_list(
            request.app.state.db_engine,
            simulation_id,
            scenario_id=scenario_id,
            include=include,
            team_number=team_number,
            query=query,
            page=page,
            page_size=page_size,
            timeout_seconds=request.app.state.settings.health_timeout_seconds,
        )
    except InspectionContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/simulations/{simulation_id}/approval-requests", status_code=201)
async def post_approval_request(
    request: Request,
    session: WriteSession,
    simulation_id: UUID,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key or len(idempotency_key) > 160:
        return _error(
            request,
            InspectionContractError(
                422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key가 필요합니다."
            ),
        )
    try:
        data = await request_inspection_approval(
            request.app.state.db_engine,
            profile=request.app.state.settings.profile,
            simulation_id=simulation_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except InspectionContractError as error:
        return _error(request, error)
    return envelope(request, data)
