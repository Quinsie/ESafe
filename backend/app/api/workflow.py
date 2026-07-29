import hashlib
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.celery_app import celery_app
from app.workflow import (
    WorkflowContractError,
    case_closure_review,
    case_evidence,
    case_work_items,
    close_case,
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


class CloseCaseBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    close_reason: str = Field(alias="closeReason", min_length=1, max_length=32)
    summary: str = Field(min_length=1, max_length=4000)
    warning_acknowledged: bool = Field(
        default=False,
        alias="warningAcknowledged",
    )


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            error.details,
            error={"code": error.code, "message": error.message},
        ),
    )


def _not_found(request: Request, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=envelope(request, None, error={"code": code, "message": message}),
    )


@router.post("/cases/{case_id}/evidence/retrieve", status_code=202)
async def post_case_evidence_retrieval(
    request: Request,
    _: WriteSession,
    case_id: UUID,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    if idempotency_key is None or not 8 <= len(idempotency_key) <= 200:
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
    async with request.app.state.db_engine.connect() as connection:
        exists = (
            await connection.execute(
                text("SELECT 1 FROM case_record WHERE case_id = :case_id"),
                {"case_id": case_id},
            )
        ).scalar_one_or_none()
    if exists is None:
        return _not_found(request, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
    settings = request.app.state.settings
    digest = hashlib.sha256(
        f"{settings.profile}:{case_id}:{idempotency_key}".encode()
    ).hexdigest()
    redis_key = f"rag:retrieve:idempotency:{digest}"
    task_id = str(uuid5(case_id, digest))
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        created = bool(
            await redis.set(
                redis_key,
                task_id,
                ex=24 * 60 * 60,
                nx=True,
            )
        )
        if created:
            try:
                celery_app.send_task(
                    "esafe.retrieve_case_evidence",
                    args=[str(case_id)],
                    task_id=task_id,
                    queue=settings.celery_queue,
                )
            except Exception:
                await redis.delete(redis_key)
                raise
        else:
            task_id = str(await redis.get(redis_key))
    finally:
        await redis.aclose()
    return envelope(
        request,
        {
            "caseId": str(case_id),
            "taskId": task_id,
            "status": "QUEUED",
            "reused": not created,
        },
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


@router.post("/cases/{case_id}/recommendations/generate", status_code=202)
async def post_case_recommendation_generation(
    request: Request,
    _: WriteSession,
    case_id: UUID,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    if idempotency_key is None or not 8 <= len(idempotency_key) <= 200:
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
    async with request.app.state.db_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT c.case_id, bundle.evidence_bundle_id
                        FROM case_record c
                        LEFT JOIN evidence_bundle bundle
                          ON bundle.case_id = c.case_id AND bundle.is_current
                        WHERE c.case_id = :case_id
                        """
                    ),
                    {"case_id": case_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return _not_found(request, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
    if row["evidence_bundle_id"] is None:
        return JSONResponse(
            status_code=409,
            content=envelope(
                request,
                None,
                error={
                    "code": "EVIDENCE_BUNDLE_REQUIRED",
                    "message": "대응안을 만들기 전에 Case 근거 검색을 실행해야 합니다.",
                },
            ),
        )
    settings = request.app.state.settings
    digest = hashlib.sha256(
        f"{settings.profile}:{case_id}:recommendation:{idempotency_key}".encode()
    ).hexdigest()
    idempotency_redis_key = f"recommendation:idempotency:{digest}"
    active_redis_key = f"recommendation:active:{settings.profile}:{case_id}"
    task_id = str(uuid5(case_id, digest))
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        existing_task_id = await redis.get(idempotency_redis_key)
        if existing_task_id:
            task_id = str(existing_task_id)
            reused = True
        else:
            acquired = bool(await redis.set(active_redis_key, task_id, ex=900, nx=True))
            if not acquired:
                task_id = str(await redis.get(active_redis_key))
                reused = True
            else:
                reused = False
                await redis.set(idempotency_redis_key, task_id, ex=24 * 60 * 60)
                try:
                    celery_app.send_task(
                        "esafe.generate_case_recommendation",
                        args=[str(case_id)],
                        task_id=task_id,
                        queue=settings.celery_queue,
                    )
                except Exception:
                    await redis.delete(active_redis_key, idempotency_redis_key)
                    raise
    finally:
        await redis.aclose()
    return envelope(
        request,
        {
            "caseId": str(case_id),
            "taskId": task_id,
            "status": "QUEUED",
            "reused": reused,
        },
    )


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


@router.post("/cases/{case_id}/close")
async def post_case_close(
    request: Request,
    session: WriteSession,
    case_id: UUID,
    body: CloseCaseBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await close_case(
            request.app.state.db_engine,
            profile=settings.profile,
            case_id=case_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
            expected_version=body.expected_version,
            close_reason=body.close_reason,
            summary=body.summary,
            warning_acknowledged=body.warning_acknowledged,
        )
    except WorkflowContractError as error:
        return _error(request, error)
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
