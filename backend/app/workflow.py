# ruff: noqa: E501
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

EVIDENCE_STATUSES: Final = frozenset(("SUFFICIENT", "INSUFFICIENT", "CONFLICT"))
WORK_PRIORITIES: Final = frozenset(("NORMAL", "HIGH", "URGENT"))
CHECKLIST_STATUSES: Final = frozenset(("PENDING", "DONE", "SKIPPED"))
CLOSE_REASONS: Final = frozenset(("RESOLVED", "FALSE_ALARM", "DUPLICATE", "OTHER"))
WORK_TRANSITIONS: Final = {
    "QUEUED": frozenset(("RUNNING", "ON_HOLD", "DISCARDED")),
    "RUNNING": frozenset(("WAITING_APPROVAL", "FAILED", "ON_HOLD")),
    "WAITING_APPROVAL": frozenset(("COMPLETED", "ON_HOLD", "DISCARDED")),
    "ON_HOLD": frozenset(("RUNNING", "WAITING_APPROVAL", "DISCARDED")),
    "FAILED": frozenset(("QUEUED", "DISCARDED")),
    "COMPLETED": frozenset(),
    "DISCARDED": frozenset(),
}


@dataclass
class WorkflowContractError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _audit_key(idempotency_key: str) -> str:
    return f"workflow:{hashlib.sha256(idempotency_key.encode()).hexdigest()}"


def _validate_idempotency_key(value: str | None) -> str:
    normalized = value.strip() if value else ""
    if not normalized or len(normalized) > 160:
        raise WorkflowContractError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "변경 요청에는 160자 이하의 Idempotency-Key가 필요합니다.",
        )
    return normalized


