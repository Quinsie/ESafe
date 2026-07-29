from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.config import Settings
from app.demo.playback import _reset_rows, require_demo_profile
from app.main import app
from app.security import token_hash
from app.workflow import WorkflowContractError


def _session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("session"),
        user_id=uuid4(),
        username="user",
        display_name="사용자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_demo_catalog_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/scenarios")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_demo_catalog_is_blocked_in_live_profile() -> None:
    try:
        require_demo_profile("LIVE")
    except WorkflowContractError as error:
        assert error.status_code == 403
        assert error.code == "DEMO_PROFILE_REQUIRED"
    else:
        raise AssertionError("LIVE profile unexpectedly accepted DEMO controls")


def test_demo_catalog_contract(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    item = {
        "scenarioId": str(uuid4()),
        "code": "DS-01",
        "name": "화재 전체 여정",
        "description": "설명",
        "scenarioVersion": 1,
        "playback": None,
    }
    query = AsyncMock(return_value={"items": [item]})
    monkeypatch.setattr("app.api.demo.scenario_catalog", query)
    try:
        with TestClient(app) as client:
            original_settings = app.state.settings
            app.state.settings = Settings(
                ESAFE_PROFILE="DEMO",
                ESAFE_SESSION_SECRET="x" * 32,
            )
            try:
                response = client.get("/api/v1/demo/scenarios")
            finally:
                app.state.settings = original_settings
        assert response.status_code == 200
        assert response.json()["data"] == {"items": [item]}
        assert query.await_args.kwargs["profile"] == "DEMO"
    finally:
        app.dependency_overrides.clear()


def test_demo_catalog_live_error_contract(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    error = WorkflowContractError(
        403,
        "DEMO_PROFILE_REQUIRED",
        "시나리오 제어는 체험 데이터 환경에서만 사용할 수 있습니다.",
    )
    query = AsyncMock(side_effect=error)
    monkeypatch.setattr("app.api.demo.scenario_catalog", query)
    try:
        with TestClient(app) as client:
            original_settings = app.state.settings
            app.state.settings = Settings(
                ESAFE_PROFILE="LIVE",
                ESAFE_SESSION_SECRET="x" * 32,
            )
            try:
                response = client.get("/api/v1/demo/scenarios")
            finally:
                app.state.settings = original_settings
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "DEMO_PROFILE_REQUIRED"
    finally:
        app.dependency_overrides.clear()


class _ResetResult:
    rowcount = 0

    def scalars(self) -> "_ResetResult":
        return self

    def all(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_demo_reset_deletes_recommendation_graph_before_case() -> None:
    statements: list[str] = []

    class Connection:
        async def execute(self, statement: Any) -> _ResetResult:
            statements.append(str(statement))
            return _ResetResult()

    counts, paths = await _reset_rows(Connection())  # type: ignore[arg-type]

    recommendation = next(
        i for i, value in enumerate(statements)
        if value.startswith("DELETE FROM recommendation ")
    )
    evidence = next(
        i for i, value in enumerate(statements)
        if value.startswith("DELETE FROM evidence_bundle ")
    )
    case = statements.index("DELETE FROM case_record WHERE is_simulated")
    assert recommendation < evidence < case
    assert counts["recommendations"] == 0
    assert counts["evidence_bundles"] == 0
    assert paths == []
