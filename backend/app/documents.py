from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings
from app.document_content import (
    VARIANT_FAMILIES,
    VARIANT_TEMPLATE_KEYS,
    ArtifactStage,
    DocumentPayload,
    DocumentVariant,
    build_initial_document_payload,
    canonical_payload_hash,
    hwpx_values,
    missing_administrative_fields,
    render_document_html,
)
from app.document_templates import (
    TEMPLATE_BY_KEY,
    TEMPLATE_VERSION,
    render_hwpx,
    sha256_file,
)
from app.workflow import WorkflowContractError

DOCUMENT_ASSET_ROOT = Path(__file__).parent / "assets" / "document_templates"
DOCUMENT_STATUSES = frozenset(
    {"DRAFT", "APPROVAL_PENDING", "APPROVED", "ON_HOLD", "DISCARDED"}
)
EDITABLE_STATUSES = frozenset({"DRAFT", "ON_HOLD"})
ARTIFACT_FORMATS = frozenset({"HWPX", "PDF"})
ARTIFACT_STAGES = frozenset({"REVIEW", "FINAL"})
ARTIFACT_RETRY_AFTER = timedelta(minutes=10)
SAFE_FILE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _idempotency_key(scope: str, profile: str, value: str | None) -> str:
    normalized = value.strip() if value else ""
    if not 8 <= len(normalized) <= 160:
        raise WorkflowContractError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "변경 요청에는 8~160자의 Idempotency-Key가 필요합니다.",
        )
    digest = hashlib.sha256(f"{profile}:{scope}:{normalized}".encode()).hexdigest()
    return f"document:{scope}:{digest}"


def _artifact_key(
    document_version_id: UUID,
    format_name: str,
    stage: str,
) -> str:
    return f"document-artifact:{document_version_id}:{format_name}:{stage}"


def _template_metadata(variant: DocumentVariant) -> tuple[str, str]:
    template_key = VARIANT_TEMPLATE_KEYS[variant]
    definition = TEMPLATE_BY_KEY[template_key]
    template_path = DOCUMENT_ASSET_ROOT / definition.file_name
    digest = sha256_file(template_path)
    return template_key, digest


def _serialize_artifact(row: Any) -> dict[str, Any]:
    return {
        "documentArtifactId": str(row["document_artifact_id"]),
        "format": row["format"],
        "stage": row["stage"],
        "status": row["status"],
        "attemptCount": int(row["attempt_count"]),
        "fileName": row["file_name"],
        "mimeType": row["mime_type"],
        "sizeBytes": int(row["size_bytes"]) if row["size_bytes"] else None,
        "sha256": row["sha256"],
        "validation": row["validation"],
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
        "queuedAt": _iso(row["queued_at"]),
        "startedAt": _iso(row["started_at"]),
        "finishedAt": _iso(row["finished_at"]),
        "downloadUrl": (
            f"/api/v1/document-artifacts/{row['document_artifact_id']}/download"
            if row["status"] == "SUCCEEDED"
            else None
        ),
    }


