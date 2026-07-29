from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.workflow import (
    WorkflowContractError,
    case_closure_review,
    case_evidence,
    case_work_items,
    create_case_work_item,
    transition_work_item,
    update_checklist_item,
    work_item_detail,
)

router = APIRouter(prefix="/api/v1", tags=["case-workflow"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]


class CreateWorkItemBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=240)
    work_type: str = Field(
        alias="workType",
        min_length=1,
        max_length=64,
        pattern="^[A-Za-z0-9_]+$",
    )
    priority: str = Field(default="NORMAL")
    due_at: datetime | None = Field(default=None, alias="dueAt")
    recommendation_action_id: UUID | None = Field(
        default=None, alias="recommendationActionId"
    )
    checklist: list[str] = Field(default_factory=list, max_length=30)


class WorkTransitionBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    target_status: str = Field(alias="targetStatus")
    reason: str = Field(min_length=1, max_length=1000)


class ChecklistUpdateBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_work_version: int = Field(alias="expectedWorkVersion", ge=1)
    status: str
    note: str | None = Field(default=None, max_length=2000)


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


def _not_found(request: Request, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=envelope(request, None, error={"code": code, "message": message}),
    )


@router.get("/cases/{case_id}/evidence")
async def get_case_evidence(
    request: Request,
    _: Session,
    case_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await case_evidence(
        request.app.state.db_engine,
        case_id,
        settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
    return envelope(request, data)


@router.get("/cases/{case_id}/work-items")
async def get_case_work_items(
    request: Request,
    _: Session,
    case_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await case_work_items(
        request.app.state.db_engine,
        case_id,
        settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
    return envelope(request, data)


@router.get("/work-items/{work_item_id}")
async def get_work_item(
    request: Request,
    _: Session,
    work_item_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await work_item_detail(
        request.app.state.db_engine,
        work_item_id,
        settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request, "WORK_ITEM_NOT_FOUND", "업무를 찾을 수 없습니다.")
    return envelope(request, data)


@router.get("/cases/{case_id}/closure-review")
async def get_case_closure_review(
    request: Request,
    _: Session,
    case_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await case_closure_review(
        request.app.state.db_engine,
        case_id,
        settings.health_timeout_seconds,
    )
    if data is None:
        return _not_found(request, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
    return envelope(request, data)


@router.post("/cases/{case_id}/work-items", status_code=201)
async def post_case_work_item(
    request: Request,
    session: WriteSession,
    case_id: UUID,
    body: CreateWorkItemBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await create_case_work_item(
            request.app.state.db_engine,
            profile=settings.profile,
            case_id=case_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
            title=body.title,
            work_type=body.work_type,
            priority=body.priority,
            due_at=body.due_at,
            recommendation_action_id=body.recommendation_action_id,
            checklist_labels=body.checklist,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.patch("/work-items/{work_item_id}/status")
async def patch_work_item_status(
    request: Request,
    session: WriteSession,
    work_item_id: UUID,
    body: WorkTransitionBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await transition_work_item(
            request.app.state.db_engine,
            profile=settings.profile,
            work_item_id=work_item_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
            expected_version=body.expected_version,
            target_status=body.target_status,
            reason=body.reason,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.patch(
    "/work-items/{work_item_id}/checklist/{checklist_item_id}"
)
async def patch_checklist_item(
    request: Request,
    session: WriteSession,
    work_item_id: UUID,
    checklist_item_id: UUID,
    body: ChecklistUpdateBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await update_checklist_item(
            request.app.state.db_engine,
            profile=settings.profile,
            work_item_id=work_item_id,
            checklist_item_id=checklist_item_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
            expected_work_version=body.expected_work_version,
            status=body.status,
            note=body.note,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)