def _work_item(row: Any, checklist: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "workItemId": str(row["work_item_id"]),
        "caseId": str(row["case_id"]) if row["case_id"] is not None else None,
        "recommendationActionId": (
            str(row["recommendation_action_id"])
            if row["recommendation_action_id"] is not None
            else None
        ),
        "workType": row["work_type"],
        "status": row["status"],
        "priority": row["priority"],
        "title": row["title"],
        "dueAt": _iso(row["due_at"]),
        "progress": int(row["progress"]),
        "errorClass": row["error_class"],
        "retryCount": int(row["retry_count"]),
        "version": int(row["version"]),
        "createdAt": _iso(row["created_at"]),
        "startedAt": _iso(row["started_at"]),
        "completedAt": _iso(row["completed_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "checklist": checklist,
    }


def _checklist_item(row: Any) -> dict[str, Any]:
    return {
        "checklistItemId": str(row["checklist_item_id"]),
        "ordinal": int(row["ordinal"]),
        "label": row["label"],
        "status": row["status"],
        "note": row["note"],
        "completedAt": _iso(row["completed_at"]),
        "updatedAt": _iso(row["updated_at"]),
    }


async def _case_exists(connection: AsyncConnection, case_id: UUID) -> bool:
    result = await connection.execute(
        text("SELECT 1 FROM case_record WHERE case_id = :case_id"),
        {"case_id": case_id},
    )
    return result.scalar_one_or_none() is not None


async def case_evidence(
    engine: AsyncEngine,
    case_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            case_row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT c.case_id, c.case_number, c.title, c.case_type, c.status,
                                   c.primary_region_code, region.full_name AS region_name,
                                   c.updated_at
                            FROM case_record c
                            LEFT JOIN admin_region region
                              ON region.region_code = c.primary_region_code
                            WHERE c.case_id = :case_id
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
            bundle = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT bundle.*, index.status AS index_status,
                                   index.document_count AS indexed_document_count,
                                   index.chunk_count AS indexed_chunk_count
                            FROM evidence_bundle bundle
                            LEFT JOIN rag_index_version index
                              ON index.index_version_id = bundle.index_version_id
                            WHERE bundle.case_id = :case_id AND bundle.is_current
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if bundle is None:
                return {
                    "case": {
                        "caseId": str(case_row["case_id"]),
                        "caseNumber": case_row["case_number"],
                        "title": case_row["title"],
                        "caseType": case_row["case_type"],
                        "status": case_row["status"],
                        "regionName": case_row["region_name"],
                        "updatedAt": _iso(case_row["updated_at"]),
                    },
                    "retrievalState": "NOT_RUN",
                    "evidenceStatus": "INSUFFICIENT",
                    "warning": "아직 이 Case의 근거 검색이 수행되지 않았습니다. 대응 초안은 만들 수 있지만 추가 확인이 필요합니다.",
                    "bundle": None,
                    "officialEvidence": [],
                    "similarIncidents": [],
                    "otherRegionReferences": [],
                    "recommendation": None,
                }

            items = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT item.*, chunk.page_or_section, chunk.heading_path,
                                   document.document_id, document.title AS document_title,
                                   document.document_family, document.issuing_agency,
                                   document.document_number, document.published_at,
                                   document.revision, document.authority_level,
                                   document.privacy_status
                            FROM evidence_item item
                            JOIN rag_chunk chunk ON chunk.chunk_id = item.chunk_id
                            JOIN rag_document document
                              ON document.document_id = chunk.document_id
                            WHERE item.evidence_bundle_id = :bundle_id
                            ORDER BY
                              CASE item.evidence_group
                                  WHEN 'OFFICIAL' THEN 0
                                  WHEN 'PAST_INCIDENT' THEN 1
                                  ELSE 2
                              END,
                              item.rank
                            """
                        ),
                        {"bundle_id": bundle["evidence_bundle_id"]},
                    )
                )
                .mappings()
                .all()
            )
            recommendation = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM recommendation
                            WHERE case_id = :case_id
                              AND status IN ('DRAFT', 'READY')
                            ORDER BY version DESC
                            LIMIT 1
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            actions: Any = []
            citations_by_action: dict[UUID, list[dict[str, Any]]] = {}
            if recommendation is not None:
                actions = (
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT action.*,
                                       coalesce(work.work_item_id::text, NULL) AS work_item_id,
                                       work.status AS work_item_status
                                FROM recommendation_action action
                                LEFT JOIN work_item work
                                  ON work.recommendation_action_id = action.recommendation_action_id
                                WHERE action.recommendation_id = :recommendation_id
                                ORDER BY action.ordinal
                                """
                            ),
                            {"recommendation_id": recommendation["recommendation_id"]},
                        )
                    )
                    .mappings()
                    .all()
                )
                citation_rows = (
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT citation.*, document.title AS document_title,
                                       document.issuing_agency, document.document_number,
                                       document.published_at
                                FROM evidence_citation citation
                                JOIN evidence_item item
                                  ON item.evidence_item_id = citation.evidence_item_id
                                JOIN rag_chunk chunk ON chunk.chunk_id = item.chunk_id
                                JOIN rag_document document
                                  ON document.document_id = chunk.document_id
                                WHERE citation.recommendation_action_id =
                                      ANY(CAST(:action_ids AS uuid[]))
                                ORDER BY citation.recommendation_action_id, citation.citation_id
                                """
                            ),
                            {
                                "action_ids": [
                                    action["recommendation_action_id"] for action in actions
                                ]
                            },
                        )
                    )
                    .mappings()
                    .all()
                ) if actions else []
                for citation in citation_rows:
                    citations_by_action.setdefault(
                        citation["recommendation_action_id"], []
                    ).append(
                        {
                            "citationId": str(citation["citation_id"]),
                            "evidenceItemId": str(citation["evidence_item_id"]),
                            "supportType": citation["support_type"],
                            "quote": citation["quote_text"],
                            "locator": citation["locator"],
                            "documentTitle": citation["document_title"],
                            "issuingAgency": citation["issuing_agency"],
                            "documentNumber": citation["document_number"],
                            "publishedAt": (
                                citation["published_at"].isoformat()
                                if citation["published_at"] is not None
                                else None
                            ),
                        }
                    )

        serialized_items = [
            {
                "evidenceItemId": str(item["evidence_item_id"]),
                "documentId": str(item["document_id"]),
                "documentTitle": item["document_title"],
                "documentFamily": item["document_family"],
                "issuingAgency": item["issuing_agency"],
                "documentNumber": item["document_number"],
                "publishedAt": (
                    item["published_at"].isoformat()
                    if item["published_at"] is not None
                    else None
                ),
                "revision": item["revision"],
                "authorityLevel": int(item["authority_level"]),
                "privacyStatus": item["privacy_status"],
                "evidenceGroup": item["evidence_group"],
                "rank": int(item["rank"]),
                "fusedScore": float(item["fused_score"]),
                "currentStatus": item["current_status"],
                "selectionReason": item["selection_reason"],
                "excerpt": item["excerpt"],
                "locator": item["locator"],
                "pageOrSection": item["page_or_section"],
                "headingPath": list(item["heading_path"] or []),
            }
            for item in items
        ]
        grouped = {
            group: [item for item in serialized_items if item["evidenceGroup"] == group]
            for group in ("OFFICIAL", "PAST_INCIDENT", "OTHER_REGION")
        }
        return {
            "case": {
                "caseId": str(case_row["case_id"]),
                "caseNumber": case_row["case_number"],
                "title": case_row["title"],
                "caseType": case_row["case_type"],
                "status": case_row["status"],
                "regionName": case_row["region_name"],
                "updatedAt": _iso(case_row["updated_at"]),
            },
            "retrievalState": "COMPLETED",
            "evidenceStatus": bundle["status"],
            "warning": bundle["warning"],
            "bundle": {
                "evidenceBundleId": str(bundle["evidence_bundle_id"]),
                "version": int(bundle["version"]),
                "indexVersionId": (
                    str(bundle["index_version_id"])
                    if bundle["index_version_id"] is not None
                    else None
                ),
                "indexStatus": bundle["index_status"],
                "indexedDocumentCount": int(bundle["indexed_document_count"] or 0),
                "indexedChunkCount": int(bundle["indexed_chunk_count"] or 0),
                "candidateCount": int(bundle["candidate_count"]),
                "selectedCount": int(bundle["selected_count"]),
                "directCitationCount": int(bundle["direct_citation_count"]),
                "retrievalVersion": bundle["retrieval_version"],
                "createdAt": _iso(bundle["created_at"]),
            },
            "officialEvidence": grouped["OFFICIAL"],
            "similarIncidents": grouped["PAST_INCIDENT"],
            "otherRegionReferences": grouped["OTHER_REGION"],
            "recommendation": (
                {
                    "recommendationId": str(recommendation["recommendation_id"]),
                    "version": int(recommendation["version"]),
                    "status": recommendation["status"],
                    "generationMode": recommendation["generation_mode"],
                    "situationSummary": recommendation["situation_summary"],
                    "requiredChecks": recommendation["required_checks"],
                    "uncertainties": recommendation["uncertainties"],
                    "conflicts": recommendation["conflicts"],
                    "warning": recommendation["warning"],
                    "generationVersion": recommendation["generation_version"],
                    "createdAt": _iso(recommendation["created_at"]),
                    "actions": [
                        {
                            "recommendationActionId": str(
                                action["recommendation_action_id"]
                            ),
                            "ordinal": int(action["ordinal"]),
                            "title": action["title"],
                            "description": action["description"],
                            "dueGuidance": action["due_guidance"],
                            "evidenceStatus": action["evidence_status"],
                            "warning": action["warning"],
                            "status": action["status"],
                            "workItemId": action["work_item_id"],
                            "workItemStatus": action["work_item_status"],
                            "citations": citations_by_action.get(
                                action["recommendation_action_id"], []
                            ),
                        }
                        for action in actions
                    ],
                }
                if recommendation is not None
                else None
            ),
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def case_work_items(
    engine: AsyncEngine,
    case_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            if not await _case_exists(connection, case_id):
                return None
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM work_item
                            WHERE case_id = :case_id
                            ORDER BY
                              CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,
                              created_at,
                              work_item_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
            checklist_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT checklist.*
                            FROM work_item_checklist checklist
                            JOIN work_item work
                              ON work.work_item_id = checklist.work_item_id
                            WHERE work.case_id = :case_id
                            ORDER BY checklist.work_item_id, checklist.ordinal
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
        checklists: dict[UUID, list[dict[str, Any]]] = {}
        for item in checklist_rows:
            checklists.setdefault(item["work_item_id"], []).append(_checklist_item(item))
        items = [_work_item(row, checklists.get(row["work_item_id"], [])) for row in rows]
        return {
            "summary": {
                "total": len(items),
                "open": sum(
                    item["status"]
                    in ("QUEUED", "RUNNING", "WAITING_APPROVAL", "ON_HOLD", "FAILED")
                    for item in items
                ),
                "waitingApproval": sum(
                    item["status"] == "WAITING_APPROVAL" for item in items
                ),
                "completed": sum(item["status"] == "COMPLETED" for item in items),
            },
            "items": items,
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.0))


async def work_item_detail(
    engine: AsyncEngine,
    work_item_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM work_item WHERE work_item_id = :work_item_id"),
                        {"work_item_id": work_item_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            checklist = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM work_item_checklist
                            WHERE work_item_id = :work_item_id
                            ORDER BY ordinal
                            """
                        ),
                        {"work_item_id": work_item_id},
                    )
                )
                .mappings()
                .all()
            )
        return _work_item(row, [_checklist_item(item) for item in checklist])

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.0))