async def _current_document_detail(
    connection: AsyncConnection,
    document_draft_id: UUID,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    row = (
        (
            await connection.execute(
                text(
                    f"""
                    SELECT draft.*, version.document_version_id,
                           version.parent_version_id,
                           version.status AS version_status,
                           version.structured_payload,
                           version.evidence_status,
                           version.warning,
                           version.content_sha256,
                           version.template_key,
                           version.template_version,
                           version.template_sha256,
                           version.warning_acknowledged,
                           version.approval_reason,
                           version.created_at AS version_created_at,
                           version.approved_at,
                           case_record.case_number
                    FROM document_draft draft
                    JOIN document_version version
                      ON version.document_draft_id = draft.document_draft_id
                     AND version.version = draft.current_version
                    LEFT JOIN case_record
                      ON case_record.case_id = draft.case_id
                    WHERE draft.document_draft_id = :document_draft_id
                    {"FOR UPDATE OF draft, version" if lock else ""}
                    """
                ),
                {"document_draft_id": document_draft_id},
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
                    ORDER BY
                      CASE stage WHEN 'FINAL' THEN 0 ELSE 1 END,
                      CASE format WHEN 'PDF' THEN 0 ELSE 1 END,
                      queued_at DESC
                    """
                ),
                {"document_version_id": row["document_version_id"]},
            )
        )
        .mappings()
        .all()
    )
    version_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT version, status, evidence_status, warning,
                           content_sha256, created_at, approved_at,
                           (
                             SELECT count(*)
                             FROM document_artifact artifact
                             WHERE artifact.document_version_id =
                                   version_record.document_version_id
                               AND artifact.status = 'SUCCEEDED'
                           ) AS succeeded_artifact_count
                    FROM document_version version_record
                    WHERE document_draft_id = :document_draft_id
                    ORDER BY version DESC
                    """
                ),
                {"document_draft_id": document_draft_id},
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
                    ORDER BY delivered_at DESC,
                             document_manual_delivery_id
                    """
                ),
                {"document_version_id": row["document_version_id"]},
            )
        )
        .mappings()
        .all()
    )
    payload = DocumentPayload.model_validate(row["structured_payload"])
    return {
        "documentDraftId": str(row["document_draft_id"]),
        "documentVersionId": str(row["document_version_id"]),
        "caseId": str(row["case_id"]) if row["case_id"] else None,
        "caseNumber": row["case_number"],
        "family": row["family"],
        "variant": row["variant"],
        "title": row["title"],
        "status": row["status"],
        "versionStatus": row["version_status"],
        "currentVersion": int(row["current_version"]),
        "lockVersion": int(row["version"]),
        "payload": payload.model_dump(mode="json", by_alias=True),
        "evidenceStatus": row["evidence_status"],
        "warning": row["warning"],
        "missingAdministrativeFields": missing_administrative_fields(payload),
        "contentSha256": row["content_sha256"],
        "template": {
            "key": row["template_key"],
            "version": row["template_version"],
            "sha256": row["template_sha256"],
        },
        "warningAcknowledged": bool(row["warning_acknowledged"]),
        "approvalReason": row["approval_reason"],
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "versionCreatedAt": _iso(row["version_created_at"]),
        "approvedAt": _iso(row["approved_at"]),
        "artifacts": [_serialize_artifact(item) for item in artifact_rows],
        "manualDeliveries": [
            {
                "documentManualDeliveryId": str(
                    item["document_manual_delivery_id"]
                ),
                "recipient": item["recipient"],
                "deliveredAt": _iso(item["delivered_at"]),
                "method": item["method"],
                "memo": item["memo"],
                "recordedBy": item["recorded_by_name"],
                "recordedAt": _iso(item["recorded_at"]),
                "externalDeliveryVerified": False,
            }
            for item in delivery_rows
        ],
        "versions": [
            {
                "version": int(item["version"]),
                "status": item["status"],
                "evidenceStatus": item["evidence_status"],
                "warning": item["warning"],
                "contentSha256": item["content_sha256"],
                "succeededArtifactCount": int(
                    item["succeeded_artifact_count"]
                ),
                "createdAt": _iso(item["created_at"]),
                "approvedAt": _iso(item["approved_at"]),
            }
            for item in version_rows
        ],
    }


async def _case_and_recommendation(
    connection: AsyncConnection,
    case_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    case_row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT case_record.*, region.full_name AS region_name
                    FROM case_record
                    LEFT JOIN admin_region region
                      ON region.region_code = case_record.primary_region_code
                    WHERE case_record.case_id = :case_id
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if case_row is None:
        return None
    case = {
        "caseId": str(case_row["case_id"]),
        "caseNumber": case_row["case_number"],
        "title": case_row["title"],
        "caseType": case_row["case_type"],
        "status": case_row["status"],
        "sourceStatus": case_row["source_status"],
        "monitoringPriority": case_row["monitoring_priority"],
        "regionCode": case_row["primary_region_code"],
        "regionName": case_row["region_name"],
        "normalizedAddress": case_row["normalized_address"],
        "openedAt": _iso(case_row["opened_at"]),
        "updatedAt": _iso(case_row["updated_at"]),
    }
    recommendation_row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT recommendation.*, bundle.status AS evidence_status,
                           bundle.warning AS evidence_warning
                    FROM recommendation
                    JOIN evidence_bundle bundle
                      ON bundle.evidence_bundle_id =
                         recommendation.evidence_bundle_id
                    WHERE recommendation.case_id = :case_id
                      AND recommendation.status IN ('DRAFT', 'READY')
                    ORDER BY recommendation.version DESC
                    LIMIT 1
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if recommendation_row is None:
        return case, None
    action_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT *
                    FROM recommendation_action
                    WHERE recommendation_id = :recommendation_id
                    ORDER BY ordinal
                    """
                ),
                {"recommendation_id": recommendation_row["recommendation_id"]},
            )
        )
        .mappings()
        .all()
    )
    action_ids = [row["recommendation_action_id"] for row in action_rows]
    citations_by_action: dict[UUID, list[dict[str, Any]]] = {}
    if action_ids:
        citation_rows = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT citation.*, document.title AS document_title
                        FROM evidence_citation citation
                        JOIN evidence_item item
                          ON item.evidence_item_id = citation.evidence_item_id
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
        for citation in citation_rows:
            citations_by_action.setdefault(
                citation["recommendation_action_id"], []
            ).append(
                {
                    "citationId": str(citation["citation_id"]),
                    "documentTitle": citation["document_title"],
                    "locator": citation["locator"],
                    "quote": citation["quote_text"],
                    "supportType": citation["support_type"],
                }
            )
    recommendation = {
        "recommendationId": str(recommendation_row["recommendation_id"]),
        "version": int(recommendation_row["version"]),
        "situationSummary": recommendation_row["situation_summary"],
        "requiredChecks": list(recommendation_row["required_checks"] or []),
        "uncertainties": list(recommendation_row["uncertainties"] or []),
        "conflicts": list(recommendation_row["conflicts"] or []),
        "warning": (
            recommendation_row["warning"]
            or recommendation_row["evidence_warning"]
        ),
        "evidenceStatus": recommendation_row["evidence_status"],
        "actions": [
            {
                "recommendationActionId": str(row["recommendation_action_id"]),
                "ordinal": int(row["ordinal"]),
                "title": row["title"],
                "description": row["description"],
                "evidenceStatus": row["evidence_status"],
                "warning": row["warning"],
                "citations": citations_by_action.get(
                    row["recommendation_action_id"], []
                ),
            }
            for row in action_rows
        ],
    }
    return case, recommendation


