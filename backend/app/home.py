# ruff: noqa: E501
import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_ACTIVE_CASE_STATUSES = ("DETECTED", "ACTIVE", "ON_HOLD", "SOURCE_RESOLVED_REVIEW")
_ACTIVE_WORK_STATUSES = ("QUEUED", "RUNNING", "WAITING_APPROVAL", "ON_HOLD", "FAILED")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


async def briefing_data(engine: AsyncEngine, timeout_seconds: float) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            reference_row = (
                await connection.execute(
                    text(
                        """
                        SELECT i.import_id, i.source_version, s.activated_at,
                               max(r.calculated_at) AS calculated_at,
                               sum(r.building_count) FILTER (WHERE a.level = 'SIDO') AS building_count,
                               sum(r.top_1_count) FILTER (WHERE a.level = 'SIDO') AS top_1_count,
                               sum(r.top_10_count) FILTER (WHERE a.level = 'SIDO') AS top_10_count
                        FROM reference_dataset_state s
                        JOIN reference_import i ON i.import_id = s.active_import_id
                        JOIN region_risk_summary r
                          ON r.reference_month = DATE '2026-03-01'
                         AND r.horizon_days = 60
                         AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        JOIN admin_region a ON a.region_code = r.region_code
                        WHERE s.state_id = true
                        GROUP BY i.import_id, i.source_version, s.activated_at
                        """
                    )
                )
            ).mappings().one()
            regions = (
                await connection.execute(
                    text(
                        """
                        SELECT r.region_code, a.name, a.full_name, r.building_count,
                               r.top_1_count, r.top_10_count, r.score_p99
                        FROM region_risk_summary r
                        JOIN admin_region a ON a.region_code = r.region_code
                        WHERE a.level = 'SIGUNGU'
                          AND r.reference_month = DATE '2026-03-01'
                          AND r.horizon_days = 60
                          AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                          AND EXISTS (
                              SELECT 1 FROM reference_dataset_state WHERE state_id = true
                          )
                        ORDER BY r.top_10_count DESC, r.score_p99 DESC NULLS LAST, r.region_code
                        LIMIT 5
                        """
                    )
                )
            ).mappings().all()
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (WHERE status IN ('DETECTED', 'ACTIVE', 'ON_HOLD')) AS active_cases,
                            count(*) FILTER (WHERE status = 'SOURCE_RESOLVED_REVIEW') AS resolved_review,
                            count(*) FILTER (
                                WHERE status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                                  AND monitoring_priority = 'URGENT'
                            ) AS urgent_cases,
                            max(updated_at) AS last_case_update
                        FROM case_record
                        """
                    )
                )
            ).mappings().one()
            task_counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE status IN ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'ON_HOLD', 'FAILED')
                                  AND due_at <= CURRENT_TIMESTAMP + interval '24 hours'
                            ) AS due_within_24h,
                            count(*) FILTER (WHERE status = 'WAITING_APPROVAL') AS waiting_approval
                        FROM work_item
                        """
                    )
                )
            ).mappings().one()
            recent_cases = (
                await connection.execute(
                    text(
                        """
                        SELECT case_id, case_number, title, case_type, status,
                               monitoring_priority, primary_region_code, updated_at, is_simulated
                        FROM case_record
                        WHERE status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                        ORDER BY CASE monitoring_priority
                                   WHEN 'URGENT' THEN 0 WHEN 'ATTENTION' THEN 1 ELSE 2 END,
                                 updated_at DESC, case_id
                        LIMIT 5
                        """
                    )
                )
            ).mappings().all()

        active_total = int(counts["active_cases"] or 0) + int(counts["resolved_review"] or 0)
        if active_total == 0:
            headline = {
                "state": "NO_ACTIVE_CASES",
                "title": "현재 확인된 광주·전남 관제 Case가 없습니다.",
                "description": "수집원 상태를 함께 확인하세요. 사건이 감지되면 이 영역에 자동으로 표시됩니다.",
                "caseId": None,
            }
        else:
            first_case = recent_cases[0]
            headline = {
                "state": "ACTION_REQUIRED",
                "title": f"확인이 필요한 관제 Case {active_total}건이 있습니다.",
                "description": str(first_case["title"]),
                "caseId": str(first_case["case_id"]),
            }

        return {
            "headline": headline,
            "metrics": {
                "urgentCases": int(counts["urgent_cases"] or 0),
                "activeCases": int(counts["active_cases"] or 0),
                "dueWithin24Hours": int(task_counts["due_within_24h"] or 0),
                "waitingApproval": int(task_counts["waiting_approval"] or 0),
                "sourceResolvedReview": int(counts["resolved_review"] or 0),
            },
            "riskReference": {
                "importId": reference_row["import_id"],
                "sourceVersion": reference_row["source_version"],
                "lineageVersion": "v27.1-focus-2026-03-60d",
                "referenceMonth": "2026-03",
                "horizonDays": 60,
                "buildingCount": int(reference_row["building_count"] or 0),
                "top1Count": int(reference_row["top_1_count"] or 0),
                "top10Count": int(reference_row["top_10_count"] or 0),
                "calculatedAt": _iso(reference_row["calculated_at"]),
            },
            "priorityRegions": [
                {
                    "regionCode": row["region_code"],
                    "name": row["name"],
                    "fullName": row["full_name"],
                    "buildingCount": int(row["building_count"]),
                    "top1Count": int(row["top_1_count"]),
                    "top10Count": int(row["top_10_count"]),
                    "top10Share": round(int(row["top_10_count"]) / int(row["building_count"]) * 100, 2),
                    "scoreP99": float(row["score_p99"]) if row["score_p99"] is not None else None,
                }
                for row in regions
            ],
            "recentCases": [
                {
                    "caseId": str(row["case_id"]),
                    "caseNumber": row["case_number"],
                    "title": row["title"],
                    "caseType": row["case_type"],
                    "status": row["status"],
                    "monitoringPriority": row["monitoring_priority"],
                    "primaryRegionCode": row["primary_region_code"],
                    "updatedAt": _iso(row["updated_at"]),
                    "isSimulated": row["is_simulated"],
                }
                for row in recent_cases
            ],
            "dataAsOf": _iso(counts["last_case_update"] or reference_row["calculated_at"]),
        }

    return await asyncio.wait_for(query(), timeout=timeout_seconds)