async def create_case_work_item(
    engine: AsyncEngine,
    *,
    profile: str,
    case_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
    title: str,
    work_type: str,
    priority: str,
    due_at: datetime | None,
    recommendation_action_id: UUID | None,
    checklist_labels: list[str],
) -> dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    if priority not in WORK_PRIORITIES:
        raise WorkflowContractError(422, "INVALID_WORK_PRIORITY", "업무 우선순위가 올바르지 않습니다.")
    normalized_title = title.strip()
    normalized_type = work_type.strip().upper()
    if not normalized_title or not normalized_type:
        raise WorkflowContractError(422, "INVALID_WORK_ITEM", "업무 제목과 유형이 필요합니다.")
    normalized_labels = [label.strip() for label in checklist_labels if label.strip()]
    if len(normalized_labels) != len(checklist_labels) or len(normalized_labels) > 30:
        raise WorkflowContractError(
            422, "INVALID_CHECKLIST", "체크리스트는 빈 항목 없이 최대 30개까지 입력할 수 있습니다."
        )

    async with engine.begin() as connection:
        existing = (
            (
                await connection.execute(
                    text("SELECT work_item_id FROM work_item WHERE idempotency_key = :key"),
                    {"key": key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            existing_item = await work_item_detail(engine, existing["work_item_id"], 2.0)
            if existing_item is None:
                raise RuntimeError("Idempotent work item disappeared")
            return existing_item
        if recommendation_action_id is not None:
            action = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT action.status
                            FROM recommendation_action action
                            JOIN recommendation recommendation
                              ON recommendation.recommendation_id = action.recommendation_id
                            WHERE action.recommendation_action_id = :action_id
                              AND recommendation.case_id = :case_id
                              AND recommendation.status IN ('DRAFT', 'READY')
                            FOR UPDATE
                            """
                        ),
                        {"action_id": recommendation_action_id, "case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if action is None:
                raise WorkflowContractError(
                    409,
                    "RECOMMENDATION_ACTION_UNAVAILABLE",
                    "현재 Case의 사용 가능한 제안 행동이 아닙니다.",
                )
            if action["status"] == "DISCARDED":
                raise WorkflowContractError(
                    409,
                    "RECOMMENDATION_ACTION_DISCARDED",
                    "폐기한 제안 행동에서는 업무를 만들 수 없습니다.",
                )
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
                {"case_id": case_id},
            )
        ).scalar_one_or_none()
        if case_status is None:
            raise WorkflowContractError(404, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.")
        if case_status in ("CLOSED", "MERGED"):
            raise WorkflowContractError(
                409,
                "CASE_WORK_ITEM_LOCKED",
                "종료되거나 병합된 Case에는 새 업무를 만들 수 없습니다.",
            )
        work_item_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO work_item (
                    work_item_id, work_type, case_id, recommendation_action_id,
                    status, priority, title, due_at, progress, idempotency_key
                )
                VALUES (
                    :work_item_id, :work_type, :case_id, :action_id,
                    'QUEUED', :priority, :title, :due_at, 0, :idempotency_key
                )
                """
            ),
            {
                "work_item_id": work_item_id,
                "work_type": normalized_type[:64],
                "case_id": case_id,
                "action_id": recommendation_action_id,
                "priority": priority,
                "title": normalized_title,
                "due_at": due_at,
                "idempotency_key": key,
            },
        )
        for ordinal, label in enumerate(normalized_labels, start=1):
            await connection.execute(
                text(
                    """
                    INSERT INTO work_item_checklist (
                        checklist_item_id, work_item_id, ordinal, label
                    )
                    VALUES (:item_id, :work_item_id, :ordinal, :label)
                    """
                ),
                {
                    "item_id": uuid4(),
                    "work_item_id": work_item_id,
                    "ordinal": ordinal,
                    "label": label,
                },
            )
        if recommendation_action_id is not None:
            await connection.execute(
                text(
                    """
                    UPDATE recommendation_action
                    SET status = 'ACCEPTED'
                    WHERE recommendation_action_id = :action_id
                    """
                ),
                {"action_id": recommendation_action_id},
            )
        await _insert_audit(
            connection,
            profile=profile,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=_audit_key(key),
            action="WORK_ITEM_CREATED",
            target_id=work_item_id,
            target_version=1,
            before_state=None,
            after_state={"status": "QUEUED", "priority": priority},
            reason={"source": "USER"},
        )
    result = await work_item_detail(engine, work_item_id, 2.0)
    if result is None:
        raise RuntimeError("Created work item not found")
    return result


async def transition_work_item(
    engine: AsyncEngine,
    *,
    profile: str,
    work_item_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
    expected_version: int,
    target_status: str,
    reason: str,
) -> dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise WorkflowContractError(422, "REASON_REQUIRED", "상태 변경 사유를 입력해 주세요.")
    if target_status not in WORK_TRANSITIONS:
        raise WorkflowContractError(422, "INVALID_WORK_STATUS", "업무 상태가 올바르지 않습니다.")
    audit_key = _audit_key(key)
    async with engine.begin() as connection:
        duplicate = (
            await connection.execute(
                text("SELECT 1 FROM audit_event WHERE idempotency_key = :key"),
                {"key": audit_key},
            )
        ).scalar_one_or_none()
        row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT *
                        FROM work_item
                        WHERE work_item_id = :work_item_id
                        FOR UPDATE
                        """
                    ),
                    {"work_item_id": work_item_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise WorkflowContractError(404, "WORK_ITEM_NOT_FOUND", "업무를 찾을 수 없습니다.")
        if duplicate is not None:
            result = await work_item_detail(engine, work_item_id, 2.0)
            if result is None:
                raise RuntimeError("Idempotent work item disappeared")
            return result
        if int(row["version"]) != expected_version:
            raise WorkflowContractError(
                409,
                "WORK_ITEM_VERSION_CONFLICT",
                "다른 변경이 먼저 반영되었습니다. 최신 상태를 다시 불러와 주세요.",
            )
        current_status = str(row["status"])
        if target_status not in WORK_TRANSITIONS[current_status]:
            raise WorkflowContractError(
                409,
                "INVALID_WORK_TRANSITION",
                f"{current_status} 상태에서는 {target_status}(으)로 변경할 수 없습니다.",
            )
        progress = {
            "QUEUED": 0,
            "RUNNING": max(int(row["progress"]), 1),
            "WAITING_APPROVAL": max(int(row["progress"]), 90),
            "COMPLETED": 100,
            "ON_HOLD": int(row["progress"]),
            "DISCARDED": int(row["progress"]),
            "FAILED": int(row["progress"]),
        }[target_status]
        await connection.execute(
            text(
                """
                UPDATE work_item
                SET status = CAST(:target_status AS varchar),
                    progress = :progress,
                    started_at = CASE
                        WHEN CAST(:target_status AS varchar) = 'RUNNING'
                         AND started_at IS NULL
                        THEN CURRENT_TIMESTAMP ELSE started_at END,
                    completed_at = CASE
                        WHEN CAST(:target_status AS varchar) = 'COMPLETED'
                        THEN CURRENT_TIMESTAMP ELSE NULL END,
                    error_class = CASE
                        WHEN CAST(:target_status AS varchar) = 'FAILED'
                        THEN 'USER_RECORDED_FAILURE'
                        WHEN CAST(:target_status AS varchar) IN ('QUEUED', 'RUNNING')
                        THEN NULL
                        ELSE error_class END,
                    retry_count = CASE
                        WHEN CAST(:target_status AS varchar) = 'QUEUED'
                         AND status = 'FAILED'
                        THEN retry_count + 1 ELSE retry_count END,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE work_item_id = :work_item_id
                """
            ),
            {
                "work_item_id": work_item_id,
                "target_status": target_status,
                "progress": progress,
            },
        )
        await _insert_audit(
            connection,
            profile=profile,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=audit_key,
            action="WORK_ITEM_STATUS_CHANGED",
            target_id=work_item_id,
            target_version=expected_version + 1,
            before_state={"status": current_status, "version": expected_version},
            after_state={"status": target_status, "version": expected_version + 1},
            reason={"userReason": normalized_reason},
        )
    result = await work_item_detail(engine, work_item_id, 2.0)
    if result is None:
        raise RuntimeError("Updated work item not found")
    return result


async def update_checklist_item(
    engine: AsyncEngine,
    *,
    profile: str,
    work_item_id: UUID,
    checklist_item_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
    expected_work_version: int,
    status: str,
    note: str | None,
) -> dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    if status not in CHECKLIST_STATUSES:
        raise WorkflowContractError(
            422, "INVALID_CHECKLIST_STATUS", "체크리스트 상태가 올바르지 않습니다."
        )
    audit_key = _audit_key(key)
    async with engine.begin() as connection:
        duplicate = (
            await connection.execute(
                text("SELECT 1 FROM audit_event WHERE idempotency_key = :key"),
                {"key": audit_key},
            )
        ).scalar_one_or_none()
        work = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT status, version
                        FROM work_item
                        WHERE work_item_id = :work_item_id
                        FOR UPDATE
                        """
                    ),
                    {"work_item_id": work_item_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if work is None:
            raise WorkflowContractError(404, "WORK_ITEM_NOT_FOUND", "업무를 찾을 수 없습니다.")
        if duplicate is not None:
            result = await work_item_detail(engine, work_item_id, 2.0)
            if result is None:
                raise RuntimeError("Idempotent work item disappeared")
            return result
        if int(work["version"]) != expected_work_version:
            raise WorkflowContractError(
                409,
                "WORK_ITEM_VERSION_CONFLICT",
                "다른 변경이 먼저 반영되었습니다. 최신 상태를 다시 불러와 주세요.",
            )
        if work["status"] in ("COMPLETED", "DISCARDED"):
            raise WorkflowContractError(
                409, "WORK_ITEM_LOCKED", "완료 또는 폐기된 업무의 체크리스트는 수정할 수 없습니다."
            )
        item = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT status
                        FROM work_item_checklist
                        WHERE checklist_item_id = :item_id
                          AND work_item_id = :work_item_id
                        FOR UPDATE
                        """
                    ),
                    {"item_id": checklist_item_id, "work_item_id": work_item_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if item is None:
            raise WorkflowContractError(
                404, "CHECKLIST_ITEM_NOT_FOUND", "체크리스트 항목을 찾을 수 없습니다."
            )
        await connection.execute(
            text(
                """
                UPDATE work_item_checklist
                SET status = CAST(:status AS varchar),
                    note = :note,
                    completed_at = CASE
                        WHEN CAST(:status AS varchar) = 'DONE'
                        THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE checklist_item_id = :item_id
                """
            ),
            {
                "item_id": checklist_item_id,
                "status": status,
                "note": note.strip() if note and note.strip() else None,
            },
        )
        aggregate = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT count(1) AS total,
                               count(1) FILTER (WHERE status IN ('DONE', 'SKIPPED')) AS finished
                        FROM work_item_checklist
                        WHERE work_item_id = :work_item_id
                        """
                    ),
                    {"work_item_id": work_item_id},
                )
            )
            .mappings()
            .one()
        )
        progress = (
            round(int(aggregate["finished"]) * 85 / int(aggregate["total"]))
            if int(aggregate["total"]) > 0
            else 0
        )
        await connection.execute(
            text(
                """
                UPDATE work_item
                SET progress = :progress,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE work_item_id = :work_item_id
                """
            ),
            {"work_item_id": work_item_id, "progress": progress},
        )
        await _insert_audit(
            connection,
            profile=profile,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=audit_key,
            action="WORK_ITEM_CHECKLIST_CHANGED",
            target_id=work_item_id,
            target_version=expected_work_version + 1,
            before_state={"checklistItemId": str(checklist_item_id), "status": item["status"]},
            after_state={"checklistItemId": str(checklist_item_id), "status": status},
            reason={"noteProvided": bool(note and note.strip())},
        )
    result = await work_item_detail(engine, work_item_id, 2.0)
    if result is None:
        raise RuntimeError("Updated work item not found")
    return result


