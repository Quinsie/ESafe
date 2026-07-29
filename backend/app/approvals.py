from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.documents import _insert_artifacts
from app.workflow import WorkflowContractError

DECISIONS = frozenset(("APPROVED", "ON_HOLD", "DISCARDED"))
DOCUMENT_DISCARD_REASONS = frozenset(
    (
        "FALSE_ALARM",
        "DUPLICATE",
        "NO_ACTION_REQUIRED",
        "EVIDENCE_INAPPROPRIATE",
        "OTHER",
    )
)
APPROVAL_STATUSES = frozenset(
    ("APPROVAL_PENDING", "APPROVED", "ON_HOLD", "DISCARDED", "SUPERSEDED")
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _key(value: str | None) -> str:
    normalized = value.strip() if value else ""
    if not 8 <= len(normalized) <= 160:
        raise WorkflowContractError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "변경 요청에는 8~160자의 Idempotency-Key가 필요합니다.",
        )
    return normalized


def _hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approval_content(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in snapshot.items()
        if key not in ("status", "actions")
    } | {
        "actions": [
            {
                key: value
                for key, value in action.items()
                if key not in ("status", "workItemId", "workItemStatus")
            }
            for action in snapshot["actions"]
        ]
    }


def _audit_key(scope: str, profile: str, key: str) -> str:
    digest = hashlib.sha256(f"{profile}:{key}".encode()).hexdigest()
    return f"{scope}:{digest}"