async def _insert_artifacts(
    connection: AsyncConnection,
    document_version_id: UUID,
    stage: ArtifactStage,
) -> list[UUID]:
    result: list[UUID] = []
    for format_name in ("HWPX", "PDF"):
        artifact_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO document_artifact (
                    document_artifact_id, document_version_id,
                    format, stage, status, idempotency_key
                )
                VALUES (
                    :artifact_id, :document_version_id,
                    :format, :stage, 'QUEUED', :idempotency_key
                )
                """
            ),
            {
                "artifact_id": artifact_id,
                "document_version_id": document_version_id,
                "format": format_name,
                "stage": stage,
                "idempotency_key": _artifact_key(
                    document_version_id, format_name, stage
                ),
            },
        )
        result.append(artifact_id)
    return result


async def _existing_idempotent_document(
    connection: AsyncConnection,
    audit_key: str,
) -> dict[str, Any] | None:
    target_id = (
        await connection.execute(
            text(
                """
                SELECT target_id
                FROM audit_event
                WHERE idempotency_key = :idempotency_key
                  AND target_type = 'DOCUMENT_DRAFT'
                """
            ),
            {"idempotency_key": audit_key},
        )
    ).scalar_one_or_none()
    if target_id is None:
        return None
    return await _current_document_detail(connection, UUID(str(target_id)))


async def create_document_draft(
    engine: AsyncEngine,
    *,
    profile: str,
    case_id: UUID,
    variant: DocumentVariant,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    audit_key = _idempotency_key("create", profile, idempotency_key)
    async with engine.begin() as connection:
        existing = await _existing_idempotent_document(connection, audit_key)
        if existing is not None:
            return existing, True
        source = await _case_and_recommendation(connection, case_id)
        if source is None:
            raise WorkflowContractError(
                404,
                "CASE_NOT_FOUND",
                "Case를 찾을 수 없습니다.",
            )
        case, recommendation = source
        payload = build_initial_document_payload(
            variant=variant,
            case=case,
            recommendation=recommendation,
            now=datetime.now(UTC),
        )
        document_draft_id = uuid4()
        document_version_id = uuid4()
        family = VARIANT_FAMILIES[variant]
        template_key, template_sha256 = _template_metadata(variant)
        content_sha256 = canonical_payload_hash(payload)
        warning = payload.review.warning or None
        await connection.execute(
            text(
                """
                INSERT INTO document_draft (
                    document_draft_id, case_id, family, variant, title,
                    status, current_version, created_by
                )
                VALUES (
                    :document_draft_id, :case_id, :family, :variant, :title,
                    'DRAFT', 1, :user_id
                )
                """
            ),
            {
                "document_draft_id": document_draft_id,
                "case_id": case_id,
                "family": family,
                "variant": variant,
                "title": payload.document.title,
                "user_id": user_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO document_version (
                    document_version_id, document_draft_id, version, status,
                    structured_payload, evidence_status, warning,
                    content_sha256, template_key, template_version,
                    template_sha256, created_by
                )
                VALUES (
                    :document_version_id, :document_draft_id, 1, 'DRAFT',
                    CAST(:structured_payload AS jsonb), :evidence_status, :warning,
                    :content_sha256, :template_key, :template_version,
                    :template_sha256, :user_id
                )
                """
            ),
            {
                "document_version_id": document_version_id,
                "document_draft_id": document_draft_id,
                "structured_payload": json.dumps(
                    payload.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                ),
                "evidence_status": payload.evidence.status,
                "warning": warning,
                "content_sha256": content_sha256,
                "template_key": template_key,
                "template_version": TEMPLATE_VERSION,
                "template_sha256": template_sha256,
                "user_id": user_id,
            },
        )
        await _insert_artifacts(connection, document_version_id, "REVIEW")
        await connection.execute(
            text(
                """
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, actor_user_id,
                    action, target_type, target_id, target_version,
                    after_state, reason, correlation_id, idempotency_key,
                    output_sha256
                )
                VALUES (
                    :audit_event_id, :profile, 'USER', :user_id,
                    'DOCUMENT_DRAFT_CREATED', 'DOCUMENT_DRAFT',
                    :target_id, 1, CAST(:after_state AS jsonb),
                    '{}'::jsonb, :request_id, :idempotency_key,
                    :output_sha256
                )
                """
            ),
            {
                "audit_event_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(document_draft_id),
                "after_state": json.dumps(
                    {
                        "status": "DRAFT",
                        "variant": variant,
                        "version": 1,
                        "evidenceStatus": payload.evidence.status,
                    }
                ),
                "request_id": request_id,
                "idempotency_key": audit_key,
                "output_sha256": content_sha256,
            },
        )
        detail = await _current_document_detail(connection, document_draft_id)
        if detail is None:
            raise RuntimeError("DOCUMENT_INSERT_NOT_VISIBLE")
        return detail, False


