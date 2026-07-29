from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import require_csrf, require_session
from app.auth import AuthenticatedSession
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


def test_approval_endpoints_require_authentication() -> None:
    approval_id = uuid4()
    recommendation_id = uuid4()
    with TestClient(app) as client:
        assert client.get("/api/v1/approvals").status_code == 401
        assert client.get(f"/api/v1/approvals/{approval_id}").status_code == 401
        assert (
            client.post(
                f"/api/v1/recommendations/{recommendation_id}/approval-requests",
                headers={"Idempotency-Key": "approval-request-auth"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={"Idempotency-Key": "approval-decision-auth"},
                json={
                    "expectedVersion": 1,
                    "decision": "APPROVED",
                    "reason": "확인",
                    "warningAcknowledged": True,
                },
            ).status_code
            == 401
        )


def test_approval_read_contracts(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    approval_id = uuid4()
    listing = {"items": [], "page": 1, "pageSize": 20, "total": 0}
    detail = {"approvalRequestId": str(approval_id), "status": "APPROVAL_PENDING"}
    monkeypatch.setattr(
        "app.api.approvals.approval_list", AsyncMock(return_value=listing)
    )
    monkeypatch.setattr(
        "app.api.approvals.approval_detail", AsyncMock(return_value=detail)
    )
    try:
        with TestClient(app) as client:
            list_response = client.get("/api/v1/approvals?status=APPROVAL_PENDING")
            detail_response = client.get(f"/api/v1/approvals/{approval_id}")
        assert list_response.json()["data"] == listing
        assert detail_response.json()["data"] == detail
    finally:
        app.dependency_overrides.clear()


def test_approval_mutations_pass_user_version_warning_and_key(monkeypatch) -> None:
    session = _session()
    app.dependency_overrides[require_csrf] = lambda: session
    approval_id = uuid4()
    recommendation_id = uuid4()
    requested = {
        "approvalRequestId": str(approval_id),
        "status": "APPROVAL_PENDING",
    }
    decided = {
        "approvalRequestId": str(approval_id),
        "status": "APPROVED",
    }
    request_mock = AsyncMock(return_value=requested)
    decision_mock = AsyncMock(return_value=decided)
    monkeypatch.setattr(
        "app.api.approvals.request_recommendation_approval", request_mock
    )
    monkeypatch.setattr(
        "app.api.approvals.decide_approval", decision_mock
    )
    try:
        with TestClient(app) as client:
            request_response = client.post(
                f"/api/v1/recommendations/{recommendation_id}/approval-requests",
                headers={"Idempotency-Key": "approval-request-1"},
            )
            decision_response = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={"Idempotency-Key": "approval-decision-1"},
                json={
                    "expectedVersion": 1,
                    "decision": "APPROVED",
                    "reason": "근거와 실행 범위를 확인했습니다.",
                    "warningAcknowledged": True,
                },
            )
        assert request_response.status_code == 201
        assert request_response.json()["data"] == requested
        assert decision_response.status_code == 200
        assert decision_response.json()["data"] == decided
        assert request_mock.await_args.kwargs["user_id"] == session.user_id
        assert (
            request_mock.await_args.kwargs["idempotency_key"]
            == "approval-request-1"
        )
        assert decision_mock.await_args.kwargs["expected_version"] == 1
        assert decision_mock.await_args.kwargs["warning_acknowledged"] is True
    finally:
        app.dependency_overrides.clear()


def test_approval_contract_errors_keep_public_shape(monkeypatch) -> None:
    app.dependency_overrides[require_csrf] = _session
    error = WorkflowContractError(
        422,
        "WARNING_ACKNOWLEDGEMENT_REQUIRED",
        "근거 부족·충돌 경고를 확인해야 승인할 수 있습니다.",
    )
    monkeypatch.setattr(
        "app.api.approvals.decide_approval",
        AsyncMock(side_effect=error),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/approvals/{uuid4()}/decision",
                headers={"Idempotency-Key": "approval-warning-check"},
                json={
                    "expectedVersion": 1,
                    "decision": "APPROVED",
                    "reason": "승인",
                    "warningAcknowledged": False,
                },
            )
        assert response.status_code == 422
        assert response.json()["error"] == {
            "code": "WARNING_ACKNOWLEDGEMENT_REQUIRED",
            "message": "근거 부족·충돌 경고를 확인해야 승인할 수 있습니다.",
        }
    finally:
        app.dependency_overrides.clear()