async def case_closure_review(
    engine: AsyncEngine,
    case_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT c.case_id, c.case_number, c.title, c.status,
                                   c.version AS case_version,
                                   c.source_status, c.opened_at, c.updated_at,
                                   c.source_resolved_at, c.closed_at, c.close_reason,
                                   coalesce(work.incomplete_count, 0) AS incomplete_count,
                                   coalesce(work.completed_count, 0) AS completed_count,
                                   coalesce(work.discarded_count, 0) AS discarded_count,
                                   coalesce(work.unreasoned_discarded_count, 0)
                                       AS unreasoned_discarded_count,
                                   coalesce(bundle.status, 'INSUFFICIENT') AS evidence_status,
                                   bundle.warning AS evidence_warning,
                                   closure.case_closure_id, closure.version AS closure_version,
                                   closure.summary AS closure_summary,
                                   closure.close_reason AS closure_close_reason,
                                   closure.warning_acknowledged AS closure_warning_acknowledged,
                                   closure.created_at AS closure_created_at
                            FROM case_record c
                            LEFT JOIN LATERAL (
                                SELECT count(1) FILTER (
                                           WHERE status IN (
                                               'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                                               'ON_HOLD', 'FAILED'
                                           )
                                       ) AS incomplete_count,
                                       count(1) FILTER (WHERE item.status = 'COMPLETED')
                                           AS completed_count,
                                       count(1) FILTER (WHERE item.status = 'DISCARDED')
                                           AS discarded_count,
                                       count(1) FILTER (
                                           WHERE item.status = 'DISCARDED'
                                             AND NOT EXISTS (
                                                 SELECT 1
                                                 FROM audit_event audit
                                                 WHERE audit.target_type = 'work_item'
                                                   AND audit.target_id = item.work_item_id::text
                                                   AND audit.action = 'WORK_ITEM_STATUS_CHANGED'
                                                   AND audit.after_state ->> 'status' = 'DISCARDED'
                                                   AND length(trim(coalesce(
                                                       audit.reason ->> 'userReason', ''
                                                   ))) > 0
                                             )
                                       ) AS unreasoned_discarded_count
                                FROM work_item item
                                WHERE item.case_id = c.case_id
                            ) work ON true
                            LEFT JOIN evidence_bundle bundle
                              ON bundle.case_id = c.case_id AND bundle.is_current
                            LEFT JOIN case_closure closure
                              ON closure.case_id = c.case_id
                             AND closure.status = 'COMPLETED'
                            WHERE c.case_id = :case_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            incomplete_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT work_item_id, title, status, priority, progress, updated_at
                            FROM work_item
                            WHERE case_id = :case_id
                              AND status IN (
                                  'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                                  'ON_HOLD', 'FAILED'
                              )
                            ORDER BY
                              CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,
                              updated_at DESC
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
            unreasoned_discarded_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT item.work_item_id, item.title, item.status,
                                   item.priority, item.progress, item.updated_at
                            FROM work_item item
                            WHERE item.case_id = :case_id
                              AND item.status = 'DISCARDED'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM audit_event audit
                                  WHERE audit.target_type = 'work_item'
                                    AND audit.target_id = item.work_item_id::text
                                    AND audit.action = 'WORK_ITEM_STATUS_CHANGED'
                                    AND audit.after_state ->> 'status' = 'DISCARDED'
                                    AND length(trim(coalesce(
                                        audit.reason ->> 'userReason', ''
                                    ))) > 0
                              )
                            ORDER BY item.updated_at DESC
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
        blocking_reasons: list[str] = []
        if row["status"] in ("CLOSED", "MERGED"):
            blocking_reasons.append("CASE_ALREADY_TERMINAL")
        if int(row["incomplete_count"]) > 0:
            blocking_reasons.append("CASE_WORK_INCOMPLETE")
        if int(row["unreasoned_discarded_count"]) > 0:
            blocking_reasons.append("DISCARD_REASON_REQUIRED")
        return {
            "caseId": str(row["case_id"]),
            "caseNumber": row["case_number"],
            "title": row["title"],
            "status": row["status"],
            "version": int(row["case_version"]),
            "sourceStatus": row["source_status"],
            "openedAt": _iso(row["opened_at"]),
            "updatedAt": _iso(row["updated_at"]),
            "sourceResolvedAt": _iso(row["source_resolved_at"]),
            "closedAt": _iso(row["closed_at"]),
            "closeReason": row["close_reason"],
            "evidenceStatus": row["evidence_status"],
            "evidenceWarning": (
                row["evidence_warning"]
                or (
                    "현재 Case에 연결된 근거 묶음이 없습니다. 결과 요약에는 근거 부족 경고가 유지됩니다."
                    if row["evidence_status"] == "INSUFFICIENT"
                    else None
                )
            ),
            "workSummary": {
                "incomplete": int(row["incomplete_count"]),
                "completed": int(row["completed_count"]),
                "discarded": int(row["discarded_count"]),
                "unreasonedDiscarded": int(row["unreasoned_discarded_count"]),
            },
            "incompleteWorkItems": [
                {
                    "workItemId": str(item["work_item_id"]),
                    "title": item["title"],
                    "status": item["status"],
                    "priority": item["priority"],
                    "progress": int(item["progress"]),
                    "updatedAt": _iso(item["updated_at"]),
                }
                for item in incomplete_rows
            ],
            "unreasonedDiscardedWorkItems": [
                {
                    "workItemId": str(item["work_item_id"]),
                    "title": item["title"],
                    "status": item["status"],
                    "priority": item["priority"],
                    "progress": int(item["progress"]),
                    "updatedAt": _iso(item["updated_at"]),
                }
                for item in unreasoned_discarded_rows
            ],
            "completedClosure": (
                {
                    "caseClosureId": str(row["case_closure_id"]),
                    "version": int(row["closure_version"]),
                    "summary": row["closure_summary"],
                    "closeReason": row["closure_close_reason"],
                    "warningAcknowledged": bool(row["closure_warning_acknowledged"]),
                    "createdAt": _iso(row["closure_created_at"]),
                }
                if row["case_closure_id"] is not None
                else None
            ),
            "canClose": not blocking_reasons,
            "blockingReasons": blocking_reasons,
            "closurePolicy": "ALL_WORK_TERMINAL",
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.0))


