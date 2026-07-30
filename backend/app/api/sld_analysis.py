from __future__ import annotations

import hashlib
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api.auth import require_csrf, require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.celery_app import celery_app
from app.sld_analysis import (
    SldContractError,
    analysis_detail,
    analysis_source,
    building_analyses,
    create_analysis,
    new_analysis_id,
    retry_analysis,
)
from app.sld_documents import (
    building_sld_document,
    ensure_demo_fire_building_document,
    sld_document_source,
    upsert_building_sld_document,
)

router = APIRouter(prefix="/api/v1", tags=["sld-analysis"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]
WriteSession = Annotated[AuthenticatedSession, Depends(require_csrf)]
ALLOWED_SIGNATURES = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


def _error(request: Request, error: SldContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            None,
            error={"code": error.code, "message": error.message},
        ),
    )


def _detected_type(content: bytes) -> tuple[str, str] | None:
    for signature, mime_type, extension in ALLOWED_SIGNATURES:
        if content.startswith(signature):
            return mime_type, extension
    return None


def _resolve_source(storage_root: Path, relative_path: str) -> Path:
    root = storage_root.resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise SldContractError(404, "SLD_SOURCE_NOT_FOUND", "원본 파일을 찾을 수 없습니다.")
    return target


def _render_pdf_page(source_path: Path, page_number: int) -> bytes:
    import fitz

    try:
        with fitz.open(str(source_path)) as document:
            if page_number < 1 or page_number > document.page_count:
                raise SldContractError(
                    404,
                    "SLD_PAGE_NOT_FOUND",
                    "요청한 도면 페이지를 찾을 수 없습니다.",
                )
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(dpi=144, alpha=False)
            return bytes(pixmap.tobytes("png"))
    except SldContractError:
        raise
    except Exception as error:
        raise SldContractError(
            422,
            "SLD_PAGE_RENDER_FAILED",
            "도면 페이지 이미지를 만들지 못했습니다.",
        ) from error


async def _read_upload(
    document: UploadFile,
    max_upload_bytes: int,
) -> tuple[bytes, str, str, str]:
    content = await document.read(max_upload_bytes + 1)
    if not content:
        raise SldContractError(422, "SLD_FILE_EMPTY", "파일이 비어 있습니다.")
    if len(content) > max_upload_bytes:
        raise SldContractError(
            413,
            "SLD_FILE_TOO_LARGE",
            f"파일은 {max_upload_bytes // (1024 * 1024)}MB 이하여야 합니다.",
        )
    detected = _detected_type(content)
    if detected is None:
        raise SldContractError(
            415,
            "SLD_FILE_TYPE_UNSUPPORTED",
            "PDF, PNG, JPG 단선결선도만 등록할 수 있습니다.",
        )
    mime_type, extension = detected
    source_name = Path(document.filename or f"single-line-diagram{extension}").name
    return content, mime_type, extension, source_name


def _valid_idempotency_key(value: str | None) -> bool:
    return bool(value and len(value) <= 160)


def _queue_analysis(settings: Any, analysis_id: UUID, *, task_suffix: str = "") -> None:
    celery_app.send_task(
        "esafe.analyze_sld",
        args=[str(analysis_id)],
        task_id=f"{analysis_id}{task_suffix}",
        queue=f"{settings.celery_queue}-sld",
    )


@router.get("/buildings/{building_id}/sld-document")
async def get_building_sld_document(
    request: Request,
    _: Session,
    building_id: UUID,
) -> Any:
    settings = request.app.state.settings
    try:
        await ensure_demo_fire_building_document(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
            storage_root=Path(settings.sld_storage_root),
        )
        document = await building_sld_document(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
        )
    except SldContractError as error:
        return _error(request, error)
    return envelope(request, {"document": document})


@router.put("/buildings/{building_id}/sld-document")
async def put_building_sld_document(
    request: Request,
    session: WriteSession,
    building_id: UUID,
    document: Annotated[UploadFile, File()],
) -> Any:
    settings = request.app.state.settings
    try:
        content, mime_type, extension, source_name = await _read_upload(
            document,
            settings.sld_max_upload_bytes,
        )
    except SldContractError as error:
        return _error(request, error)

    document_id = new_analysis_id()
    storage_root = Path(settings.sld_storage_root)
    relative_path = f"documents/{document_id}/source{extension}"
    source_path = _resolve_source(storage_root, relative_path)
    source_path.parent.mkdir(parents=True, exist_ok=False)
    source_path.write_bytes(content)
    try:
        data, previous_path, _ = await upsert_building_sld_document(
            request.app.state.db_engine,
            document_id=document_id,
            profile=settings.profile,
            building_id=building_id,
            source_file_name=source_name,
            source_mime_type=mime_type,
            source_size_bytes=len(content),
            source_sha256=hashlib.sha256(content).hexdigest(),
            source_storage_path=relative_path,
            user_id=session.user_id,
        )
    except SldContractError as error:
        source_path.unlink(missing_ok=True)
        source_path.parent.rmdir()
        return _error(request, error)
    if previous_path and previous_path != relative_path:
        previous_source = _resolve_source(storage_root, previous_path)
        previous_source.unlink(missing_ok=True)
        with suppress(OSError):
            previous_source.parent.rmdir()
    return envelope(request, {"document": data})


