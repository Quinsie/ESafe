from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.config import Settings
from app.main import PUBLIC_INTERNAL_ERROR_MESSAGE, app
from app.security import token_hash


def _authenticated_session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("test-session"),
        user_id=uuid4(),
        username="user",
        display_name="사용자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_liveness_has_contract_and_generated_request_id() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    UUID(response.headers["x-request-id"])
    body = response.json()
    assert body["data"]["status"] == "UP"
    assert body["meta"]["profile"] == "LIVE"
    assert body["error"] is None


def test_valid_request_id_is_preserved() -> None:
    request_id = str(uuid4())
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"x-request-id": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id
    assert response.json()["meta"]["requestId"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"x-request-id": "not-a-uuid"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "not-a-uuid"
    UUID(response.headers["x-request-id"])


def test_readiness_fails_closed_without_dependencies() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "DOWN"


def test_public_korean_labels_are_preserved() -> None:
    assert Settings(ESAFE_PROFILE="LIVE").profile_badge == "실시간 연동"
    assert Settings(ESAFE_PROFILE="DEMO").profile_badge == "체험 데이터"
    assert PUBLIC_INTERNAL_ERROR_MESSAGE == "요청을 처리하지 못했습니다."


def test_reference_metadata_exposes_active_lineage(monkeypatch) -> None:
    metadata = {
        "importId": "20260729T0438-s2-v27-1",
        "manifestHash": "a" * 64,
        "buildingCount": 217238,
        "riskCount": 217238,
    }
    monkeypatch.setattr(
        "app.api.health.reference_dataset_metadata", AsyncMock(return_value=metadata)
    )
    app.dependency_overrides[require_session] = _authenticated_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/reference/meta")
        assert response.status_code == 200
        assert response.json()["data"] == metadata
    finally:
        app.dependency_overrides.clear()


def test_reference_metadata_fails_closed_without_active_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.health.reference_dataset_metadata", AsyncMock(return_value=None)
    )
    app.dependency_overrides[require_session] = _authenticated_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/reference/meta")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "REFERENCE_DATA_NOT_READY"
    finally:
        app.dependency_overrides.clear()
