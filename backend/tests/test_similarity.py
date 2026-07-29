import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.main import app
from app.security import token_hash
from app.similarity import (
    _cached_candidate_result,
    _candidate_cache,
    _candidate_inflight,
    classify_building_use,
    condition_match,
)


def _session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("session"),
        user_id=uuid4(),
        username="user",
        display_name="사용자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_building_use_classification_is_deterministic() -> None:
    assert classify_building_use("제2종근린생활시설") == "근린생활시설"
    assert classify_building_use("공동주택") == "공동주택"
    assert classify_building_use("분류되지 않은 용도") is None


def test_condition_match_separates_facility_and_geography() -> None:
    exact = condition_match("공장", "전라남도", "나주시", "공장", "전라남도", "나주시")
    assert exact["score"] == 100
    assert exact["isProbability"] is False
    assert [item["points"] for item in exact["components"]] == [60, 40]

    province_only = condition_match("공장", "전라남도", "나주시", "창고시설", "전라남도", "목포시")
    assert province_only["score"] == 20


@pytest.mark.asyncio
async def test_candidate_cache_coalesces_concurrent_identical_queries() -> None:
    key = (991_337, uuid4(), 1, 20)
    _candidate_cache.clear()
    _candidate_inflight.clear()
    calls = 0

    async def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"items": [{"buildingId": "one"}]}

    try:
        results = await asyncio.gather(
            *[_cached_candidate_result(key, loader) for _ in range(10)]
        )
        await asyncio.sleep(0)
        cached = await _cached_candidate_result(key, loader)
        assert calls == 1
        assert all(result == cached for result in results)
        assert key not in _candidate_inflight
    finally:
        _candidate_cache.clear()
        _candidate_inflight.clear()


def test_similarity_endpoints_require_authentication() -> None:
    incident_id = uuid4()
    building_id = uuid4()
    with TestClient(app) as client:
        for path in (
            "/api/v1/similar/incidents",
            f"/api/v1/similar/facilities?referenceIncident={incident_id}",
            f"/api/v1/similar/compare?referenceIncident={incident_id}&candidateBuilding={building_id}",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_similarity_routes_keep_selected_identifiers(monkeypatch) -> None:
    incident_id = uuid4()
    building_id = uuid4()
    app.dependency_overrides[require_session] = _session
    incident_payload = {
        "items": [],
        "pagination": {"page": 1, "pageSize": 20, "total": 0, "totalPages": 0},
        "selection": {"building": {"buildingId": str(building_id)}},
    }
    candidate_payload = {
        "referenceIncident": {"incidentId": str(incident_id)},
        "items": [{"buildingId": str(building_id)}],
    }
    comparison_payload = {
        "referenceIncident": {"incidentId": str(incident_id)},
        "candidateBuilding": {"buildingId": str(building_id)},
    }
    monkeypatch.setattr(
        "app.api.similarity.incident_search", AsyncMock(return_value=incident_payload)
    )
    monkeypatch.setattr(
        "app.api.similarity.candidate_buildings", AsyncMock(return_value=candidate_payload)
    )
    monkeypatch.setattr("app.api.similarity.comparison", AsyncMock(return_value=comparison_payload))
    try:
        with TestClient(app) as client:
            incidents = client.get(f"/api/v1/similar/incidents?building={building_id}")
            facilities = client.get(f"/api/v1/similar/facilities?referenceIncident={incident_id}")
            compare = client.get(
                f"/api/v1/similar/compare?referenceIncident={incident_id}&candidateBuilding={building_id}"
            )
        assert incidents.json()["data"] == incident_payload
        assert facilities.json()["data"] == candidate_payload
        assert compare.json()["data"] == comparison_payload
    finally:
        app.dependency_overrides.clear()


def test_incident_filters_reject_inverted_date_range_before_database_access() -> None:
    app.dependency_overrides[require_session] = _session
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/similar/incidents?from=2026-05-02&to=2026-05-01&sort=oldest"
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"
    finally:
        app.dependency_overrides.clear()
