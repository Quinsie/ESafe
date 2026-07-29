from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.approvals import (
    approval_detail,
    approval_list,
    decide_approval,
    request_recommendation_approval,
)
from app.auth import AuthenticatedSession
from app.workflow import WorkflowContractError

router = APIRouter(prefix="/api/v1", tags=["approvals"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]


class ApprovalDecisionBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    decision: Literal["APPROVED", "ON_HOLD", "DISCARDED"]
    reason: str = Field(min_length=1, max_length=1000)
    warning_acknowledged: bool = Field(
        default=False, alias="warningAcknowledged"
    )


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


@router.get("/approvals")
async def get_approvals(
    request: Request,
    _: Session,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await approval_list(
            request.app.state.db_engine,
            status=status,
            page=page,
            page_size=page_size,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.get("/approvals/{approval_request_id}")
async def get_approval(
    request: Request,
    _: Session,
    approval_request_id: UUID,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await approval_detail(
            request.app.state.db_engine,
            approval_request_id,
            settings.health_timeout_seconds,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    if data is None:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={
                    "code": "APPROVAL_NOT_FOUND",
                    "message": "승인 요청을 찾을 수 없습니다.",
                },
            ),
        )
    return envelope(request, data)


@router.post(
    "/recommendations/{recommendation_id}/approval-requests",
    status_code=201,
)
async def post_recommendation_approval_request(
    request: Request,
    session: WriteSession,
    recommendation_id: UUID,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await request_recommendation_approval(
            request.app.state.db_engine,
            profile=settings.profile,
            recommendation_id=recommendation_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/approvals/{approval_request_id}/decision")
async def post_approval_decision(
    request: Request,
    session: WriteSession,
    approval_request_id: UUID,
    body: ApprovalDecisionBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        data = await decide_approval(
            request.app.state.db_engine,
            profile=settings.profile,
            approval_request_id=approval_request_id,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
            expected_version=body.expected_version,
            decision=body.decision,
            reason=body.reason,
            warning_acknowledged=body.warning_acknowledged,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, data)