async def task_summary_data(engine: AsyncEngine, timeout_seconds: float) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT status, count(*) AS item_count
                        FROM work_item
                        GROUP BY status
                        """
                    )
                )
            ).mappings().all()
            items = (
                await connection.execute(
                    text(
                        """
                        SELECT work_item_id, case_id, work_type, status, priority, title,
                               due_at, progress, retry_count, error_class, updated_at
                        FROM work_item
                        WHERE status IN ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'ON_HOLD', 'FAILED')
                        ORDER BY CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,
                                 due_at ASC NULLS LAST, created_at, work_item_id
                        LIMIT 8
                        """
                    )
                )
            ).mappings().all()
        by_status = {row["status"]: int(row["item_count"]) for row in counts}
        return {
            "counts": {
                "queued": by_status.get("QUEUED", 0),
                "running": by_status.get("RUNNING", 0),
                "waitingApproval": by_status.get("WAITING_APPROVAL", 0),
                "onHold": by_status.get("ON_HOLD", 0),
                "failed": by_status.get("FAILED", 0),
            },
            "items": [
                {
                    "workItemId": str(row["work_item_id"]),
                    "caseId": str(row["case_id"]) if row["case_id"] is not None else None,
                    "workType": row["work_type"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "title": row["title"],
                    "dueAt": _iso(row["due_at"]),
                    "progress": int(row["progress"]),
                    "retryCount": int(row["retry_count"]),
                    "errorClass": row["error_class"],
                    "updatedAt": _iso(row["updated_at"]),
                }
                for row in items
            ],
            "dataAsOf": _iso(max((row["updated_at"] for row in items), default=None)),
        }

    return await asyncio.wait_for(query(), timeout=timeout_seconds)


async def source_health_data(engine: AsyncEngine, timeout_seconds: float) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT source, execution_mode, enabled,
                               CASE
                                   WHEN NOT enabled THEN 'DISABLED'
                                   WHEN status = 'OUTAGE' THEN 'OUTAGE'
                                   WHEN last_success_at IS NULL THEN 'OUTAGE'
                                   WHEN last_success_at <= CURRENT_TIMESTAMP - interval '60 minutes' THEN 'OUTAGE'
                                   WHEN status = 'DELAYED'
                                     OR last_success_at <= CURRENT_TIMESTAMP - interval '30 minutes' THEN 'DELAYED'
                                   ELSE 'HEALTHY'
                               END AS effective_status,
                               last_attempt_at, last_success_at, last_failure_at,
                               consecutive_failures, next_poll_at, backoff_until,
                               parser_version, contract_version, updated_at
                        FROM source_health
                        ORDER BY CASE source
                                   WHEN 'NFDS' THEN 1 WHEN 'KMA_WARNING' THEN 2 ELSE 3 END
                        """
                    )
                )
            ).mappings().all()
        statuses = [row["effective_status"] for row in rows]
        if not rows or "OUTAGE" in statuses:
            summary = "OUTAGE"
        elif "DELAYED" in statuses:
            summary = "DELAYED"
        elif all(status == "DISABLED" for status in statuses):
            summary = "DISABLED"
        else:
            summary = "HEALTHY"
        return {
            "summary": summary,
            "sources": [
                {
                    "source": row["source"],
                    "executionMode": row["execution_mode"],
                    "enabled": row["enabled"],
                    "status": row["effective_status"],
                    "lastAttemptAt": _iso(row["last_attempt_at"]),
                    "lastSuccessAt": _iso(row["last_success_at"]),
                    "lastFailureAt": _iso(row["last_failure_at"]),
                    "consecutiveFailures": int(row["consecutive_failures"]),
                    "nextPollAt": _iso(row["next_poll_at"]),
                    "backoffUntil": _iso(row["backoff_until"]),
                    "parserVersion": row["parser_version"],
                    "contractVersion": row["contract_version"],
                    "updatedAt": _iso(row["updated_at"]),
                }
                for row in rows
            ],
            "dataAsOf": _iso(max((row["updated_at"] for row in rows), default=None)),
        }

    return await asyncio.wait_for(query(), timeout=timeout_seconds)