@router.get("/buildings/{building_id}/sld-document/source")
async def get_building_sld_document_source(
    request: Request,
    _: Session,
    building_id: UUID,
) -> Response:
    settings = request.app.state.settings
    try:
        await ensure_demo_fire_building_document(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
            storage_root=Path(settings.sld_storage_root),
        )
        relative_path, file_name, mime_type = await sld_document_source(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
        )
        source_path = _resolve_source(Path(settings.sld_storage_root), relative_path)
        if not source_path.is_file():
            raise SldContractError(
                404,
                "SLD_SOURCE_NOT_FOUND",
                "원본 파일을 찾을 수 없습니다.",
            )
    except SldContractError as error:
        return _error(request, error)
    return FileResponse(
        source_path,
        media_type=mime_type,
        filename=file_name,
        content_disposition_type="inline",
    )


@router.post("/buildings/{building_id}/sld-analyses/from-document", status_code=202)
async def post_sld_analysis_from_document(
    request: Request,
    session: WriteSession,
    building_id: UUID,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not _valid_idempotency_key(idempotency_key):
        return _error(
            request,
            SldContractError(
                422,
                "IDEMPOTENCY_KEY_REQUIRED",
                "안전한 재요청을 위한 Idempotency-Key가 필요합니다.",
            ),
        )
    settings = request.app.state.settings
    try:
        await ensure_demo_fire_building_document(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
            storage_root=Path(settings.sld_storage_root),
        )
        document = await building_sld_document(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
        )
        if document is None:
            raise SldContractError(
                409,
                "SLD_DOCUMENT_REQUIRED",
                "설비 추출 전에 관리자가 단선결선도를 등록해야 합니다.",
            )
        document_relative_path, _, _ = await sld_document_source(
            request.app.state.db_engine,
            profile=settings.profile,
            building_id=building_id,
        )
        document_path = _resolve_source(Path(settings.sld_storage_root), document_relative_path)
        if not document_path.is_file():
            raise SldContractError(404, "SLD_SOURCE_NOT_FOUND", "원본 파일을 찾을 수 없습니다.")
        content = document_path.read_bytes()
    except SldContractError as error:
        return _error(request, error)

    extension = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }[document["sourceMimeType"]]
    analysis_id = new_analysis_id()
    relative_path = f"{analysis_id}/source{extension}"
    source_path = _resolve_source(Path(settings.sld_storage_root), relative_path)
    source_path.parent.mkdir(parents=True, exist_ok=False)
    source_path.write_bytes(content)
    try:
        data = await create_analysis(
            request.app.state.db_engine,
            analysis_id=analysis_id,
            profile=settings.profile,
            building_id=building_id,
            source_file_name=document["sourceFileName"],
            source_mime_type=document["sourceMimeType"],
            source_size_bytes=document["sourceSizeBytes"],
            source_sha256=document["sourceSha256"],
            source_storage_path=relative_path,
            user_id=session.user_id,
            idempotency_key=str(idempotency_key),
            document_model=settings.upstage_document_model,
        )
    except SldContractError as error:
        source_path.unlink(missing_ok=True)
        source_path.parent.rmdir()
        return _error(request, error)
    if data["analysisId"] != str(analysis_id):
        source_path.unlink(missing_ok=True)
        source_path.parent.rmdir()
        return envelope(request, data)
    _queue_analysis(settings, analysis_id)
    return envelope(request, data)


