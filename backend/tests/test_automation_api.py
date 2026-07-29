from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.config import Settings
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


def test_automation_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        for path in ("/api/v1/automation/runs", "/api/v1/automation/policies"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_automation_activity_contract(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    activity = {
        "summary": {
            "todayActivity": 3,
            "waitingApproval": 0,
            "running": 1,
            "failedLast24h": 0,
        },
        "items": [
            {
                "occurredAt": "2026-07-29T00:00:00+00:00",
                "entryType": "AUTOMATION_RUN",
                "entryId": str(uuid4()),
                "status": "SUCCEEDED",
                "category": "SIGNAL_POLL",
            }
        ],
        "page": 1,
        "pageSize": 20,
        "total": 1,
        "dataAsOf": "2026-07-29T00:00:00+00:00",
    }
    query = AsyncMock(return_value=activity)
    monkeypatch.setattr("app.api.automation.automation_activity", query)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/automation/runs?status=SUCCEEDED&entryType=AUTOMATION_RUN"
                "&source=NFDS&hours=24&search=SIGNAL"
            )
        assert response.status_code == 200
        assert response.json()["data"] == activity
        assert query.await_args.kwargs["status"] == "SUCCEEDED"
        assert query.await_args.kwargs["entry_type"] == "AUTOMATION_RUN"
        assert query.await_args.kwargs["source"] == "NFDS"
        assert query.await_args.kwargs["hours"] == 24
        assert query.await_args.kwargs["search"] == "SIGNAL"
    finally:
        app.dependency_overrides.clear()


def test_automation_policy_is_read_only_and_does_not_expose_credentials() -> None:
    app.dependency_overrides[require_session] = _session
    try:
        with TestClient(app) as client:
            original_settings = app.state.settings
            app.state.settings = Settings(
                ESAFE_PROFILE="LIVE",
                ESAFE_SESSION_SECRET="x" * 32,
                NFDS_ENABLED=False,
                DATA_GO_KR_SERVICE_KEY="should-never-appear",
            )
            try:
                response = client.get("/api/v1/automation/policies")
                unsupported = client.post("/api/v1/automation/policies", json={})
            finally:
                app.state.settings = original_settings
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["mutable"] is False
        assert payload["sources"][0] == {
            "source": "NFDS",
            "enabled": False,
            "mode": "LIVE",
        }
        assert "should-never-appear" not in response.text
        assert unsupported.status_code == 405
    finally:
        app.dependency_overrides.clear()