async def update_document_draft(
    engine: AsyncEngine,
    *,
    profile: str,
    document_draft_id: UUID,
    expected_version: int,
    payload: DocumentPayload,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    audit_key = _idempotency_key("update", profile, idempotency_key)
    async with engine.begin() as connection:
        existing = await _existing_idempotent_document(connection, audit_key)
        if existing is not None:
            return existing, True
        current = await _current_document_detail(
            connection,
            document_draft_id,
            lock=True,
        )
        if current is None:
            raise WorkflowContractError(
                404,
                "DOCUMENT_NOT_FOUND",
                "문서 초안을 찾을 수 없습니다.",
            )
        if current["status"] not in EDITABLE_STATUSES:
            raise WorkflowContractError(
                409,
                "DOCUMENT_NOT_EDITABLE",
                "현재 상태에서는 문서를 수정할 수 없습니다.",
            )
        if current["lockVersion"] != expected_version:
            raise WorkflowContractError(
                409,
                "DOCUMENT_VERSION_CONFLICT",
                "다른 변경이 먼저 저장되었습니다. 최신 문서를 다시 확인해 주세요.",
            )
        if payload.case_id != current["caseId"] or payload.variant != current["variant"]:
            raise WorkflowContractError(
                422,
                "DOCUMENT_IDENTITY_IMMUTABLE",
                "문서의 사건과 종류는 변경할 수 없습니다.",
            )
        previous_version_id = UUID(current["documentVersionId"])
        next_version = int(current["currentVersion"]) + 1
        next_version_id = uuid4()
        template_key, template_sha256 = _template_metadata(payload.variant)
        content_sha256 = canonical_payload_hash(payload)
        await connection.execute(
            text(
                """
                UPDATE document_version
                SET status = 'SUPERSEDED', superseded_at = CURRENT_TIMESTAMP
                WHERE document_version_id = :document_version_id
                """
            ),
            {"document_version_id": previous_version_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO document_version (
                    document_version_id, document_draft_id, version,
                    parent_version_id, status, structured_payload,
                    evidence_status, warning, content_sha256,
                    template_key, template_version, template_sha256, created_by
                )
                VALUES (
                    :document_version_id, :document_draft_id, :version,
                    :parent_version_id, 'DRAFT', CAST(:structured_payload AS jsonb),
                    :evidence_status, :warning, :content_sha256,
                    :template_key, :template_version, :template_sha256, :user_id
                )
                """
            ),
            {
                "document_version_id": next_version_id,
                "document_draft_id": document_draft_id,
                "version": next_version,
                "parent_version_id": previous_version_id,
                "structured_payload": json.dumps(
                    payload.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                ),
                "evidence_status": payload.evidence.status,
                "warning": payload.review.warning or None,
                "content_sha256": content_sha256,
                "template_key": template_key,
                "template_version": TEMPLATE_VERSION,
                "template_sha256": template_sha256,
                "user_id": user_id,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE document_draft
                SET title = :title,
                    status = 'DRAFT',
                    current_version = :current_version,
                    updated_at = CURRENT_TIMESTAMP,
                    version = version + 1
                WHERE document_draft_id = :document_draft_id
                """
            ),
            {
                "title": payload.document.title,
                "current_version": next_version,
                "document_draft_id": document_draft_id,
            },
        )
        await _insert_artifacts(connection, next_version_id, "REVIEW")
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
                    'DOCUMENT_DRAFT_UPDATED', 'DOCUMENT_DRAFT',
                    :target_id, :target_version,
                    CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                    '{}'::jsonb, :request_id, :idempotency_key,
                    :input_sha256, :output_sha256
                )
                """
            ),
            {
                "audit_event_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(document_draft_id),
                "target_version": next_version,
                "before_state": json.dumps(
                    {
                        "version": current["currentVersion"],
                        "status": current["status"],
                    }
                ),
                "after_state": json.dumps(
                    {
                        "version": next_version,
                        "status": "DRAFT",
                    }
                ),
                "request_id": request_id,
                "idempotency_key": audit_key,
                "input_sha256": current["contentSha256"],
                "output_sha256": content_sha256,
            },
        )
        detail = await _current_document_detail(connection, document_draft_id)
        if detail is None:
            raise RuntimeError("DOCUMENT_UPDATE_NOT_VISIBLE")
        return detail, False


async def clone_document_draft(
    engine: AsyncEngine,
    *,
    profile: str,
    document_draft_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    audit_key = _idempotency_key("clone", profile, idempotency_key)
    async with engine.begin() as connection:
        existing = await _existing_idempotent_document(connection, audit_key)
        if existing is not None:
            return existing, True
        current = await _current_document_detail(
            connection,
            document_draft_id,
            lock=True,
        )
        if current is None:
            raise WorkflowContractError(
                404,
                "DOCUMENT_NOT_FOUND",
                "복제할 문서를 찾을 수 없습니다.",
            )
        if current["status"] not in ("APPROVED", "DISCARDED"):
            raise WorkflowContractError(
                409,
                "DOCUMENT_CLONE_NOT_ALLOWED",
                "승인본 또는 폐기본만 새 초안으로 복제할 수 있습니다.",
            )
        next_version = int(current["currentVersion"]) + 1
        next_version_id = uuid4()
        payload = DocumentPayload.model_validate(current["payload"])
        await connection.execute(
            text(
                """
                INSERT INTO document_version (
                    document_version_id, document_draft_id, version,
                    parent_version_id, status, structured_payload,
                    evidence_status, warning, content_sha256,
                    template_key, template_version, template_sha256,
                    created_by
                )
                VALUES (
                    :document_version_id, :document_draft_id, :version,
                    :parent_version_id, 'DRAFT',
                    CAST(:structured_payload AS jsonb), :evidence_status,
                    :warning, :content_sha256, :template_key,
                    :template_version, :template_sha256, :created_by
                )
                """
            ),
            {
                "document_version_id": next_version_id,
                "document_draft_id": document_draft_id,
                "version": next_version,
                "parent_version_id": UUID(current["documentVersionId"]),
                "structured_payload": json.dumps(
                    payload.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                ),
                "evidence_status": current["evidenceStatus"],
                "warning": current["warning"],
                "content_sha256": current["contentSha256"],
                "template_key": current["template"]["key"],
                "template_version": current["template"]["version"],
                "template_sha256": current["template"]["sha256"],
                "created_by": user_id,
            },
        )
        if current["status"] == "APPROVED":
            await connection.execute(
                text(
                    """
                    UPDATE document_version
                    SET status = 'SUPERSEDED',
                        superseded_at = CURRENT_TIMESTAMP
                    WHERE document_version_id = :document_version_id
                    """
                ),
                {"document_version_id": UUID(current["documentVersionId"])},
            )
        await connection.execute(
            text(
                """
                UPDATE document_draft
                SET status = 'DRAFT',
                    current_version = :current_version,
                    updated_at = CURRENT_TIMESTAMP,
                    version = version + 1
                WHERE document_draft_id = :document_draft_id
                """
            ),
            {
                "current_version": next_version,
                "document_draft_id": document_draft_id,
            },
        )
        await _insert_artifacts(connection, next_version_id, "REVIEW")
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
                    'DOCUMENT_DRAFT_CLONED', 'DOCUMENT_DRAFT',
                    :target_id, :target_version,
                    CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                    CAST(:reason AS jsonb), :request_id, :idempotency_key,
                    :input_sha256, :output_sha256
                )
                """
            ),
            {
                "audit_event_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(document_draft_id),
                "target_version": next_version,
                "before_state": json.dumps(
                    {
                        "version": current["currentVersion"],
                        "status": current["status"],
                    }
                ),
                "after_state": json.dumps(
                    {"version": next_version, "status": "DRAFT"}
                ),
                "reason": json.dumps(
                    {
                        "sourceStatus": current["status"],
                        "sourceVersion": current["currentVersion"],
                    }
                ),
                "request_id": request_id,
                "idempotency_key": audit_key,
                "input_sha256": current["contentSha256"],
                "output_sha256": current["contentSha256"],
            },
        )
        detail = await _current_document_detail(connection, document_draft_id)
        if detail is None:
            raise RuntimeError("DOCUMENT_CLONE_NOT_VISIBLE")
        return detail, False