@router.post("/buildings/{building_id}/sld-analyses", status_code=202)
async def post_sld_analysis(
    request: Request,
    session: WriteSession,
    building_id: UUID,
    document: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key or len(idempotency_key) > 160:
        return _error(
            request,
            SldContractError(
                422,
                "IDEMPOTENCY_KEY_REQUIRED",
                "안전한 재요청을 위한 Idempotency-Key가 필요합니다.",
            ),
        )
    settings = request.app.state.settings
    content = await document.read(settings.sld_max_upload_bytes + 1)
    if not content:
        return _error(request, SldContractError(422, "SLD_FILE_EMPTY", "파일이 비어 있습니다."))
    if len(content) > settings.sld_max_upload_bytes:
        return _error(
            request,
            SldContractError(
                413,
                "SLD_FILE_TOO_LARGE",
                f"파일은 {settings.sld_max_upload_bytes // (1024 * 1024)}MB 이하여야 합니다.",
            ),
        )
    detected = _detected_type(content)
    if detected is None:
        return _error(
            request,
            SldContractError(
                415,
                "SLD_FILE_TYPE_UNSUPPORTED",
                "PDF, PNG, JPG 단선결선도만 분석할 수 있습니다.",
            ),
        )
    mime_type, extension = detected
    analysis_id = new_analysis_id()
    storage_root = Path(settings.sld_storage_root)
    relative_path = f"{analysis_id}/source{extension}"
    source_path = _resolve_source(storage_root, relative_path)
    source_path.parent.mkdir(parents=True, exist_ok=False)
    source_path.write_bytes(content)
    source_name = Path(document.filename or f"single-line-diagram{extension}").name
    try:
        data = await create_analysis(
            request.app.state.db_engine,
            analysis_id=analysis_id,
            profile=settings.profile,
            building_id=building_id,
            source_file_name=source_name,
            source_mime_type=mime_type,
            source_size_bytes=len(content),
            source_sha256=hashlib.sha256(content).hexdigest(),
            source_storage_path=relative_path,
            user_id=session.user_id,
            idempotency_key=idempotency_key,
            document_model=settings.upstage_document_model,
        )
    except SldContractError as error:
        source_path.unlink(missing_ok=True)
        source_path.parent.rmdir()
        return _error(request, error)
    if data["analysisId"] != str(analysis_id):
        source_path.unlink(missing_ok=True)
        source_path.parent.rmdir()
        return envelope(request, data)
    celery_app.send_task(
        "esafe.analyze_sld",
        args=[str(analysis_id)],
        task_id=str(analysis_id),
        queue=f"{settings.celery_queue}-sld",
    )
    return envelope(request, data)


@router.get("/buildings/{building_id}/sld-analyses")
async def get_building_sld_analyses(
    request: Request,
    _: Session,
    building_id: UUID,
) -> Any:
    data = await building_analyses(request.app.state.db_engine, building_id)
    return envelope(request, data)


@router.get("/sld-analyses/{analysis_id}")
async def get_sld_analysis(
    request: Request,
    _: Session,
    analysis_id: UUID,
) -> Any:
    try:
        data = await analysis_detail(request.app.state.db_engine, analysis_id)
    except SldContractError as error:
        return _error(request, error)
    return envelope(request, data)


@router.post("/sld-analyses/{analysis_id}/retry", status_code=202)
async def post_sld_analysis_retry(
    request: Request,
    _: WriteSession,
    analysis_id: UUID,
) -> Any:
    try:
        data = await retry_analysis(request.app.state.db_engine, analysis_id)
    except SldContractError as error:
        return _error(request, error)
    settings = request.app.state.settings
    celery_app.send_task(
        "esafe.analyze_sld",
        args=[str(analysis_id)],
        task_id=f"{analysis_id}-v{data['version']}",
        queue=f"{settings.celery_queue}-sld",
    )
    return envelope(request, data)


@router.get("/sld-analyses/{analysis_id}/source")
async def get_sld_analysis_source(
    request: Request,
    _: Session,
    analysis_id: UUID,
) -> Response:
    try:
        relative_path, file_name, mime_type = await analysis_source(
            request.app.state.db_engine,
            analysis_id,
        )
        source_path = _resolve_source(
            Path(request.app.state.settings.sld_storage_root),
            relative_path,
        )
        if not source_path.is_file():
            raise SldContractError(
                404,
                "SLD_SOURCE_NOT_FOUND",
                "원본 파일을 찾을 수 없습니다.",
            )
    except SldContractError as error:
        return _error(request, error)
    return FileResponse(
        source_path,
        media_type=mime_type,
        filename=file_name,
        content_disposition_type="inline",
    )


@router.get("/sld-analyses/{analysis_id}/pages/{page_number}/preview")
async def get_sld_analysis_page_preview(
    request: Request,
    _: Session,
    analysis_id: UUID,
    page_number: int,
) -> Response:
    try:
        relative_path, _file_name, mime_type = await analysis_source(
            request.app.state.db_engine,
            analysis_id,
        )
        source_path = _resolve_source(
            Path(request.app.state.settings.sld_storage_root),
            relative_path,
        )
        if not source_path.is_file():
            raise SldContractError(
                404,
                "SLD_SOURCE_NOT_FOUND",
                "원본 파일을 찾을 수 없습니다.",
            )
        if mime_type in {"image/png", "image/jpeg"}:
            if page_number != 1:
                raise SldContractError(
                    404,
                    "SLD_PAGE_NOT_FOUND",
                    "요청한 도면 페이지를 찾을 수 없습니다.",
                )
            return FileResponse(
                source_path,
                media_type=mime_type,
                content_disposition_type="inline",
                headers={"Cache-Control": "private, max-age=3600"},
            )
        if mime_type != "application/pdf":
            raise SldContractError(
                415,
                "SLD_FILE_TYPE_UNSUPPORTED",
                "미리보기를 지원하지 않는 도면 형식입니다.",
            )
        preview = await run_in_threadpool(_render_pdf_page, source_path, page_number)
    except SldContractError as error:
        return _error(request, error)
    return Response(
        content=preview,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
