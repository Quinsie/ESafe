from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_csrf, require_session
from app.auth import AuthenticatedSession
from app.document_content import build_initial_document_payload
from app.main import app
from app.security import token_hash


def _session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("session"),
        user_id=uuid4(),
        username="user",
        display_name="사용자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _payload() -> dict[str, object]:
    return build_initial_document_payload(
        variant="INCIDENT_REPORT",
        case={
            "caseId": "11111111-1111-4111-8111-111111111111",
            "caseNumber": "ES-20260729-000001",
            "title": "테스트 사건",
            "caseType": "FIRE",
            "status": "ACTIVE",
            "sourceStatus": "NFDS",
            "monitoringPriority": "URGENT",
            "openedAt": "2026-07-29T05:00:00+00:00",
            "normalizedAddress": "광주광역시 북구",
            "regionName": "광주광역시 북구",
        },
        recommendation=None,
        now=datetime(2026, 7, 29, tzinfo=UTC),
    ).model_dump(mode="json", by_alias=True)


def _detail(document_id: UUID, artifact_id: UUID) -> dict[str, object]:
    return {
        "documentDraftId": str(document_id),
        "documentVersionId": str(uuid4()),
        "caseId": "11111111-1111-4111-8111-111111111111",
        "variant": "INCIDENT_REPORT",
        "status": "DRAFT",
        "currentVersion": 1,
        "lockVersion": 1,
        "payload": _payload(),
        "artifacts": [
            {
                "documentArtifactId": str(artifact_id),
                "status": "QUEUED",
            }
        ],
    }


def test_document_endpoints_require_authentication() -> None:
    case_id = uuid4()
    document_id = uuid4()
    artifact_id = uuid4()
    with TestClient(app) as client:
        assert client.get("/api/v1/documents").status_code == 401
        assert client.get(f"/api/v1/documents/{document_id}").status_code == 401
        assert (
            client.get(
                f"/api/v1/document-artifacts/{artifact_id}/download"
            ).status_code
            == 401
        )
        assert (
            client.post(
                f"/api/v1/cases/{case_id}/documents",
                json={"variant": "INCIDENT_REPORT"},
                headers={"Idempotency-Key": "document-auth-create"},
            ).status_code
            == 401
        )


def test_document_create_and_update_queue_profile_artifacts(monkeypatch) -> None:
    session = _session()
    app.dependency_overrides[require_csrf] = lambda: session
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    document_id = uuid4()
    artifact_id = uuid4()
    detail = _detail(document_id, artifact_id)
    create_mock = AsyncMock(return_value=(detail, False))
    update_mock = AsyncMock(return_value=(detail, False))
    send_mock = Mock()
    monkeypatch.setattr(
        "app.api.documents.create_document_draft",
        create_mock,
    )
    monkeypatch.setattr(
        "app.api.documents.update_document_draft",
        update_mock,
    )
    monkeypatch.setattr("app.api.documents.celery_app.send_task", send_mock)
    try:
        with TestClient(app) as client:
            create_response = client.post(
                f"/api/v1/cases/{case_id}/documents",
                json={"variant": "INCIDENT_REPORT"},
                headers={"Idempotency-Key": "document-create-1"},
            )
            update_response = client.put(
                f"/api/v1/documents/{document_id}",
                json={"expectedVersion": 1, "payload": _payload()},
                headers={"Idempotency-Key": "document-update-1"},
            )
        assert create_response.status_code == 202
        assert update_response.status_code == 202
        assert create_mock.await_args.kwargs["user_id"] == session.user_id
        assert create_mock.await_args.kwargs["variant"] == "INCIDENT_REPORT"
        assert update_mock.await_args.kwargs["expected_version"] == 1
        assert send_mock.call_count == 2
        for call in send_mock.call_args_list:
            assert call.args[0] == "esafe.generate_document_artifact"
            assert call.kwargs["queue"] == "live-documents"
            assert call.kwargs["task_id"] == str(artifact_id)
    finally:
        app.dependency_overrides.clear()


def test_document_read_and_download_contracts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[require_session] = _session
    document_id = uuid4()
    artifact_id = uuid4()
    detail = _detail(document_id, artifact_id)
    library = {"items": [detail], "pagination": {"total": 1}}
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"%PDF-test\n%%EOF")
    monkeypatch.setattr(
        "app.api.documents.document_library",
        AsyncMock(return_value=library),
    )
    monkeypatch.setattr(
        "app.api.documents.document_detail",
        AsyncMock(return_value=detail),
    )
    monkeypatch.setattr(
        "app.api.documents.document_artifact_download",
        AsyncMock(return_value=(file_path, "report.pdf", "application/pdf")),
    )
    try:
        with TestClient(app) as client:
            list_response = client.get("/api/v1/documents")
            detail_response = client.get(f"/api/v1/documents/{document_id}")
            download_response = client.get(
                f"/api/v1/document-artifacts/{artifact_id}/download"
            )
        assert list_response.json()["data"] == library
        assert detail_response.json()["data"] == detail
        assert download_response.content == b"%PDF-test\n%%EOF"
        assert download_response.headers["cache-control"] == "private, no-store"
        assert download_response.headers["x-content-type-options"] == "nosniff"
    finally:
        app.dependency_overrides.clear()