async def retry_document_artifact(
    engine: AsyncEngine,
    *,
    profile: str,
    artifact_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    audit_key = _idempotency_key("artifact-retry", profile, idempotency_key)
    async with engine.begin() as connection:
        duplicate_id = (
            await connection.execute(
                text(
                    """
                    SELECT target_id
                    FROM audit_event
                    WHERE idempotency_key = :idempotency_key
                      AND target_type = 'DOCUMENT_ARTIFACT'
                    """
                ),
                {"idempotency_key": audit_key},
            )
        ).scalar_one_or_none()
        reused = duplicate_id is not None
        target_id = UUID(str(duplicate_id)) if duplicate_id else artifact_id
        row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT artifact.*, version.document_draft_id,
                               version.version AS document_version
                        FROM document_artifact artifact
                        JOIN document_version version
                          ON version.document_version_id =
                             artifact.document_version_id
                        WHERE artifact.document_artifact_id = :artifact_id
                        FOR UPDATE OF artifact
                        """
                    ),
                    {"artifact_id": target_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise WorkflowContractError(
                404,
                "DOCUMENT_ARTIFACT_NOT_FOUND",
                "재시도할 문서 산출물을 찾을 수 없습니다.",
            )
        if reused:
            return {
                "documentDraftId": str(row["document_draft_id"]),
                "artifact": _serialize_artifact(row),
            }, True
        if row["status"] != "FAILED":
            raise WorkflowContractError(
                409,
                "DOCUMENT_ARTIFACT_NOT_RETRYABLE",
                "실패한 문서 산출물만 재시도할 수 있습니다.",
            )
        await connection.execute(
            text(
                """
                UPDATE document_artifact
                SET status = 'QUEUED',
                    storage_path = NULL,
                    file_name = NULL,
                    mime_type = NULL,
                    size_bytes = NULL,
                    sha256 = NULL,
                    validation = '{}'::jsonb,
                    error_code = NULL,
                    error_message = NULL,
                    queued_at = CURRENT_TIMESTAMP,
                    started_at = NULL,
                    finished_at = NULL
                WHERE document_artifact_id = :artifact_id
                """
            ),
            {"artifact_id": artifact_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, actor_user_id,
                    action, target_type, target_id, target_version,
                    before_state, after_state, reason, correlation_id,
                    idempotency_key
                )
                VALUES (
                    :audit_event_id, :profile, 'USER', :user_id,
                    'DOCUMENT_ARTIFACT_RETRIED', 'DOCUMENT_ARTIFACT',
                    :target_id, :target_version,
                    CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                    '{}'::jsonb, :request_id, :idempotency_key
                )
                """
            ),
            {
                "audit_event_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(artifact_id),
                "target_version": int(row["document_version"]),
                "before_state": json.dumps(
                    {
                        "status": "FAILED",
                        "attemptCount": int(row["attempt_count"]),
                        "errorCode": row["error_code"],
                    }
                ),
                "after_state": json.dumps(
                    {
                        "status": "QUEUED",
                        "attemptCount": int(row["attempt_count"]),
                    }
                ),
                "request_id": request_id,
                "idempotency_key": audit_key,
            },
        )
        updated = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT artifact.*, version.document_draft_id
                        FROM document_artifact artifact
                        JOIN document_version version
                          ON version.document_version_id =
                             artifact.document_version_id
                        WHERE artifact.document_artifact_id = :artifact_id
                        """
                    ),
                    {"artifact_id": artifact_id},
                )
            )
            .mappings()
            .one()
        )
        return {
            "documentDraftId": str(updated["document_draft_id"]),
            "artifact": _serialize_artifact(updated),
        }, False


async def record_manual_delivery(
    engine: AsyncEngine,
    *,
    profile: str,
    document_version_id: UUID,
    recipient: str,
    delivered_at: datetime,
    method: str,
    memo: str | None,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    normalized_recipient = recipient.strip()
    normalized_method = method.strip().upper()
    normalized_memo = memo.strip() if memo and memo.strip() else None
    if not normalized_recipient or len(normalized_recipient) > 500:
        raise WorkflowContractError(
            422,
            "MANUAL_DELIVERY_RECIPIENT_INVALID",
            "수신처는 1~500자로 입력해 주세요.",
        )
    if normalized_method not in {
        "EMAIL",
        "MESSENGER",
        "E_DOCUMENT",
        "IN_PERSON",
        "OTHER",
    }:
        raise WorkflowContractError(
            422,
            "MANUAL_DELIVERY_METHOD_INVALID",
            "지원하는 전달방법을 선택해 주세요.",
        )
    if delivered_at.utcoffset() is None:
        raise WorkflowContractError(
            422,
            "MANUAL_DELIVERY_TIMEZONE_REQUIRED",
            "발송시각에는 시간대를 포함해 주세요.",
        )
    if normalized_memo is not None and len(normalized_memo) > 2000:
        raise WorkflowContractError(
            422,
            "MANUAL_DELIVERY_MEMO_TOO_LONG",
            "메모는 2000자 이하로 입력해 주세요.",
        )
    delivery_key = _idempotency_key("manual-delivery", profile, idempotency_key)
    async with engine.begin() as connection:
        duplicate = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT delivery.*, user_record.display_name
                        FROM document_manual_delivery delivery
                        JOIN app_user user_record
                          ON user_record.user_id = delivery.recorded_by
                        WHERE delivery.idempotency_key = :idempotency_key
                        """
                    ),
                    {"idempotency_key": delivery_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if duplicate is not None:
            if duplicate["document_version_id"] != document_version_id:
                raise WorkflowContractError(
                    409,
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "다른 문서 버전에 사용된 Idempotency-Key입니다.",
                )
            return {
                "documentManualDeliveryId": str(
                    duplicate["document_manual_delivery_id"]
                ),
                "documentVersionId": str(duplicate["document_version_id"]),
                "recipient": duplicate["recipient"],
                "deliveredAt": _iso(duplicate["delivered_at"]),
                "method": duplicate["method"],
                "memo": duplicate["memo"],
                "recordedBy": duplicate["display_name"],
                "recordedAt": _iso(duplicate["recorded_at"]),
                "externalDeliveryVerified": False,
            }, True
        version = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT version.*, draft.document_draft_id
                        FROM document_version version
                        JOIN document_draft draft
                          ON draft.document_draft_id =
                             version.document_draft_id
                        WHERE version.document_version_id =
                              :document_version_id
                        FOR UPDATE OF version
                        """
                    ),
                    {"document_version_id": document_version_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if version is None:
            raise WorkflowContractError(
                404,
                "DOCUMENT_VERSION_NOT_FOUND",
                "발송 기록을 남길 문서 버전을 찾을 수 없습니다.",
            )
        if version["approved_at"] is None:
            raise WorkflowContractError(
                409,
                "DOCUMENT_VERSION_NOT_APPROVED",
                "승인된 문서 버전에만 수동 발송 기록을 남길 수 있습니다.",
            )
        succeeded_final_count = int(
            (
                await connection.execute(
                    text(
                        """
                        SELECT count(DISTINCT format)
                        FROM document_artifact
                        WHERE document_version_id = :document_version_id
                          AND stage = 'FINAL'
                          AND status = 'SUCCEEDED'
                        """
                    ),
                    {"document_version_id": document_version_id},
                )
            ).scalar_one()
        )
        if succeeded_final_count != 2:
            raise WorkflowContractError(
                409,
                "DOCUMENT_FINAL_ARTIFACTS_INCOMPLETE",
                "최종 HWPX와 PDF 생성이 끝난 뒤 발송 기록을 남길 수 있습니다.",
            )
        delivery_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO document_manual_delivery (
                    document_manual_delivery_id, document_version_id,
                    recipient, delivered_at, method, memo, recorded_by,
                    idempotency_key
                )
                VALUES (
                    :delivery_id, :document_version_id, :recipient,
                    :delivered_at, :method, :memo, :recorded_by,
                    :idempotency_key
                )
                """
            ),
            {
                "delivery_id": delivery_id,
                "document_version_id": document_version_id,
                "recipient": normalized_recipient,
                "delivered_at": delivered_at,
                "method": normalized_method,
                "memo": normalized_memo,
                "recorded_by": user_id,
                "idempotency_key": delivery_key,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, actor_user_id,
                    action, target_type, target_id, target_version,
                    after_state, reason, correlation_id, idempotency_key,
                    input_sha256
                )
                VALUES (
                    :audit_event_id, :profile, 'USER', :user_id,
                    'DOCUMENT_MANUAL_DELIVERY_RECORDED', 'DOCUMENT_VERSION',
                    :target_id, :target_version, CAST(:after_state AS jsonb),
                    CAST(:reason AS jsonb), :request_id, :audit_key,
                    :input_sha256
                )
                """
            ),
            {
                "audit_event_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(document_version_id),
                "target_version": int(version["version"]),
                "after_state": json.dumps(
                    {
                        "documentManualDeliveryId": str(delivery_id),
                        "manualRecordOnly": True,
                    }
                ),
                "reason": json.dumps(
                    {
                        "recipient": normalized_recipient,
                        "deliveredAt": delivered_at.isoformat(),
                        "method": normalized_method,
                    },
                    ensure_ascii=False,
                ),
                "request_id": request_id,
                "audit_key": _idempotency_key(
                    "manual-delivery-audit",
                    profile,
                    idempotency_key,
                ),
                "input_sha256": version["content_sha256"],
            },
        )
        recorded = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT delivery.recorded_at,
                               user_record.display_name
                        FROM document_manual_delivery delivery
                        JOIN app_user user_record
                          ON user_record.user_id = delivery.recorded_by
                        WHERE delivery.document_manual_delivery_id =
                              :delivery_id
                        """
                    ),
                    {"delivery_id": delivery_id},
                )
            )
            .mappings()
            .one()
        )
        return {
            "documentManualDeliveryId": str(delivery_id),
            "documentVersionId": str(document_version_id),
            "recipient": normalized_recipient,
            "deliveredAt": delivered_at.isoformat(),
            "method": normalized_method,
            "memo": normalized_memo,
            "recordedBy": recorded["display_name"],
            "recordedAt": _iso(recorded["recorded_at"]),
            "externalDeliveryVerified": False,
        }, False