async def _insert_audit(
    connection: AsyncConnection,
    *,
    profile: str,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str,
    action: str,
    target_id: UUID,
    target_version: int,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    reason: dict[str, Any],
    target_type: str = "work_item",
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO audit_event (
                audit_event_id, profile, actor_type, actor_user_id,
                action, target_type, target_id, target_version,
                before_state, after_state, reason, correlation_id,
                idempotency_key, output_sha256
            )
            VALUES (
                :audit_event_id, :profile, 'USER', :user_id,
                :action, :target_type, :target_id, :target_version,
                CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                CAST(:reason AS jsonb), :correlation_id,
                :idempotency_key, :output_sha256
            )
            """
        ),
        {
            "audit_event_id": uuid4(),
            "profile": profile,
            "user_id": user_id,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id),
            "target_version": target_version,
            "before_state": json.dumps(before_state) if before_state is not None else None,
            "after_state": json.dumps(after_state),
            "reason": json.dumps(reason),
            "correlation_id": request_id,
            "idempotency_key": idempotency_key,
            "output_sha256": hashlib.sha256(
                json.dumps(after_state, sort_keys=True).encode()
            ).hexdigest(),
        },
    )



async def close_case(
    engine: AsyncEngine,
    *,
    profile: str,
    case_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str | None,
    expected_version: int,
    close_reason: str,
    summary: str,
    warning_acknowledged: bool,
) -> dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    normalized_reason = close_reason.strip().upper()
    normalized_summary = summary.strip()
    if normalized_reason not in CLOSE_REASONS:
        raise WorkflowContractError(
            422,
            "INVALID_CLOSE_REASON",
            "종료 사유는 해소·오탐·중복·기타 중 하나여야 합니다.",
        )
    if not normalized_summary or len(normalized_summary) > 4000:
        raise WorkflowContractError(
            422,
            "CLOSURE_SUMMARY_REQUIRED",
            "종료 결과 요약을 1~4000자로 입력해 주세요.",
        )

    reused = False
    async with engine.begin() as connection:
        duplicate = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT case_id
                        FROM case_closure
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
            if UUID(str(duplicate["case_id"])) != case_id:
                raise WorkflowContractError(
                    409,
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "다른 Case 종료에 사용된 Idempotency-Key입니다.",
                )
            reused = True
        else:
            case_row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT case_id, case_number, status, source_status,
                                   source_resolved_at, version
                            FROM case_record
                            WHERE case_id = :case_id
                            FOR UPDATE
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if case_row is None:
                raise WorkflowContractError(
                    404,
                    "CASE_NOT_FOUND",
                    "Case를 찾을 수 없습니다.",
                )
            if case_row["status"] == "CLOSED":
                raise WorkflowContractError(
                    409,
                    "CASE_ALREADY_CLOSED",
                    "이미 종료된 Case입니다.",
                )
            if case_row["status"] == "MERGED":
                raise WorkflowContractError(
                    409,
                    "CASE_MERGED",
                    "병합된 Case는 별도로 종료할 수 없습니다.",
                )
            if int(case_row["version"]) != expected_version:
                raise WorkflowContractError(
                    409,
                    "CASE_VERSION_CONFLICT",
                    "다른 변경이 먼저 반영되었습니다. 최신 종료 조건을 다시 확인해 주세요.",
                )
            if (
                normalized_reason == "RESOLVED"
                and case_row["source_status"] != "RESOLVED"
                and case_row["status"] != "SOURCE_RESOLVED_REVIEW"
            ):
                raise WorkflowContractError(
                    409,
                    "SOURCE_NOT_RESOLVED",
                    "해소 사유로 종료하려면 원천 종료·해제가 먼저 확인되어야 합니다.",
                )

            work_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT item.work_item_id, item.title, item.status,
                                   item.priority, item.progress, item.updated_at,
                                   CASE
                                     WHEN item.status <> 'DISCARDED' THEN true
                                     ELSE EXISTS (
                                       SELECT 1
                                       FROM audit_event audit
                                       WHERE audit.target_type = 'work_item'
                                         AND audit.target_id = item.work_item_id::text
                                         AND audit.action = 'WORK_ITEM_STATUS_CHANGED'
                                         AND audit.after_state ->> 'status' = 'DISCARDED'
                                         AND length(trim(coalesce(
                                           audit.reason ->> 'userReason', ''
                                         ))) > 0
                                     )
                                   END AS discard_reasoned
                            FROM work_item item
                            WHERE item.case_id = :case_id
                            ORDER BY item.updated_at DESC
                            FOR UPDATE OF item
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
            incomplete = [
                row
                for row in work_rows
                if row["status"] not in ("COMPLETED", "DISCARDED")
            ]
            if incomplete:
                raise WorkflowContractError(
                    409,
                    "CASE_WORK_INCOMPLETE",
                    "미완료·보류·실패·승인대기 업무를 모두 처리해야 Case를 종료할 수 있습니다.",
                    {
                        "caseId": str(case_id),
                        "caseStatus": case_row["status"],
                        "incompleteWorkItems": [
                            {
                                "workItemId": str(row["work_item_id"]),
                                "title": row["title"],
                                "status": row["status"],
                                "priority": row["priority"],
                                "progress": int(row["progress"]),
                                "updatedAt": _iso(row["updated_at"]),
                            }
                            for row in incomplete
                        ],
                    },
                )
            unreasoned = [
                row
                for row in work_rows
                if row["status"] == "DISCARDED" and not bool(row["discard_reasoned"])
            ]
            if unreasoned:
                raise WorkflowContractError(
                    409,
                    "DISCARD_REASON_REQUIRED",
                    "폐기 사유 기록이 없는 업무를 확인해야 Case를 종료할 수 있습니다.",
                    {
                        "caseId": str(case_id),
                        "unreasonedDiscardedWorkItems": [
                            {
                                "workItemId": str(row["work_item_id"]),
                                "title": row["title"],
                                "status": row["status"],
                            }
                            for row in unreasoned
                        ],
                    },
                )

            evidence_row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT status, warning
                            FROM evidence_bundle
                            WHERE case_id = :case_id AND is_current
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            evidence_status = (
                str(evidence_row["status"])
                if evidence_row is not None
                else "INSUFFICIENT"
            )
            evidence_warning = (
                evidence_row["warning"] if evidence_row is not None else None
            )
            if evidence_status != "SUFFICIENT" and not warning_acknowledged:
                raise WorkflowContractError(
                    409,
                    "EVIDENCE_WARNING_ACK_REQUIRED",
                    "근거 부족·충돌 경고를 확인하면 종료 결과를 기록할 수 있습니다.",
                )

            closure_version = int(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT coalesce(max(version), 0) + 1
                            FROM case_closure
                            WHERE case_id = :case_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                ).scalar_one()
            )
            snapshot = {
                "caseNumber": case_row["case_number"],
                "caseVersion": int(case_row["version"]),
                "caseStatus": case_row["status"],
                "sourceStatus": case_row["source_status"],
                "sourceResolvedAt": _iso(case_row["source_resolved_at"]),
                "completedWorkItemCount": sum(
                    row["status"] == "COMPLETED" for row in work_rows
                ),
                "discardedWorkItemCount": sum(
                    row["status"] == "DISCARDED" for row in work_rows
                ),
                "evidenceStatus": evidence_status,
                "evidenceWarning": evidence_warning,
            }
            closure_id = uuid4()
            await connection.execute(
                text(
                    """
                    INSERT INTO case_closure (
                        case_closure_id, case_id, version, status,
                        close_reason, summary, incomplete_work_item_count,
                        evidence_status, warning_acknowledged, snapshot,
                        requested_by, idempotency_key, completed_at
                    )
                    VALUES (
                        :closure_id, :case_id, :version, 'COMPLETED',
                        :close_reason, :summary, 0,
                        :evidence_status, :warning_acknowledged,
                        CAST(:snapshot AS jsonb), :requested_by,
                        :idempotency_key, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "closure_id": closure_id,
                    "case_id": case_id,
                    "version": closure_version,
                    "close_reason": normalized_reason,
                    "summary": normalized_summary,
                    "evidence_status": evidence_status,
                    "warning_acknowledged": warning_acknowledged,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                    "requested_by": user_id,
                    "idempotency_key": key,
                },
            )
            next_version = int(case_row["version"]) + 1
            await connection.execute(
                text(
                    """
                    UPDATE case_record
                    SET status = 'CLOSED', close_reason = :close_reason,
                        closed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        version = :next_version
                    WHERE case_id = :case_id
                    """
                ),
                {
                    "case_id": case_id,
                    "close_reason": normalized_reason,
                    "next_version": next_version,
                },
            )
            await _insert_audit(
                connection,
                profile=profile,
                user_id=user_id,
                request_id=request_id,
                idempotency_key=_audit_key(f"case-close:{key}"),
                action="CASE_CLOSED",
                target_id=case_id,
                target_version=next_version,
                before_state={
                    "status": case_row["status"],
                    "version": int(case_row["version"]),
                },
                after_state={
                    "status": "CLOSED",
                    "version": next_version,
                    "closeReason": normalized_reason,
                    "caseClosureId": str(closure_id),
                },
                reason={
                    "summary": normalized_summary,
                    "warningAcknowledged": warning_acknowledged,
                },
                target_type="case_record",
            )

    result = await case_closure_review(engine, case_id, 2.0)
    if result is None:
        raise RuntimeError("Closed Case disappeared")
    return {**result, "reused": reused}
