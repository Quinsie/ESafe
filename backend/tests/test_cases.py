from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.cases import CaseContractError
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


def test_case_endpoints_require_authentication() -> None:
    case_id = uuid4()
    with TestClient(app) as client:
        for path in (
            "/api/v1/cases",
            f"/api/v1/cases/{case_id}",
            f"/api/v1/cases/{case_id}/timeline",
            f"/api/v1/cases/{case_id}/impact-buildings",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_case_read_contracts_are_independent(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    case_id = uuid4()
    cases = {
        "summary": {"total": 1, "open": 1},
        "items": [{"caseId": str(case_id), "title": "Case"}],
        "page": 1,
        "pageSize": 20,
        "total": 1,
    }
    detail = {"caseId": str(case_id), "signals": [], "relations": []}
    timeline = {"items": [], "page": 1, "pageSize": 50, "total": 0}
    impact = {
        "summary": {"impactBuildings": 1},
        "items": [{"buildingId": str(uuid4())}],
        "page": 1,
        "pageSize": 100,
        "total": 1,
    }
    list_mock = AsyncMock(return_value=cases)
    detail_mock = AsyncMock(return_value=detail)
    timeline_mock = AsyncMock(return_value=timeline)
    impact_mock = AsyncMock(return_value=impact)
    monkeypatch.setattr("app.api.cases.case_list", list_mock)
    monkeypatch.setattr("app.api.cases.case_detail", detail_mock)
    monkeypatch.setattr("app.api.cases.case_timeline", timeline_mock)
    monkeypatch.setattr("app.api.cases.case_impact_buildings", impact_mock)
    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/api/v1/cases?status=ACTIVE&caseType=FIRE"
                "&source=NFDS&regionCode=29&search=fire&sort=updated"
            )
            detail_response = client.get(f"/api/v1/cases/{case_id}")
            timeline_response = client.get(f"/api/v1/cases/{case_id}/timeline")
            impact_response = client.get(
                f"/api/v1/cases/{case_id}/impact-buildings"
                "?riskThreshold=10&incidentOnly=false&sort=risk"
            )
        assert list_response.status_code == 200
        assert list_response.json()["data"] == cases
        assert detail_response.json()["data"] == detail
        assert timeline_response.json()["data"] == timeline
        assert impact_response.json()["data"] == impact
        list_mock.assert_awaited_once()
        impact_mock.assert_awaited_once()
        assert list_mock.await_args.kwargs["region_code"] == "29"
        assert list_mock.await_args.kwargs["case_type"] == "FIRE"
        assert impact_mock.await_args.kwargs["risk_threshold"] == 10
    finally:
        app.dependency_overrides.clear()


def test_missing_case_has_stable_public_error(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    case_id = uuid4()
    monkeypatch.setattr("app.api.cases.case_detail", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.cases.case_timeline", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.cases.case_impact_buildings", AsyncMock(return_value=None)
    )
    try:
        with TestClient(app) as client:
            responses = (
                client.get(f"/api/v1/cases/{case_id}"),
                client.get(f"/api/v1/cases/{case_id}/timeline"),
                client.get(f"/api/v1/cases/{case_id}/impact-buildings"),
            )
        for response in responses:
            assert response.status_code == 404
            assert response.json()["error"] == {
                "code": "CASE_NOT_FOUND",
                "message": "Case를 찾을 수 없습니다.",
            }
    finally:
        app.dependency_overrides.clear()


def test_case_contract_error_is_not_an_internal_error(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    contract_error = CaseContractError(
        422,
        "INVALID_RISK_THRESHOLD",
        "위험도 필터가 올바르지 않습니다.",
    )
    monkeypatch.setattr(
        "app.api.cases.case_impact_buildings",
        AsyncMock(side_effect=contract_error),
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/cases/{uuid4()}/impact-buildings?riskThreshold=2"
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_RISK_THRESHOLD"
    finally:
        app.dependency_overrides.clear()