async def document_detail(
    engine: AsyncEngine,
    document_draft_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            return await _current_document_detail(connection, document_draft_id)

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def document_library(
    engine: AsyncEngine,
    *,
    status: str | None,
    family: str | None,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if status is not None and status not in DOCUMENT_STATUSES:
        raise WorkflowContractError(
            400,
            "DOCUMENT_STATUS_INVALID",
            "지원하지 않는 문서 상태입니다.",
        )
    if family is not None and family not in {
        "SITUATION_REPORT",
        "OFFICIAL_NOTICE",
        "RESPONSE_PLAN",
    }:
        raise WorkflowContractError(
            400,
            "DOCUMENT_FAMILY_INVALID",
            "지원하지 않는 문서 계열입니다.",
        )

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT draft.*, case_record.case_number,
                                   version.evidence_status,
                                   version.warning,
                                   (
                                     SELECT count(*)
                                     FROM document_artifact artifact
                                     WHERE artifact.document_version_id =
                                           version.document_version_id
                                       AND artifact.status = 'SUCCEEDED'
                                   ) AS succeeded_artifact_count,
                                   count(*) OVER () AS total_count
                            FROM document_draft draft
                            JOIN document_version version
                              ON version.document_draft_id =
                                 draft.document_draft_id
                             AND version.version = draft.current_version
                            LEFT JOIN case_record
                              ON case_record.case_id = draft.case_id
                            WHERE (
                              CAST(:status AS varchar) IS NULL
                              OR draft.status = CAST(:status AS varchar)
                            )
                              AND (
                                CAST(:family AS varchar) IS NULL
                                OR draft.family = CAST(:family AS varchar)
                              )
                            ORDER BY draft.updated_at DESC,
                                     draft.document_draft_id
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        {
                            "status": status,
                            "family": family,
                            "limit": page_size,
                            "offset": (page - 1) * page_size,
                        },
                    )
                )
                .mappings()
                .all()
            )
            total = int(rows[0]["total_count"]) if rows else 0
            return {
                "items": [
                    {
                        "documentDraftId": str(row["document_draft_id"]),
                        "caseId": str(row["case_id"]) if row["case_id"] else None,
                        "caseNumber": row["case_number"],
                        "family": row["family"],
                        "variant": row["variant"],
                        "title": row["title"],
                        "status": row["status"],
                        "currentVersion": int(row["current_version"]),
                        "evidenceStatus": row["evidence_status"],
                        "warning": row["warning"],
                        "succeededArtifactCount": int(
                            row["succeeded_artifact_count"]
                        ),
                        "createdAt": _iso(row["created_at"]),
                        "updatedAt": _iso(row["updated_at"]),
                    }
                    for row in rows
                ],
                "pagination": {
                    "page": page,
                    "pageSize": page_size,
                    "total": total,
                    "totalPages": (total + page_size - 1) // page_size,
                },
            }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


