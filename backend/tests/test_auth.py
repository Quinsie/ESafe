from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.auth import AuthenticatedSession, NewSession, UserCredential
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


def test_login_sets_profile_scoped_session_contract(monkeypatch) -> None:
    user = UserCredential(uuid4(), "user", "사용자", "argon")
    monkeypatch.setattr("app.api.auth.is_login_rate_limited", AsyncMock(return_value=False))
    monkeypatch.setattr("app.api.auth.authenticate_credentials", AsyncMock(return_value=user))
    monkeypatch.setattr("app.api.auth.clear_login_failures", AsyncMock())
    monkeypatch.setattr(
        "app.api.auth.create_session_with_audit",
        AsyncMock(
            return_value=NewSession(
                "opaque-session",
                "csrf",
                datetime.now(UTC) + timedelta(hours=12),
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"origin": "http://127.0.0.1:8080"},
            json={"userId": "user", "password": "secret"},
        )

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any("esafe_live_session=opaque-session" in item for item in cookies)
    assert any("HttpOnly" in item and "Path=/live/" in item for item in cookies)
    assert any("esafe_live_csrf=csrf" in item and "SameSite=strict" in item for item in cookies)
    assert response.json()["data"]["user"]["displayName"] == "사용자"


def test_login_failure_is_generic_and_rate_counted(monkeypatch) -> None:
    monkeypatch.setattr("app.api.auth.is_login_rate_limited", AsyncMock(return_value=False))
    monkeypatch.setattr("app.api.auth.authenticate_credentials", AsyncMock(return_value=None))
    increment = AsyncMock(return_value=1)
    audit = AsyncMock()
    monkeypatch.setattr("app.api.auth.register_login_failure", increment)
    monkeypatch.setattr("app.api.auth.record_auth_event", audit)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"userId": "unknown", "password": "wrong"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "아이디 또는 비밀번호를 확인해 주세요.",
    }
    increment.assert_awaited_once()
    audit.assert_awaited_once()


def test_cross_origin_login_is_rejected_before_credentials(monkeypatch) -> None:
    authenticate = AsyncMock()
    monkeypatch.setattr("app.api.auth.authenticate_credentials", authenticate)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"origin": "https://attacker.invalid", "sec-fetch-site": "cross-site"},
            json={"userId": "user", "password": "secret"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    authenticate.assert_not_awaited()


def test_protected_metadata_requires_session() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/meta")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_logout_requires_matching_double_submit_csrf(monkeypatch) -> None:
    current_session = _session()
    app.dependency_overrides[require_session] = lambda: current_session
    revoke = AsyncMock()
    monkeypatch.setattr("app.api.auth.revoke_session", revoke)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/logout",
                headers={"x-csrf-token": "csrf", "cookie": "esafe_live_csrf=csrf"},
            )
        assert response.status_code == 200
        revoke.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
