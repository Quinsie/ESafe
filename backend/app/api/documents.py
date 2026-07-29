from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.celery_app import celery_app
from app.document_content import DocumentPayload, DocumentVariant
from app.documents import (
    create_document_draft,
    document_artifact_download,
    document_detail,
    document_library,
    update_document_draft,
)
from app.workflow import WorkflowContractError

router = APIRouter(prefix="/api/v1", tags=["documents"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]


class CreateDocumentBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    variant: DocumentVariant


class UpdateDocumentBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    payload: DocumentPayload


def _error(request: Request, error: WorkflowContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


def _queue_artifacts(request: Request, detail: dict[str, Any]) -> None:
    settings = request.app.state.settings
    for artifact in detail["artifacts"]:
        if artifact["status"] != "QUEUED":
            continue
        artifact_id = artifact["documentArtifactId"]
        celery_app.send_task(
            "esafe.generate_document_artifact",
            args=[artifact_id],
            task_id=artifact_id,
            queue=f"{settings.celery_queue}-documents",
        )


@router.post("/cases/{case_id}/documents", status_code=202)
async def post_document(
    request: Request,
    session: WriteSession,
    case_id: UUID,
    body: CreateDocumentBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        detail, reused = await create_document_draft(
            request.app.state.db_engine,
            profile=settings.profile,
            case_id=case_id,
            variant=body.variant,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
        _queue_artifacts(request, detail)
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, detail | {"reused": reused})


@router.get("/documents")
async def get_documents(
    request: Request,
    _: Session,
    status: str | None = None,
    family: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> Any:
    settings = request.app.state.settings
    try:
        result = await document_library(
            request.app.state.db_engine,
            status=status,
            family=family,
            page=page,
            page_size=page_size,
            timeout_seconds=settings.health_timeout_seconds,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, result)


@router.get("/documents/{document_draft_id}")
async def get_document(
    request: Request,
    _: Session,
    document_draft_id: UUID,
) -> Any:
    settings = request.app.state.settings
    result = await document_detail(
        request.app.state.db_engine,
        document_draft_id,
        settings.health_timeout_seconds,
    )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={
                    "code": "DOCUMENT_NOT_FOUND",
                    "message": "문서 초안을 찾을 수 없습니다.",
                },
            ),
        )
    return envelope(request, result)


@router.put("/documents/{document_draft_id}", status_code=202)
async def put_document(
    request: Request,
    session: WriteSession,
    document_draft_id: UUID,
    body: UpdateDocumentBody,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    try:
        detail, reused = await update_document_draft(
            request.app.state.db_engine,
            profile=settings.profile,
            document_draft_id=document_draft_id,
            expected_version=body.expected_version,
            payload=body.payload,
            user_id=session.user_id,
            request_id=UUID(request.state.request_id),
            idempotency_key=idempotency_key,
        )
        _queue_artifacts(request, detail)
    except WorkflowContractError as error:
        return _error(request, error)
    return envelope(request, detail | {"reused": reused})


@router.get("/document-artifacts/{artifact_id}/download")
async def get_document_artifact(
    request: Request,
    _: Session,
    artifact_id: UUID,
) -> Any:
    settings = request.app.state.settings
    try:
        result = await document_artifact_download(
            request.app.state.db_engine,
            artifact_id=artifact_id,
            storage_root=Path(settings.document_storage_root),
            timeout_seconds=settings.health_timeout_seconds,
        )
    except WorkflowContractError as error:
        return _error(request, error)
    if result is None:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={
                    "code": "DOCUMENT_ARTIFACT_NOT_FOUND",
                    "message": "다운로드할 문서 파일을 찾을 수 없습니다.",
                },
            ),
        )
    path, file_name, mime_type = result
    return FileResponse(
        path,
        media_type=mime_type,
        filename=file_name,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
