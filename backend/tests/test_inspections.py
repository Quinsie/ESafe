import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_csrf, require_session
from app.auth import AuthenticatedSession
from app.inspections import (
    InspectionContractError,
    _audit_metadata,
    expanded_filters,
    inclusive_days,
)
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


def test_inspection_capacity_uses_inclusive_days() -> None:
    assert inclusive_days(date(2026, 8, 3), date(2026, 8, 3)) == 1
    assert inclusive_days(date(2026, 8, 3), date(2026, 8, 7)) == 5
    try:
        inclusive_days(date(2026, 8, 4), date(2026, 8, 3))
    except InspectionContractError as error:
        assert error.code == "INVALID_INSPECTION_DATE_RANGE"
    else:
        raise AssertionError("inverted range accepted")


def test_expanded_filters_are_deterministic_and_relaxed() -> None:
    assert expanded_filters(10, 0.9) == (25.0, 0.85)
    assert expanded_filters(25, 0.02) == (100.0, 0.0)
    assert expanded_filters(1, 0.5) == expanded_filters(1, 0.5)


def test_inspection_audit_metadata_serializes_case_and_building_ids() -> None:
    case_id = uuid4()
    building_id = uuid4()

    value = json.loads(
        _audit_metadata(
            {"caseId": str(case_id)},
            {"case": {"case_id": case_id}, "building": {"building_id": building_id}},
        )
    )

    assert value["context"]["case"]["case_id"] == str(case_id)
    assert value["context"]["building"]["building_id"] == str(building_id)


def test_inspection_endpoints_require_authentication() -> None:
    simulation_id = uuid4()
    with TestClient(app) as client:
        for path in (
            "/api/v1/inspections/options",
            f"/api/v1/inspections/simulations/{simulation_id}",
            f"/api/v1/inspections/simulations/{simulation_id}/targets",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_inspection_options_contract(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    payload = {"regions": [], "facilityTypes": ["공장"], "algorithmVersion": "v1"}
    query = AsyncMock(return_value=payload)
    monkeypatch.setattr("app.api.inspections.inspection_options", query)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/inspections/options")
        assert response.status_code == 200
        assert response.json()["data"] == payload
    finally:
        app.dependency_overrides.clear()


def test_inspection_creation_keeps_identifiers_and_queues_worker(monkeypatch) -> None:
    session = _session()
    app.dependency_overrides[require_csrf] = lambda: session
    simulation_id = uuid4()
    building_id = uuid4()
    query = AsyncMock(
        return_value={
            "inspectionSimulationId": str(simulation_id),
            "status": "QUEUED",
            "reused": False,
        }
    )
    send_task = monkeypatch.setattr("app.api.inspections.create_simulation", query)
    task = monkeypatch.setattr(
        "app.api.inspections.celery_app.send_task", lambda *args, **kwargs: None
    )
    del send_task, task
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/inspections/simulations",
                headers={"Idempotency-Key": "inspection-test"},
                json={
                    "regionCode": "46170",
                    "buildingId": str(building_id),
                    "facilityTypes": ["공장"],
                    "startDate": "2026-08-03",
                    "endDate": "2026-08-04",
                    "teamCount": 2,
                    "dailyCapacityPerTeam": 10,
                    "topPercentile": 10,
                    "minimumScore": 0.9,
                },
            )
        assert response.status_code == 202
        assert response.json()["data"]["inspectionSimulationId"] == str(simulation_id)
        assert query.await_args.kwargs["region_code"] == "46170"
        assert query.await_args.kwargs["building_id"] == building_id
        assert query.await_args.kwargs["facility_types"] == ["공장"]
    finally:
        app.dependency_overrides.clear()