async def _recommendation_target(
    connection: AsyncConnection,
    recommendation_id: UUID,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    recommendation = (
        (
            await connection.execute(
                text(
                    f"""
                    SELECT recommendation.*, bundle.status AS evidence_status,
                           bundle.warning AS evidence_warning,
                           case_record.case_number, case_record.title AS case_title,
                           case_record.case_type, case_record.status AS case_status,
                           case_record.monitoring_priority,
                           case_record.primary_region_code,
                           region.full_name AS region_name
                    FROM recommendation
                    JOIN evidence_bundle bundle
                      ON bundle.evidence_bundle_id =
                         recommendation.evidence_bundle_id
                    JOIN case_record
                      ON case_record.case_id = recommendation.case_id
                    LEFT JOIN admin_region region
                      ON region.region_code =
                         case_record.primary_region_code
                    WHERE recommendation.recommendation_id =
                          :recommendation_id
                    {"FOR UPDATE OF recommendation" if lock else ""}
                    """
                ),
                {"recommendation_id": recommendation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if recommendation is None:
        return None
    action_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT action.*, work.work_item_id,
                           work.status AS work_item_status
                    FROM recommendation_action action
                    LEFT JOIN work_item work
                      ON work.recommendation_action_id =
                         action.recommendation_action_id
                    WHERE action.recommendation_id = :recommendation_id
                    ORDER BY action.ordinal
                    """
                ),
                {"recommendation_id": recommendation_id},
            )
        )
        .mappings()
        .all()
    )
    action_ids = [row["recommendation_action_id"] for row in action_rows]
    citations: dict[UUID, list[dict[str, Any]]] = {}
    if action_ids:
        citation_rows = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT citation.*, document.title AS document_title,
                               document.issuing_agency
                        FROM evidence_citation citation
                        JOIN evidence_item item
                          ON item.evidence_item_id =
                             citation.evidence_item_id
                        JOIN rag_chunk chunk ON chunk.chunk_id = item.chunk_id
                        JOIN rag_document document
                          ON document.document_id = chunk.document_id
                        WHERE citation.recommendation_action_id =
                              ANY(CAST(:action_ids AS uuid[]))
                        ORDER BY citation.recommendation_action_id,
                                 citation.citation_id
                        """
                    ),
                    {"action_ids": action_ids},
                )
            )
            .mappings()
            .all()
        )
        for row in citation_rows:
            citations.setdefault(row["recommendation_action_id"], []).append(
                {
                    "citationId": str(row["citation_id"]),
                    "evidenceItemId": str(row["evidence_item_id"]),
                    "supportType": row["support_type"],
                    "quote": row["quote_text"],
                    "locator": row["locator"],
                    "documentTitle": row["document_title"],
                    "issuingAgency": row["issuing_agency"],
                }
            )
    actions = [
        {
            "recommendationActionId": str(row["recommendation_action_id"]),
            "ordinal": int(row["ordinal"]),
            "title": row["title"],
            "description": row["description"],
            "dueGuidance": row["due_guidance"],
            "evidenceStatus": row["evidence_status"],
            "warning": row["warning"],
            "status": row["status"],
            "checklist": list(row["checklist_template"] or []),
            "citations": citations.get(row["recommendation_action_id"], []),
            "workItemId": (
                str(row["work_item_id"])
                if row["work_item_id"] is not None
                else None
            ),
            "workItemStatus": row["work_item_status"],
        }
        for row in action_rows
    ]
    recommendation_data = dict(recommendation)
    snapshot = {
        "recommendationId": str(recommendation_data["recommendation_id"]),
        "caseId": str(recommendation_data["case_id"]),
        "evidenceBundleId": str(recommendation_data["evidence_bundle_id"]),
        "version": int(recommendation_data["version"]),
        "status": recommendation_data["status"],
        "generationMode": recommendation_data["generation_mode"],
        "factualSnapshot": recommendation_data["factual_snapshot"],
        "situationSummary": recommendation_data["situation_summary"],
        "requiredChecks": list(recommendation_data["required_checks"] or []),
        "uncertainties": list(recommendation_data["uncertainties"] or []),
        "conflicts": list(recommendation_data["conflicts"] or []),
        "warning": recommendation_data["warning"],
        "model": recommendation_data["model"],
        "promptVersion": recommendation_data["prompt_version"],
        "generationVersion": recommendation_data["generation_version"],
        "inputSha256": recommendation_data["input_sha256"],
        "outputSha256": recommendation_data["output_sha256"],
        "evidenceStatus": recommendation_data["evidence_status"],
        "evidenceWarning": recommendation_data["evidence_warning"],
        "actions": actions,
    }
    return {
        "case": {
            "caseId": str(recommendation_data["case_id"]),
            "caseNumber": recommendation_data["case_number"],
            "title": recommendation_data["case_title"],
            "caseType": recommendation_data["case_type"],
            "status": recommendation_data["case_status"],
            "monitoringPriority": recommendation_data["monitoring_priority"],
            "regionCode": recommendation_data["primary_region_code"],
            "regionName": recommendation_data["region_name"],
        },
        "recommendation": snapshot,
        "contentSha256": _hash(_approval_content(snapshot)),
    }


async def _document_target(
    connection: AsyncConnection,
    document_draft_id: UUID,
    target_version: int | None = None,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    row = (
        (
            await connection.execute(
                text(
                    f"""
                    SELECT
                        draft.document_draft_id,
                        draft.case_id,
                        draft.family,
                        draft.variant,
                        draft.title,
                        draft.status AS draft_status,
                        draft.current_version,
                        draft.version AS draft_lock_version,
                        version_record.document_version_id,
                        version_record.version AS document_version,
                        version_record.status AS version_status,
                        version_record.structured_payload,
                        version_record.evidence_status,
                        version_record.warning,
                        version_record.content_sha256,
                        version_record.template_key,
                        version_record.template_version,
                        version_record.template_sha256,
                        version_record.warning_acknowledged,
                        version_record.approval_reason,
                        version_record.created_at AS version_created_at,
                        version_record.approved_at,
                        case_record.case_number,
                        case_record.title AS case_title,
                        case_record.case_type,
                        case_record.status AS case_status,
                        case_record.monitoring_priority,
                        case_record.primary_region_code,
                        region.full_name AS region_name
                    FROM document_draft draft
                    JOIN document_version version_record
                      ON version_record.document_draft_id =
                         draft.document_draft_id
                     AND version_record.version =
                         COALESCE(
                           CAST(:target_version AS integer),
                           draft.current_version
                         )
                    LEFT JOIN case_record
                      ON case_record.case_id = draft.case_id
                    LEFT JOIN admin_region region
                      ON region.region_code =
                         case_record.primary_region_code
                    WHERE draft.document_draft_id = :document_draft_id
                    {
                        "FOR UPDATE OF draft, version_record"
                        if lock
                        else ""
                    }
                    """
                ),
                {
                    "document_draft_id": document_draft_id,
                    "target_version": target_version,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    artifact_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT *
                    FROM document_artifact
                    WHERE document_version_id = :document_version_id
                    ORDER BY stage, format, queued_at
                    """
                ),
                {"document_version_id": row["document_version_id"]},
            )
        )
        .mappings()
        .all()
    )
    delivery_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT delivery.*, user_record.display_name AS recorded_by_name
                    FROM document_manual_delivery delivery
                    JOIN app_user user_record
                      ON user_record.user_id = delivery.recorded_by
                    WHERE delivery.document_version_id = :document_version_id
                    ORDER BY delivery.delivered_at DESC,
                             delivery.document_manual_delivery_id
                    """
                ),
                {"document_version_id": row["document_version_id"]},
            )
        )
        .mappings()
        .all()
    )
    document = {
        "documentDraftId": str(row["document_draft_id"]),
        "documentVersionId": str(row["document_version_id"]),
        "caseId": str(row["case_id"]) if row["case_id"] else None,
        "family": row["family"],
        "variant": row["variant"],
        "title": row["title"],
        "draftStatus": row["draft_status"],
        "currentVersion": int(row["current_version"]),
        "draftLockVersion": int(row["draft_lock_version"]),
        "version": int(row["document_version"]),
        "versionStatus": row["version_status"],
        "payload": row["structured_payload"],
        "evidenceStatus": row["evidence_status"],
        "warning": row["warning"],
        "contentSha256": row["content_sha256"],
        "template": {
            "key": row["template_key"],
            "version": row["template_version"],
            "sha256": row["template_sha256"],
        },
        "warningAcknowledged": bool(row["warning_acknowledged"]),
        "approvalReason": row["approval_reason"],
        "versionCreatedAt": _iso(row["version_created_at"]),
        "approvedAt": _iso(row["approved_at"]),
        "artifacts": [
            {
                "documentArtifactId": str(artifact["document_artifact_id"]),
                "format": artifact["format"],
                "stage": artifact["stage"],
                "status": artifact["status"],
                "attemptCount": int(artifact["attempt_count"]),
                "fileName": artifact["file_name"],
                "mimeType": artifact["mime_type"],
                "sizeBytes": (
                    int(artifact["size_bytes"])
                    if artifact["size_bytes"] is not None
                    else None
                ),
                "sha256": artifact["sha256"],
                "errorCode": artifact["error_code"],
                "errorMessage": artifact["error_message"],
            }
            for artifact in artifact_rows
        ],
        "manualDeliveries": [
            {
                "documentManualDeliveryId": str(
                    delivery["document_manual_delivery_id"]
                ),
                "recipient": delivery["recipient"],
                "deliveredAt": _iso(delivery["delivered_at"]),
                "method": delivery["method"],
                "memo": delivery["memo"],
                "recordedBy": delivery["recorded_by_name"],
                "recordedAt": _iso(delivery["recorded_at"]),
                "externalDeliveryVerified": False,
            }
            for delivery in delivery_rows
        ],
    }
    return {
        "case": (
            {
                "caseId": str(row["case_id"]),
                "caseNumber": row["case_number"],
                "title": row["case_title"],
                "caseType": row["case_type"],
                "status": row["case_status"],
                "monitoringPriority": row["monitoring_priority"],
                "regionCode": row["primary_region_code"],
                "regionName": row["region_name"],
            }
            if row["case_id"] is not None
            else None
        ),
        "document": document,
        "contentSha256": row["content_sha256"],
    }


async def _approval_target(
    connection: AsyncConnection,
    target_type: str,
    target_id: UUID,
    target_version: int,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    if target_type == "RECOMMENDATION":
        target = await _recommendation_target(connection, target_id, lock=lock)
    elif target_type == "DOCUMENT_DRAFT":
        target = await _document_target(
            connection,
            target_id,
            target_version,
            lock=lock,
        )
    elif target_type == "INSPECTION_SCENARIO":
        from app.inspection_approval import inspection_approval_target

        target = await inspection_approval_target(
            connection,
            target_id,
            target_version,
            lock=lock,
        )
    else:
        raise WorkflowContractError(
            409,
            "APPROVAL_TARGET_UNSUPPORTED",
            "현재 화면에서 지원하지 않는 승인 대상입니다.",
        )
    if target is None:
        raise WorkflowContractError(
            409,
            "APPROVAL_TARGET_MISSING",
            "승인 대상 버전을 찾을 수 없습니다.",
        )
    return target


async def _detail(
    connection: AsyncConnection,
    approval_request_id: UUID,
) -> dict[str, Any] | None:
    request = (
        (
            await connection.execute(
                text(
                    """
                    SELECT request.*, user_record.display_name AS requested_by_name
                    FROM approval_request request
                    JOIN app_user user_record
                      ON user_record.user_id = request.requested_by
                    WHERE request.approval_request_id = :approval_request_id
                    """
                ),
                {"approval_request_id": approval_request_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if request is None:
        return None
    target = await _approval_target(
        connection,
        request["target_type"],
        request["target_id"],
        int(request["target_version"]),
    )
    decision = (
        (
            await connection.execute(
                text(
                    """
                    SELECT decision.*, user_record.display_name AS decided_by_name
                    FROM approval_decision decision
                    JOIN app_user user_record
                      ON user_record.user_id = decision.decided_by
                    WHERE decision.approval_request_id = :approval_request_id
                    """
                ),
                {"approval_request_id": approval_request_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if request["target_type"] == "RECOMMENDATION":
        work_item_count = len(target["recommendation"]["actions"])
        impact_summary = (
            "승인하면 제안 행동별 내부 수행과업과 체크리스트가 생성됩니다. "
            "외부 기관 연락·발송·현장 조치는 자동 실행되지 않습니다."
        )
    elif request["target_type"] == "INSPECTION_SCENARIO":
        work_item_count = len(target["inspection"]["teams"])
        impact_summary = (
            "승인하면 익명 점검반별 내부 수행과업이 생성되고 대상 목록이 잠깁니다. "
            "개인 담당자 배정이나 외부 요청은 자동 실행되지 않습니다."
        )
    else:
        work_item_count = 0
        impact_summary = (
            "승인하면 현재 문서 버전이 잠기고 FINAL HWPX·PDF 생성이 "
            "시작됩니다. 외부 전송은 실행되지 않습니다."
        )
    return {
        "approvalRequestId": str(request["approval_request_id"]),
        "caseId": (
            str(request["case_id"]) if request["case_id"] is not None else None
        ),
        "targetType": request["target_type"],
        "targetId": str(request["target_id"]),
        "targetVersion": int(request["target_version"]),
        "title": request["title"],
        "status": request["status"],
        "contentSha256": request["content_sha256"],
        "contentMatches": target["contentSha256"] == request["content_sha256"],
        "evidenceStatus": request["evidence_status"],
        "warning": request["warning"],
        "requestedBy": request["requested_by_name"],
        "requestedAt": _iso(request["requested_at"]),
        "decidedAt": _iso(request["decided_at"]),
        "version": int(request["version"]),
        "case": target["case"],
        "recommendation": target.get("recommendation"),
        "document": target.get("document"),
        "inspection": target.get("inspection"),
        "executionImpact": {
            "workItemCount": work_item_count,
            "externalEffect": False,
            "summary": impact_summary,
        },
        "decision": (
            {
                "approvalDecisionId": str(decision["approval_decision_id"]),
                "decision": decision["decision"],
                "decidedBy": decision["decided_by_name"],
                "reason": decision["reason"],
                "warningAcknowledged": bool(
                    decision["warning_acknowledged"]
                ),
                "contentSha256": decision["content_sha256"],
                "decidedAt": _iso(decision["decided_at"]),
            }
            if decision is not None
            else None
        ),
    }


async def approval_detail(
    engine: AsyncEngine,
    approval_request_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            return await _detail(connection, approval_request_id)

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def approval_list(
    engine: AsyncEngine,
    *,
    status: str | None,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    normalized_status = status.strip().upper() if status else None
    if normalized_status and normalized_status not in APPROVAL_STATUSES:
        raise WorkflowContractError(
            422,
            "INVALID_APPROVAL_STATUS",
            "승인 상태 필터가 올바르지 않습니다.",
        )

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            values = {
                "status": normalized_status,
                "limit": page_size,
                "offset": (page - 1) * page_size,
            }
            total = int(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM approval_request
                            WHERE (
                                CAST(:status AS varchar) IS NULL
                                OR status = CAST(:status AS varchar)
                            )
                            """
                        ),
                        values,
                    )
                ).scalar_one()
            )
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT request.*, case_record.case_number,
                                   case_record.title AS case_title
                            FROM approval_request request
                            LEFT JOIN case_record
                              ON case_record.case_id = request.case_id
                            WHERE (
                                CAST(:status AS varchar) IS NULL
                                OR request.status = CAST(:status AS varchar)
                            )
                            ORDER BY
                              CASE request.status
                                WHEN 'APPROVAL_PENDING' THEN 0
                                WHEN 'ON_HOLD' THEN 1
                                ELSE 2
                              END,
                              request.requested_at DESC,
                              request.approval_request_id
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        values,
                    )
                )
                .mappings()
                .all()
            )
        return {
            "items": [
                {
                    "approvalRequestId": str(row["approval_request_id"]),
                    "caseId": (
                        str(row["case_id"])
                        if row["case_id"] is not None
                        else None
                    ),
                    "caseNumber": row["case_number"],
                    "caseTitle": row["case_title"],
                    "targetType": row["target_type"],
                    "targetVersion": int(row["target_version"]),
                    "title": row["title"],
                    "status": row["status"],
                    "evidenceStatus": row["evidence_status"],
                    "warning": row["warning"],
                    "requestedAt": _iso(row["requested_at"]),
                    "decidedAt": _iso(row["decided_at"]),
                    "version": int(row["version"]),
                }
                for row in rows
            ],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def _audit(
    connection: AsyncConnection,
    *,
    profile: str,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str,
    action: str,
    approval_request_id: UUID,
    target_version: int,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    reason: dict[str, Any],
    input_sha256: str | None = None,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO audit_event (
                audit_event_id, profile, actor_type, actor_user_id,
                action, target_type, target_id, target_version,
                before_state, after_state, reason, correlation_id,
                idempotency_key, input_sha256, output_sha256
            )
            VALUES (
                :audit_event_id, :profile, 'USER', :user_id,
                :action, 'approval_request', :target_id, :target_version,
                CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                CAST(:reason AS jsonb), :correlation_id,
                :idempotency_key, :input_sha256, :output_sha256
            )
            """
        ),
        {
            "audit_event_id": uuid4(),
            "profile": profile,
            "user_id": user_id,
            "action": action,
            "target_id": str(approval_request_id),
            "target_version": target_version,
            "before_state": (
                json.dumps(before_state, ensure_ascii=False)
                if before_state is not None
                else None
            ),
            "after_state": json.dumps(after_state, ensure_ascii=False),
            "reason": json.dumps(reason, ensure_ascii=False),
            "correlation_id": request_id,
            "idempotency_key": idempotency_key,
            "input_sha256": input_sha256,
            "output_sha256": _hash(after_state),
        },
    )


async def request_recommendation_approval(
    engine: AsyncEngine,
    *,
    profile: str,
    recommendation_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> dict[str, Any]:
    key = _key(idempotency_key)
    audit_key = _audit_key("approval-request", profile, key)
    approval_request_id: UUID
    reused = False
    async with engine.begin() as connection:
        duplicate_id = (
            await connection.execute(
                text(
                    """
                    SELECT target_id
                    FROM audit_event
                    WHERE idempotency_key = :idempotency_key
                    """
                ),
                {"idempotency_key": audit_key},
            )
        ).scalar_one_or_none()
        if duplicate_id is not None:
            approval_request_id = UUID(str(duplicate_id))
            reused = True
        else:
            target = await _recommendation_target(
                connection, recommendation_id, lock=True
            )
            if target is None:
                raise WorkflowContractError(
                    404,
                    "RECOMMENDATION_NOT_FOUND",
                    "검토할 대응안을 찾을 수 없습니다.",
                )
            recommendation = target["recommendation"]
            if recommendation["status"] != "READY":
                raise WorkflowContractError(
                    409,
                    "RECOMMENDATION_NOT_READY",
                    "현재 상태의 대응안은 승인 요청할 수 없습니다.",
                )
            existing = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT approval_request_id, status
                            FROM approval_request
                            WHERE target_type = 'RECOMMENDATION'
                              AND target_id = :target_id
                              AND target_version = :target_version
                            ORDER BY requested_at DESC
                            FOR UPDATE
                            """
                        ),
                        {
                            "target_id": recommendation_id,
                            "target_version": recommendation["version"],
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None and existing["status"] in (
                "APPROVAL_PENDING",
                "APPROVED",
            ):
                approval_request_id = existing["approval_request_id"]
                reused = True
            else:
                approval_request_id = uuid4()
                warning = (
                    recommendation["warning"]
                    or recommendation["evidenceWarning"]
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO approval_request (
                            approval_request_id, case_id, target_type,
                            target_id, target_version, title, status,
                            content_sha256, evidence_status, warning,
                            requested_by
                        )
                        VALUES (
                            :approval_request_id, :case_id, 'RECOMMENDATION',
                            :target_id, :target_version, :title,
                            'APPROVAL_PENDING', :content_sha256,
                            :evidence_status, :warning, :requested_by
                        )
                        """
                    ),
                    {
                        "approval_request_id": approval_request_id,
                        "case_id": recommendation["caseId"],
                        "target_id": recommendation_id,
                        "target_version": recommendation["version"],
                        "title": (
                            f"{target['case']['caseNumber']} 대응안 "
                            f"v{recommendation['version']} 검토"
                        ),
                        "content_sha256": target["contentSha256"],
                        "evidence_status": recommendation["evidenceStatus"],
                        "warning": warning,
                        "requested_by": user_id,
                    },
                )
                await _audit(
                    connection,
                    profile=profile,
                    user_id=user_id,
                    request_id=request_id,
                    idempotency_key=audit_key,
                    action="APPROVAL_REQUEST_CREATED",
                    approval_request_id=approval_request_id,
                    target_version=1,
                    before_state=None,
                    after_state={
                        "status": "APPROVAL_PENDING",
                        "targetType": "RECOMMENDATION",
                        "targetId": str(recommendation_id),
                        "targetVersion": recommendation["version"],
                    },
                    reason={"source": "USER"},
                    input_sha256=target["contentSha256"],
                )
    result = await approval_detail(engine, approval_request_id, 2.0)
    if result is None:
        raise RuntimeError("Created approval request not found")
    return {**result, "reused": reused}


async def request_document_approval(
    engine: AsyncEngine,
    *,
    profile: str,
    document_draft_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> dict[str, Any]:
    key = _key(idempotency_key)
    audit_key = _audit_key("document-approval-request", profile, key)
    approval_request_id: UUID
    reused = False
    async with engine.begin() as connection:
        duplicate_id = (
            await connection.execute(
                text(
                    """
                    SELECT target_id
                    FROM audit_event
                    WHERE idempotency_key = :idempotency_key
                    """
                ),
                {"idempotency_key": audit_key},
            )
        ).scalar_one_or_none()
        if duplicate_id is not None:
            approval_request_id = UUID(str(duplicate_id))
            reused = True
        else:
            target = await _document_target(
                connection,
                document_draft_id,
                lock=True,
            )
            if target is None:
                raise WorkflowContractError(
                    404,
                    "DOCUMENT_NOT_FOUND",
                    "검토할 문서 초안을 찾을 수 없습니다.",
                )
            document = target["document"]
            if document["draftStatus"] not in ("DRAFT", "ON_HOLD"):
                raise WorkflowContractError(
                    409,
                    "DOCUMENT_NOT_REVIEWABLE",
                    "현재 상태의 문서는 승인 요청할 수 없습니다.",
                )
            existing = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT approval_request_id, status
                            FROM approval_request
                            WHERE target_type = 'DOCUMENT_DRAFT'
                              AND target_id = :target_id
                              AND target_version = :target_version
                            ORDER BY requested_at DESC
                            FOR UPDATE
                            """
                        ),
                        {
                            "target_id": document_draft_id,
                            "target_version": document["version"],
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None and existing["status"] in (
                "APPROVAL_PENDING",
                "APPROVED",
            ):
                approval_request_id = existing["approval_request_id"]
                reused = True
            else:
                approval_request_id = uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO approval_request (
                            approval_request_id, case_id, target_type,
                            target_id, target_version, title, status,
                            content_sha256, evidence_status, warning,
                            requested_by
                        )
                        VALUES (
                            :approval_request_id, :case_id, 'DOCUMENT_DRAFT',
                            :target_id, :target_version, :title,
                            'APPROVAL_PENDING', :content_sha256,
                            :evidence_status, :warning, :requested_by
                        )
                        """
                    ),
                    {
                        "approval_request_id": approval_request_id,
                        "case_id": document["caseId"],
                        "target_id": document_draft_id,
                        "target_version": document["version"],
                        "title": (
                            f"{document['title']} v{document['version']} 검토"
                        ),
                        "content_sha256": document["contentSha256"],
                        "evidence_status": document["evidenceStatus"],
                        "warning": document["warning"],
                        "requested_by": user_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE document_version
                        SET status = 'APPROVAL_PENDING'
                        WHERE document_version_id = :document_version_id
                        """
                    ),
                    {"document_version_id": document["documentVersionId"]},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE document_draft
                        SET status = 'APPROVAL_PENDING',
                            updated_at = CURRENT_TIMESTAMP,
                            version = version + 1
                        WHERE document_draft_id = :document_draft_id
                        """
                    ),
                    {"document_draft_id": document_draft_id},
                )
                await _audit(
                    connection,
                    profile=profile,
                    user_id=user_id,
                    request_id=request_id,
                    idempotency_key=audit_key,
                    action="DOCUMENT_APPROVAL_REQUEST_CREATED",
                    approval_request_id=approval_request_id,
                    target_version=1,
                    before_state={
                        "documentStatus": document["draftStatus"],
                        "documentVersion": document["version"],
                    },
                    after_state={
                        "status": "APPROVAL_PENDING",
                        "targetType": "DOCUMENT_DRAFT",
                        "targetId": str(document_draft_id),
                        "targetVersion": document["version"],
                    },
                    reason={"source": "USER"},
                    input_sha256=document["contentSha256"],
                )
    result = await approval_detail(engine, approval_request_id, 2.0)
    if result is None:
        raise RuntimeError("Created document approval request not found")
    return {**result, "reused": reused}


async def decide_approval(
    engine: AsyncEngine,
    *,
    profile: str,
    approval_request_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
    expected_version: int,
    decision: str,
    reason: str,
    warning_acknowledged: bool,
    discard_reason: str | None = None,
    discard_reason_detail: str | None = None,
) -> dict[str, Any]:
    key = _key(idempotency_key)
    normalized_decision = decision.strip().upper()
    normalized_reason = reason.strip()
    if normalized_decision not in DECISIONS:
        raise WorkflowContractError(
            422,
            "INVALID_APPROVAL_DECISION",
            "결정은 승인·보류·폐기 중 하나여야 합니다.",
        )
    if not normalized_reason or len(normalized_reason) > 1000:
        raise WorkflowContractError(
            422,
            "REASON_REQUIRED",
            "1~1000자의 결정 사유를 입력해 주세요.",
        )
    created_work_item_ids: list[str] = []
    generated_artifact_ids: list[str] = []
    async with engine.begin() as connection:
        duplicate = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT approval_request_id
                        FROM approval_decision
                        WHERE idempotency_key = :idempotency_key
                        """
                    ),
                    {"idempotency_key": key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if duplicate is not None:
            if duplicate["approval_request_id"] != approval_request_id:
                raise WorkflowContractError(
                    409,
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "다른 승인 요청에 사용된 Idempotency-Key입니다.",
                )
        else:
            request = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM approval_request
                            WHERE approval_request_id = :approval_request_id
                            FOR UPDATE
                            """
                        ),
                        {"approval_request_id": approval_request_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if request is None:
                raise WorkflowContractError(
                    404,
                    "APPROVAL_NOT_FOUND",
                    "승인 요청을 찾을 수 없습니다.",
                )
            if int(request["version"]) != expected_version:
                raise WorkflowContractError(
                    409,
                    "APPROVAL_VERSION_CONFLICT",
                    "다른 변경이 반영되었습니다. 최신 상태를 다시 확인해 주세요.",
                )
            if request["status"] != "APPROVAL_PENDING":
                raise WorkflowContractError(
                    409,
                    "APPROVAL_ALREADY_DECIDED",
                    "이미 결정된 승인 요청입니다.",
                )
            target = await _approval_target(
                connection,
                request["target_type"],
                request["target_id"],
                int(request["target_version"]),
                lock=True,
            )
            if (
                request["target_type"] == "RECOMMENDATION"
                and normalized_decision == "APPROVED"
            ):
                case_status = (
                    await connection.execute(
                        text(
                            """
                            SELECT status
                            FROM case_record
                            WHERE case_id = :case_id
                            FOR UPDATE
                            """
                        ),
                        {"case_id": UUID(target["case"]["caseId"])},
                    )
                ).scalar_one()
                if case_status in ("CLOSED", "MERGED"):
                    raise WorkflowContractError(
                        409,
                        "CASE_WORK_ITEM_LOCKED",
                        "종료되거나 병합된 Case의 대응안을 승인해 새 업무를 만들 수 없습니다.",
                    )
            if target["contentSha256"] != request["content_sha256"]:
                raise WorkflowContractError(
                    409,
                    "APPROVAL_CONTENT_CHANGED",
                    "승인 요청 이후 내용이 달라졌습니다. 새 버전을 검토해 주세요.",
                )
            if request["target_type"] == "DOCUMENT_DRAFT":
                document = target["document"]
                if (
                    document["currentVersion"] != int(request["target_version"])
                    or document["draftStatus"] != "APPROVAL_PENDING"
                    or document["versionStatus"] != "APPROVAL_PENDING"
                ):
                    raise WorkflowContractError(
                        409,
                        "APPROVAL_CONTENT_CHANGED",
                        "승인 요청 이후 문서 상태가 달라졌습니다. 새로 검토해 주세요.",
                    )
            if request["target_type"] == "INSPECTION_SCENARIO":
                inspection = target["inspection"]
                if (
                    inspection["status"] != "APPROVAL_PENDING"
                    or not inspection["confirmable"]
                ):
                    raise WorkflowContractError(
                        409,
                        "APPROVAL_CONTENT_CHANGED",
                        "승인 요청 이후 점검계획 상태가 달라졌습니다. 새로 검토해 주세요.",
                    )
            if (
                normalized_decision == "APPROVED"
                and request["evidence_status"] in ("INSUFFICIENT", "CONFLICT")
                and not warning_acknowledged
            ):
                raise WorkflowContractError(
                    422,
                    "WARNING_ACKNOWLEDGEMENT_REQUIRED",
                    "근거 부족·충돌 경고를 확인해야 승인할 수 있습니다.",
                )
            normalized_discard_reason = (
                discard_reason.strip().upper() if discard_reason else None
            )
            normalized_discard_detail = (
                discard_reason_detail.strip() if discard_reason_detail else None
            )
            if (
                request["target_type"] == "DOCUMENT_DRAFT"
                and normalized_decision == "DISCARDED"
            ):
                if normalized_discard_reason not in DOCUMENT_DISCARD_REASONS:
                    raise WorkflowContractError(
                        422,
                        "DOCUMENT_DISCARD_REASON_REQUIRED",
                        "문서 폐기 사유를 선택해 주세요.",
                    )
                if (
                    normalized_discard_reason == "OTHER"
                    and not normalized_discard_detail
                ):
                    raise WorkflowContractError(
                        422,
                        "DOCUMENT_DISCARD_DETAIL_REQUIRED",
                        "기타 폐기 사유를 입력해 주세요.",
                    )
                if (
                    normalized_discard_reason != "OTHER"
                    and normalized_discard_detail
                ):
                    raise WorkflowContractError(
                        422,
                        "DOCUMENT_DISCARD_DETAIL_NOT_ALLOWED",
                        "기타를 선택한 경우에만 추가 설명을 입력할 수 있습니다.",
                    )
                if (
                    normalized_discard_detail is not None
                    and len(normalized_discard_detail) > 500
                ):
                    raise WorkflowContractError(
                        422,
                        "DOCUMENT_DISCARD_DETAIL_TOO_LONG",
                        "기타 폐기 사유는 500자 이하로 입력해 주세요.",
                    )
            await connection.execute(
                text(
                    """
                    INSERT INTO approval_decision (
                        approval_decision_id, approval_request_id,
                        decision, decided_by, reason,
                        warning_acknowledged, content_sha256,
                        idempotency_key
                    )
                    VALUES (
                        :approval_decision_id, :approval_request_id,
                        :decision, :decided_by, :reason,
                        :warning_acknowledged, :content_sha256,
                        :idempotency_key
                    )
                    """
                ),
                {
                    "approval_decision_id": uuid4(),
                    "approval_request_id": approval_request_id,
                    "decision": normalized_decision,
                    "decided_by": user_id,
                    "reason": normalized_reason,
                    "warning_acknowledged": warning_acknowledged,
                    "content_sha256": request["content_sha256"],
                    "idempotency_key": key,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE approval_request
                    SET status = :decision,
                        decided_at = CURRENT_TIMESTAMP,
                        version = version + 1
                    WHERE approval_request_id = :approval_request_id
                    """
                ),
                {
                    "decision": normalized_decision,
                    "approval_request_id": approval_request_id,
                },
            )
            if request["target_type"] == "RECOMMENDATION":
                recommendation = target["recommendation"]
                if normalized_decision == "APPROVED":
                    case_priority = target["case"]["monitoringPriority"]
                    priority = {
                        "URGENT": "URGENT",
                        "ATTENTION": "HIGH",
                    }.get(case_priority, "NORMAL")
                    for action in recommendation["actions"]:
                        action_id = UUID(action["recommendationActionId"])
                        work_item_id = uuid4()
                        await connection.execute(
                            text(
                                """
                                INSERT INTO work_item (
                                    work_item_id, work_type, case_id,
                                    recommendation_action_id, status,
                                    priority, title, input_version,
                                    progress, idempotency_key
                                )
                                VALUES (
                                    :work_item_id, 'CASE_RESPONSE', :case_id,
                                    :action_id, 'QUEUED', :priority, :title,
                                    :input_version, 0, :idempotency_key
                                )
                                """
                            ),
                            {
                                "work_item_id": work_item_id,
                                "case_id": recommendation["caseId"],
                                "action_id": action_id,
                                "priority": priority,
                                "title": action["title"],
                                "input_version": (
                                    f"recommendation:"
                                    f"{recommendation['recommendationId']}"
                                    f":v{recommendation['version']}"
                                ),
                                "idempotency_key": (
                                    f"approval:{approval_request_id}:"
                                    f"action:{action_id}"
                                ),
                            },
                        )
                        for ordinal, label in enumerate(
                            action["checklist"], start=1
                        ):
                            await connection.execute(
                                text(
                                    """
                                    INSERT INTO work_item_checklist (
                                        checklist_item_id, work_item_id,
                                        ordinal, label
                                    )
                                    VALUES (
                                        :checklist_item_id, :work_item_id,
                                        :ordinal, :label
                                    )
                                    """
                                ),
                                {
                                    "checklist_item_id": uuid4(),
                                    "work_item_id": work_item_id,
                                    "ordinal": ordinal,
                                    "label": label,
                                },
                            )
                        await connection.execute(
                            text(
                                """
                                UPDATE recommendation_action
                                SET status = 'ACCEPTED'
                                WHERE recommendation_action_id = :action_id
                                """
                            ),
                            {"action_id": action_id},
                        )
                        created_work_item_ids.append(str(work_item_id))
                elif normalized_decision == "DISCARDED":
                    await connection.execute(
                        text(
                            """
                            UPDATE recommendation_action
                            SET status = 'DISCARDED'
                            WHERE recommendation_id = :recommendation_id
                            """
                        ),
                        {"recommendation_id": request["target_id"]},
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE recommendation
                            SET status = 'SUPERSEDED',
                                superseded_at = CURRENT_TIMESTAMP
                            WHERE recommendation_id = :recommendation_id
                            """
                        ),
                        {"recommendation_id": request["target_id"]},
                    )
            elif request["target_type"] == "DOCUMENT_DRAFT":
                document = target["document"]
                document_version_id = UUID(document["documentVersionId"])
                if normalized_decision == "APPROVED":
                    generated_artifact_ids = [
                        str(artifact_id)
                        for artifact_id in await _insert_artifacts(
                            connection,
                            document_version_id,
                            "FINAL",
                        )
                    ]
                await connection.execute(
                    text(
                        """
                        UPDATE document_version
                        SET status = CAST(:decision AS varchar),
                            warning_acknowledged = :warning_acknowledged,
                            approval_reason = :approval_reason,
                            approved_by = CASE
                              WHEN CAST(:decision AS varchar) = 'APPROVED'
                                THEN CAST(:user_id AS uuid)
                              ELSE CAST(NULL AS uuid)
                            END,
                            approved_at = CASE
                              WHEN CAST(:decision AS varchar) = 'APPROVED'
                                THEN CURRENT_TIMESTAMP
                              ELSE NULL
                            END
                        WHERE document_version_id = :document_version_id
                        """
                    ),
                    {
                        "decision": normalized_decision,
                        "warning_acknowledged": warning_acknowledged,
                        "approval_reason": normalized_reason,
                        "user_id": user_id,
                        "document_version_id": document_version_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE document_draft
                        SET status = CAST(:decision AS varchar),
                            updated_at = CURRENT_TIMESTAMP,
                            version = version + 1
                        WHERE document_draft_id = :document_draft_id
                        """
                    ),
                    {
                        "decision": normalized_decision,
                        "document_draft_id": request["target_id"],
                    },
                )
            else:
                from app.inspection_approval import apply_inspection_decision

                created_work_item_ids = await apply_inspection_decision(
                    connection,
                    scenario_id=request["target_id"],
                    decision=normalized_decision,
                    approval_request_id=approval_request_id,
                )
            await _audit(
                connection,
                profile=profile,
                user_id=user_id,
                request_id=request_id,
                idempotency_key=_audit_key("approval-decision", profile, key),
                action=f"APPROVAL_{normalized_decision}",
                approval_request_id=approval_request_id,
                target_version=expected_version + 1,
                before_state={
                    "status": "APPROVAL_PENDING",
                    "version": expected_version,
                },
                after_state={
                    "status": normalized_decision,
                    "version": expected_version + 1,
                    "createdWorkItemIds": created_work_item_ids,
                    "generatedArtifactIds": generated_artifact_ids,
                },
                reason={
                    "userReason": normalized_reason,
                    "warningAcknowledged": warning_acknowledged,
                    "discardReason": normalized_discard_reason,
                    "discardReasonDetail": normalized_discard_detail,
                },
                input_sha256=request["content_sha256"],
            )
    result = await approval_detail(engine, approval_request_id, 2.0)
    if result is None:
        raise RuntimeError("Decided approval request not found")
    if (
        not generated_artifact_ids
        and result["targetType"] == "DOCUMENT_DRAFT"
        and result["status"] == "APPROVED"
        and result["document"] is not None
    ):
        generated_artifact_ids = [
            artifact["documentArtifactId"]
            for artifact in result["document"]["artifacts"]
            if artifact["stage"] == "FINAL"
            and artifact["status"] == "QUEUED"
        ]
    return {
        **result,
        "createdWorkItemIds": created_work_item_ids,
        "generatedArtifactIds": generated_artifact_ids,
    }