def _artifact_relative_path(
    *,
    document_draft_id: UUID,
    version: int,
    stage: str,
    format_name: str,
    case_number: str | None,
) -> PurePosixPath:
    suffix = format_name.lower()
    safe_case = SAFE_FILE_COMPONENT.sub(
        "-",
        case_number or str(document_draft_id),
    ).strip("-._")
    if not safe_case:
        safe_case = str(document_draft_id)
    file_name = f"{safe_case}_v{version}_{stage.lower()}.{suffix}"
    return PurePosixPath(
        str(document_draft_id),
        f"v{version}",
        stage.lower(),
        file_name,
    )


def _resolve_storage_path(root: Path, relative_path: PurePosixPath) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise RuntimeError("DOCUMENT_STORAGE_PATH_INVALID")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*relative_path.parts)).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise RuntimeError("DOCUMENT_STORAGE_PATH_ESCAPE")
    return resolved


async def _claim_artifact(
    connection: AsyncConnection,
    artifact_id: UUID,
) -> dict[str, Any] | None:
    row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT artifact.*, version.structured_payload,
                           version.status AS version_status,
                           version.version AS document_version,
                           version.template_key,
                           version.template_version,
                           version.template_sha256,
                           draft.document_draft_id,
                           draft.title,
                           draft.variant,
                           case_record.case_number
                    FROM document_artifact artifact
                    JOIN document_version version
                      ON version.document_version_id =
                         artifact.document_version_id
                    JOIN document_draft draft
                      ON draft.document_draft_id = version.document_draft_id
                    LEFT JOIN case_record
                      ON case_record.case_id = draft.case_id
                    WHERE artifact.document_artifact_id = :artifact_id
                    FOR UPDATE OF artifact
                    """
                ),
                {"artifact_id": artifact_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["status"] == "SUCCEEDED":
        result = dict(row)
        result["_claimed"] = False
        return result
    if (
        row["status"] == "RUNNING"
        and row["started_at"] is not None
        and row["started_at"] > datetime.now(UTC) - ARTIFACT_RETRY_AFTER
    ):
        result = dict(row)
        result["_claimed"] = False
        return result
    await connection.execute(
        text(
            """
            UPDATE document_artifact
            SET status = 'RUNNING',
                attempt_count = attempt_count + 1,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL,
                error_code = NULL,
                error_message = NULL
            WHERE document_artifact_id = :artifact_id
            """
        ),
        {"artifact_id": artifact_id},
    )
    result = dict(row)
    result["status"] = "RUNNING"
    result["attempt_count"] = int(row["attempt_count"]) + 1
    result["_claimed"] = True
    return result


async def _render_pdf(
    settings: Settings,
    payload: DocumentPayload,
    stage: ArtifactStage,
    output_path: Path,
) -> dict[str, Any]:
    renderer_path = Path(settings.document_pdf_renderer)
    if not await asyncio.to_thread(renderer_path.is_file):
        raise RuntimeError("PDF_RENDERER_UNAVAILABLE")
    html_path = output_path.with_name(f".{output_path.name}.html")
    await asyncio.to_thread(
        html_path.write_text,
        render_document_html(payload, stage),
        encoding="utf-8",
    )
    try:
        process = await asyncio.create_subprocess_exec(
            "node",
            str(renderer_path),
            str(html_path),
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.document_render_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("PDF_RENDER_TIMEOUT") from None
        if process.returncode != 0:
            error_text = stderr.decode(errors="replace")[-1000:]
            raise RuntimeError(f"PDF_RENDER_FAILED:{error_text}")
        try:
            metadata = json.loads(stdout.decode() or "{}")
        except json.JSONDecodeError as error:
            raise RuntimeError("PDF_RENDER_METADATA_INVALID") from error
    finally:
        await asyncio.to_thread(html_path.unlink, missing_ok=True)
    data = await asyncio.to_thread(output_path.read_bytes)
    if len(data) < 1000 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise RuntimeError("PDF_OUTPUT_INVALID")
    return {
        "renderer": "playwright-chromium",
        "bytes": len(data),
        **metadata,
    }


async def generate_document_artifact(
    settings: Settings,
    artifact_id: UUID,
) -> dict[str, Any]:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    artifact: dict[str, Any] | None = None
    output_path: Path | None = None
    temporary_path: Path | None = None
    try:
        async with engine.begin() as connection:
            artifact = await _claim_artifact(connection, artifact_id)
        if artifact is None:
            raise RuntimeError("DOCUMENT_ARTIFACT_NOT_FOUND")
        if artifact["status"] == "SUCCEEDED":
            return {
                "documentArtifactId": str(artifact_id),
                "status": "SUCCEEDED",
                "reused": True,
            }
        if not artifact.get("_claimed"):
            return {
                "documentArtifactId": str(artifact_id),
                "status": "RUNNING",
                "reused": True,
            }
        format_name = str(artifact["format"])
        stage = str(artifact["stage"])
        if format_name not in ARTIFACT_FORMATS or stage not in ARTIFACT_STAGES:
            raise RuntimeError("DOCUMENT_ARTIFACT_CONTRACT_INVALID")
        if stage == "FINAL" and artifact["version_status"] != "APPROVED":
            raise RuntimeError("DOCUMENT_FINAL_REQUIRES_APPROVAL")
        payload = DocumentPayload.model_validate(artifact["structured_payload"])
        definition = TEMPLATE_BY_KEY[str(artifact["template_key"])]
        template_path = DOCUMENT_ASSET_ROOT / definition.file_name
        if (
            str(artifact["template_version"]) != TEMPLATE_VERSION
            or sha256_file(template_path) != str(artifact["template_sha256"])
        ):
            raise RuntimeError("DOCUMENT_TEMPLATE_VERSION_MISMATCH")
        relative_path = _artifact_relative_path(
            document_draft_id=artifact["document_draft_id"],
            version=int(artifact["document_version"]),
            stage=stage,
            format_name=format_name,
            case_number=artifact["case_number"],
        )
        storage_root = Path(settings.document_storage_root)
        output_path = _resolve_storage_path(storage_root, relative_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(output_path.suffix + ".part")
        temporary_path.unlink(missing_ok=True)
        typed_stage = cast(ArtifactStage, stage)
        if format_name == "HWPX":
            validation = render_hwpx(
                template_path,
                temporary_path,
                definition,
                hwpx_values(payload, typed_stage),
            )
            validation_data = asdict(validation)
            mime_type = "application/hwp+zip"
        else:
            validation_data = await _render_pdf(
                settings,
                payload,
                typed_stage,
                temporary_path,
            )
            mime_type = "application/pdf"
        temporary_path.replace(output_path)
        size_bytes = output_path.stat().st_size
        digest = sha256_file(output_path)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE document_artifact
                    SET status = 'SUCCEEDED',
                        storage_path = :storage_path,
                        file_name = :file_name,
                        mime_type = :mime_type,
                        size_bytes = :size_bytes,
                        sha256 = :sha256,
                        validation = CAST(:validation AS jsonb),
                        finished_at = CURRENT_TIMESTAMP
                    WHERE document_artifact_id = :artifact_id
                    """
                ),
                {
                    "storage_path": str(relative_path),
                    "file_name": output_path.name,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "sha256": digest,
                    "validation": json.dumps(validation_data),
                    "artifact_id": artifact_id,
                },
            )
        return {
            "documentArtifactId": str(artifact_id),
            "format": format_name,
            "stage": stage,
            "status": "SUCCEEDED",
            "sizeBytes": size_bytes,
            "sha256": digest,
            "reused": False,
        }
    except Exception as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if artifact is not None and artifact.get("status") != "SUCCEEDED":
            error_code = str(error).split(":", 1)[0][:80] or type(error).__name__
            error_message = str(error)[:1000] or type(error).__name__
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE document_artifact
                        SET status = 'FAILED',
                            error_code = :error_code,
                            error_message = :error_message,
                            finished_at = CURRENT_TIMESTAMP
                        WHERE document_artifact_id = :artifact_id
                        """
                    ),
                    {
                        "error_code": error_code,
                        "error_message": error_message,
                        "artifact_id": artifact_id,
                    },
                )
        raise
    finally:
        await engine.dispose()


async def document_artifact_download(
    engine: AsyncEngine,
    *,
    artifact_id: UUID,
    storage_root: Path,
    timeout_seconds: float,
) -> tuple[Path, str, str] | None:
    async def query() -> tuple[Path, str, str] | None:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT storage_path, file_name, mime_type
                            FROM document_artifact
                            WHERE document_artifact_id = :artifact_id
                              AND status = 'SUCCEEDED'
                            """
                        ),
                        {"artifact_id": artifact_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        relative_path = PurePosixPath(str(row["storage_path"]))
        resolved = _resolve_storage_path(storage_root, relative_path)
        if not resolved.is_file():
            raise WorkflowContractError(
                410,
                "DOCUMENT_ARTIFACT_FILE_MISSING",
                "문서 파일이 저장소에 존재하지 않습니다.",
            )
        return resolved, str(row["file_name"]), str(row["mime_type"])

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))
