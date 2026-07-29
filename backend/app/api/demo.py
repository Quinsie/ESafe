from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.demo.playback import (
    next_scenario_step,
    pause_scenario,
    reset_scenario,
    scenario_catalog,
    start_scenario,
)
from app.workflow import WorkflowContractError

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]


class StartBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    expected_version: int | None = Field(default=None, alias="expectedVersion", ge=1)


class VersionBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    expected_version: int = Field(alias="expectedVersion", ge=1)


class ResetBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int | None = Field(default=None, alias="expectedVersion", ge=1)
    active_expected_version: int | None = Field(default=None, alias="activeExpectedVersion", ge=1)
    confirmed: bool = False


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request, error.details, error={"code": error.code, "message": error.message}
        ),
    )


def _idempotency_error(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=envelope(
            request,
            None,
            error={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "8~200자의 Idempotency-Key가 필요합니다.",
            },
        ),
    )


def _valid_key(value: str | None) -> bool:
    return value is not None and 8 <= len(value) <= 200


@router.get("/scenarios")
async def get_scenarios(request: Request, _: Session) -> Any:
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


@router.post("/scenarios/{scenario_id}/start")
async def post_start(
    request: Request,
    session: WriteSession,
    scenario_id: UUID,
    body: StartBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not _valid_key(idempotency_key):
        return _idempotency_error(request)
    settings = request.app.state.settings
    try:
        data = await start_scenario(
            request.app.state.db_engine,
            profile=settings.profile,
            scenario_id=scenario_id,
            expected_version=body.expected_version,
            actor_user_id=session.user_id,
            idempotency_key=str(idempotency_key),
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/scenarios/{scenario_id}/pause")
async def post_pause(
    request: Request,
    session: WriteSession,
    scenario_id: UUID,
    body: VersionBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not _valid_key(idempotency_key):
        return _idempotency_error(request)
    settings = request.app.state.settings
    try:
        data = await pause_scenario(
            request.app.state.db_engine,
            profile=settings.profile,
            scenario_id=scenario_id,
            expected_version=body.expected_version,
            actor_user_id=session.user_id,
            idempotency_key=str(idempotency_key),
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/scenarios/{scenario_id}/next")
async def post_next(
    request: Request,
    session: WriteSession,
    scenario_id: UUID,
    body: VersionBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not _valid_key(idempotency_key):
        return _idempotency_error(request)
    settings = request.app.state.settings
    try:
        data = await next_scenario_step(
            request.app.state.db_engine,
            settings,
            profile=settings.profile,
            scenario_id=scenario_id,
            expected_version=body.expected_version,
            actor_user_id=session.user_id,
            idempotency_key=str(idempotency_key),
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/scenarios/{scenario_id}/reset")
async def post_reset(
    request: Request,
    session: WriteSession,
    scenario_id: UUID,
    body: ResetBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not _valid_key(idempotency_key):
        return _idempotency_error(request)
    settings = request.app.state.settings
    try:
        data = await reset_scenario(
            request.app.state.db_engine,
            request.app.state.redis,
            settings,
            profile=settings.profile,
            scenario_id=scenario_id,
            expected_version=body.expected_version,
            active_expected_version=body.active_expected_version,
            confirmed=body.confirmed,
            actor_user_id=session.user_id,
            idempotency_key=str(idempotency_key),
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)
