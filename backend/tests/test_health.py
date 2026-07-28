from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import app


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
        response = client.get("/api/v1/meta", headers={"x-request-id": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id
    assert response.json()["meta"]["requestId"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/meta", headers={"x-request-id": "not-a-uuid"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "not-a-uuid"
    UUID(response.headers["x-request-id"])


def test_readiness_fails_closed_without_dependencies() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "DOWN"
