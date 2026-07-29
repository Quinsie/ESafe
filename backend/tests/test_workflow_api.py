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


def test_workflow_read_endpoints_require_authentication() -> None:
    case_id = uuid4()
    work_item_id = uuid4()
    with TestClient(app) as client:
        paths = (
            f"/api/v1/cases/{case_id}/evidence",
            f"/api/v1/cases/{case_id}/work-items",
            f"/api/v1/cases/{case_id}/closure-review",
            f"/api/v1/work-items/{work_item_id}",
        )
        for path in paths:
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_workflow_read_contracts(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    case_id = uuid4()
    work_item_id = uuid4()
    evidence = {
        "case": {"caseId": str(case_id)},
        "evidenceStatus": "INSUFFICIENT",
        "officialEvidence": [],
    }
    tasks = {"summary": {"total": 1}, "items": [{"workItemId": str(work_item_id)}]}
    task = {"workItemId": str(work_item_id), "version": 1}
    closure = {"caseId": str(case_id), "closurePolicy": "PENDING_USER_DECISION"}
    monkeypatch.setattr(
        "app.api.workflow.case_evidence", AsyncMock(return_value=evidence)
    )
    monkeypatch.setattr(
        "app.api.workflow.case_work_items", AsyncMock(return_value=tasks)
    )
    monkeypatch.setattr(
        "app.api.workflow.work_item_detail", AsyncMock(return_value=task)
    )
    monkeypatch.setattr(
        "app.api.workflow.case_closure_review", AsyncMock(return_value=closure)
    )
    try:
        with TestClient(app) as client:
            assert (
                client.get(f"/api/v1/cases/{case_id}/evidence").json()["data"]
                == evidence
            )
            assert (
                client.get(f"/api/v1/cases/{case_id}/work-items").json()["data"]
                == tasks
            )
            assert (
                client.get(f"/api/v1/work-items/{work_item_id}").json()["data"]
                == task
            )
            assert (
                client.get(f"/api/v1/cases/{case_id}/closure-review").json()["data"]
                == closure
            )
    finally:
        app.dependency_overrides.clear()


def test_workflow_mutations_pass_session_version_and_idempotency(monkeypatch) -> None:
    session = _session()
    app.dependency_overrides[require_csrf] = lambda: session
    case_id = uuid4()
    work_item_id = uuid4()
    checklist_item_id = uuid4()
    created = {"workItemId": str(work_item_id), "version": 1}
    transitioned = {"workItemId": str(work_item_id), "version": 2}
    checked = {"workItemId": str(work_item_id), "version": 3}
    create_mock = AsyncMock(return_value=created)
    transition_mock = AsyncMock(return_value=transitioned)
    checklist_mock = AsyncMock(return_value=checked)
    monkeypatch.setattr("app.api.workflow.create_case_work_item", create_mock)
    monkeypatch.setattr("app.api.workflow.transition_work_item", transition_mock)
    monkeypatch.setattr("app.api.workflow.update_checklist_item", checklist_mock)
    try:
        with TestClient(app) as client:
            create_response = client.post(
                f"/api/v1/cases/{case_id}/work-items",
                headers={"Idempotency-Key": "create-1"},
                json={
                    "title": "현장 확인",
                    "workType": "FIELD_CHECK",
                    "priority": "HIGH",
                    "checklist": ["신호 확인"],
                },
            )
            transition_response = client.patch(
                f"/api/v1/work-items/{work_item_id}/status",
                headers={"Idempotency-Key": "transition-1"},
                json={
                    "expectedVersion": 1,
                    "targetStatus": "RUNNING",
                    "reason": "확인 시작",
                },
            )
            checklist_response = client.patch(
                f"/api/v1/work-items/{work_item_id}/checklist/{checklist_item_id}",
                headers={"Idempotency-Key": "check-1"},
                json={
                    "expectedWorkVersion": 2,
                    "status": "DONE",
                    "note": "확인함",
                },
            )
        assert create_response.status_code == 201
        assert create_response.json()["data"] == created
        assert transition_response.json()["data"] == transitioned
        assert checklist_response.json()["data"] == checked
        assert create_mock.await_args.kwargs["idempotency_key"] == "create-1"
        assert create_mock.await_args.kwargs["user_id"] == session.user_id
        assert transition_mock.await_args.kwargs["expected_version"] == 1
        assert checklist_mock.await_args.kwargs["expected_work_version"] == 2
    finally:
        app.dependency_overrides.clear()


def test_workflow_contract_errors_keep_public_shape(monkeypatch) -> None:
    app.dependency_overrides[require_csrf] = _session
    error = WorkflowContractError(
        409,
        "INVALID_WORK_TRANSITION",
        "현재 상태에서는 변경할 수 없습니다.",
    )
    monkeypatch.setattr(
        "app.api.workflow.transition_work_item",
        AsyncMock(side_effect=error),
    )
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/work-items/{uuid4()}/status",
                headers={"Idempotency-Key": "transition-invalid"},
                json={
                    "expectedVersion": 1,
                    "targetStatus": "COMPLETED",
                    "reason": "잘못된 전이",
                },
            )
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "INVALID_WORK_TRANSITION",
            "message": "현재 상태에서는 변경할 수 없습니다.",
        }
    finally:
        app.dependency_overrides.clear()


def test_missing_workflow_resources_use_stable_errors(monkeypatch) -> None:
    app.dependency_overrides[require_session] = _session
    monkeypatch.setattr("app.api.workflow.case_evidence", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.workflow.work_item_detail", AsyncMock(return_value=None)
    )
    case_id = uuid4()
    work_item_id = uuid4()
    try:
        with TestClient(app) as client:
            case_response = client.get(f"/api/v1/cases/{case_id}/evidence")
            work_response = client.get(f"/api/v1/work-items/{work_item_id}")
        assert case_response.status_code == 404
        assert case_response.json()["error"]["code"] == "CASE_NOT_FOUND"
        assert work_response.status_code == 404
        assert work_response.json()["error"]["code"] == "WORK_ITEM_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
