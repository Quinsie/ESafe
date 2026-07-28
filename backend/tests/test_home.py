from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
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


def test_home_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        for path in ("/api/v1/briefing", "/api/v1/tasks/summary", "/api/v1/sources/health"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_home_panels_have_independent_contracts(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    briefing = {
        "headline": {"state": "NO_ACTIVE_CASES", "title": "현재 Case 없음", "caseId": None},
        "metrics": {"activeCases": 0},
        "priorityRegions": [{"regionCode": "29170", "name": "북구"}],
        "recentCases": [],
        "dataAsOf": "2026-07-29T00:00:00+00:00",
    }
    tasks = {"counts": {"queued": 0}, "items": [], "dataAsOf": None}
    sources = {
        "summary": "OUTAGE",
        "sources": [{"source": "NFDS", "status": "OUTAGE"}],
        "dataAsOf": "2026-07-29T00:00:00+00:00",
    }
    monkeypatch.setattr("app.api.home.briefing_data", AsyncMock(return_value=briefing))
    monkeypatch.setattr("app.api.home.task_summary_data", AsyncMock(return_value=tasks))
    monkeypatch.setattr("app.api.home.source_health_data", AsyncMock(return_value=sources))
    try:
        with TestClient(app) as client:
            briefing_response = client.get("/api/v1/briefing")
            tasks_response = client.get("/api/v1/tasks/summary")
            sources_response = client.get("/api/v1/sources/health")
        assert briefing_response.status_code == 200
        assert briefing_response.json()["data"] == briefing
        assert tasks_response.status_code == 200
        assert tasks_response.json()["data"] == tasks
        assert sources_response.status_code == 200
        assert sources_response.json()["data"] == sources
    finally:
        app.dependency_overrides.clear()