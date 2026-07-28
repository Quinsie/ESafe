from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession
from app.main import app
from app.security import token_hash
from app.spatial import SpatialContractError, parse_bbox


def _session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("session"),
        user_id=uuid4(),
        username="user",
        display_name="사용자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_spatial_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        for path in (
            "/api/v1/map/config",
            "/api/v1/map/regions",
            "/api/v1/map/districts?parentCode=29",
            "/api/v1/map/buildings/14/13964/6488.mvt",
            "/api/v1/map/buildings?bbox=126.8,35.1,126.9,35.2&zoom=14",
            "/api/v1/regions/29170",
            f"/api/v1/buildings/{uuid4()}",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_bbox_requires_building_zoom_and_bounded_viewport() -> None:
    parsed = parse_bbox("126.80,35.10,126.90,35.20", 14)
    assert parsed.west == 126.8
    for value, zoom, expected in (
        ("126.8,35.1,126.9", 14, "INVALID_BBOX"),
        ("126.9,35.1,126.8,35.2", 14, "INVALID_BBOX"),
        ("126.8,35.1,126.9,35.2", 13, "BUILDING_ZOOM_REQUIRED"),
        ("126.0,34.0,127.0,35.0", 14, "VIEWPORT_TOO_LARGE"),
    ):
        try:
            parse_bbox(value, zoom)
        except SpatialContractError as error:
            assert error.code == expected
        else:
            raise AssertionError("SpatialContractError expected")


def test_spatial_contracts_are_independent(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    collection = {
        "type": "FeatureCollection",
        "features": [{"id": "29", "properties": {"name": "광주광역시"}}],
    }
    region = {"regionCode": "29170", "name": "북구", "topBuildings": []}
    building_id = uuid4()
    building = {"buildingId": str(building_id), "name": "건물명 미등록"}
    monkeypatch.setattr("app.api.spatial.region_features", AsyncMock(return_value=collection))
    monkeypatch.setattr("app.api.spatial.region_detail", AsyncMock(return_value=region))
    monkeypatch.setattr("app.api.spatial.building_detail", AsyncMock(return_value=building))
    monkeypatch.setattr("app.api.spatial.building_tile", AsyncMock(return_value=b"mvt"))
    try:
        with TestClient(app) as client:
            regions_response = client.get("/api/v1/map/regions")
            region_response = client.get("/api/v1/regions/29170")
            building_response = client.get(f"/api/v1/buildings/{building_id}")
            tile_response = client.get("/api/v1/map/buildings/14/13964/6488.mvt")
        assert regions_response.json()["data"] == collection
        assert region_response.json()["data"] == region
        assert building_response.json()["data"] == building
        assert tile_response.content == b"mvt"
        assert tile_response.headers["content-type"].startswith(
            "application/vnd.mapbox-vector-tile"
        )
    finally:
        app.dependency_overrides.clear()