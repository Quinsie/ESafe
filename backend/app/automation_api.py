from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings


class AutomationContractError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_STATUSES = frozenset({"RUNNING", "SUCCEEDED", "FAILED", "SKIPPED", "RECORDED"})
_ENTRY_TYPES = frozenset({"AUTOMATION_RUN", "AUDIT_EVENT"})
_SOURCES = frozenset({"NFDS", "KMA_WARNING", "DISASTER_MESSAGE"})
_WINDOW_HOURS = frozenset({24, 168, 720})


def _validate_filter(
    value: str | None,
    allowed: frozenset[str],
    *,
    code: str,
    label: str,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in allowed:
        raise AutomationContractError(code, f"지원하지 않는 {label}입니다.")
    return normalized


async def automation_activity(
    engine: AsyncEngine,
    *,
    page: int,
    page_size: int,
    status: str | None,
    entry_type: str | None,
    source: str | None,
    hours: int | None,
    search: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    status = _validate_filter(
        status,
        _STATUSES,
        code="INVALID_AUTOMATION_STATUS",
        label="자동화 상태",
    )
    entry_type = _validate_filter(
        entry_type,
        _ENTRY_TYPES,
        code="INVALID_AUTOMATION_ENTRY_TYPE",
        label="활동 유형",
    )
    source = _validate_filter(
        source,
        _SOURCES,
        code="INVALID_AUTOMATION_SOURCE",
        label="신호 원천",
    )
    if hours is not None and hours not in _WINDOW_HOURS:
        raise AutomationContractError(
            "INVALID_AUTOMATION_WINDOW",
            "조회 기간은 24시간, 7일 또는 30일만 지원합니다.",
        )
    normalized_search = search.strip() if search and search.strip() else None
    params = {
        "status": status,
        "entry_type": entry_type,
        "source": source,
        "hours": hours,
        "search": normalized_search,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    activity_cte = """
        WITH activity AS (
            SELECT run.started_at AS occurred_at,
                   'AUTOMATION_RUN'::text AS entry_type,
                   run.automation_run_id::text AS entry_id,
                   run.status,
                   run.run_type AS category,
                   run.trigger_type,
                   run.source,
                   'SYSTEM'::text AS actor_type,
                   NULL::text AS actor_name,
                   run.case_id::text AS case_id,
                   case_record.case_number,
                   run.work_item_id::text AS work_item_id,
                   work.title AS work_item_title,
                   run.rule_version,
                   run.input_version,
                   run.output_version,
                   run.retry_count,
                   run.error_class,
                   run.finished_at,
                   run.idempotency_key
            FROM automation_run run
            LEFT JOIN case_record ON case_record.case_id = run.case_id
            LEFT JOIN work_item work ON work.work_item_id = run.work_item_id
            UNION ALL
            SELECT audit.occurred_at,
                   'AUDIT_EVENT'::text,
                   audit.audit_event_id::text,
                   'RECORDED'::text,
                   audit.action,
                   NULL::text,
                   NULL::varchar,
                   audit.actor_type,
                   app_user.display_name,
                   CASE
                       WHEN audit.target_type = 'CASE' THEN audit.target_id
                       ELSE NULL
                   END,
                   case_record.case_number,
                   CASE
                       WHEN audit.target_type = 'WORK_ITEM' THEN audit.target_id
                       ELSE NULL
                   END,
                   NULL::text,
                   NULL::varchar,
                   audit.input_sha256,
                   audit.output_sha256,
                   0,
                   NULL::varchar,
                   audit.occurred_at,
                   audit.idempotency_key
            FROM audit_event audit
            LEFT JOIN app_user ON app_user.user_id = audit.actor_user_id
            LEFT JOIN case_record
              ON audit.target_type = 'CASE'
             AND case_record.case_id::text = audit.target_id
        )
    """
    where_clause = """
        WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
          AND (CAST(:entry_type AS text) IS NULL OR entry_type = CAST(:entry_type AS text))
          AND (CAST(:source AS text) IS NULL OR source = CAST(:source AS text))
          AND (
              CAST(:hours AS integer) IS NULL
              OR occurred_at >= CURRENT_TIMESTAMP - make_interval(hours => CAST(:hours AS integer))
          )
          AND (
              CAST(:search AS text) IS NULL
              OR category ILIKE '%' || CAST(:search AS text) || '%'
              OR coalesce(case_number, '') ILIKE '%' || CAST(:search AS text) || '%'
              OR coalesce(work_item_title, '') ILIKE '%' || CAST(:search AS text) || '%'
              OR coalesce(entry_id, '') ILIKE '%' || CAST(:search AS text) || '%'
          )
    """
    async with engine.connect() as connection:
        await connection.execute(
            text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
            {"timeout_ms": f"{max(1, int(timeout_seconds * 1000))}ms"},
        )
        summary = (
            await connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM automation_run
                            WHERE started_at >= (
                                date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')
                                AT TIME ZONE 'Asia/Seoul'
                            )
                        ) + (
                            SELECT count(*)
                            FROM audit_event
                            WHERE occurred_at >= (
                                date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')
                                AT TIME ZONE 'Asia/Seoul'
                            )
                        ) AS today_activity,
                        (
                            SELECT count(*)
                            FROM work_item
                            WHERE status = 'WAITING_APPROVAL'
                        ) AS waiting_approval,
                        (
                            SELECT count(*)
                            FROM automation_run
                            WHERE status = 'RUNNING'
                        ) AS running,
                        (
                            SELECT count(*)
                            FROM automation_run
                            WHERE status = 'FAILED'
                              AND started_at >= CURRENT_TIMESTAMP - interval '24 hours'
                        ) + (
                            SELECT count(*)
                            FROM work_item
                            WHERE status = 'FAILED'
                              AND updated_at >= CURRENT_TIMESTAMP - interval '24 hours'
                        ) AS failed_last_24h
                    """
                )
            )
        ).mappings().one()
        total = int(
            (
                await connection.execute(
                    text(f"{activity_cte} SELECT count(*) FROM activity {where_clause}"),
                    params,
                )
            ).scalar_one()
        )
        rows = (
            await connection.execute(
                text(
                    f"""
                    {activity_cte}
                    SELECT occurred_at, entry_type, entry_id, status, category,
                           trigger_type, source, actor_type, actor_name, case_id,
                           case_number, work_item_id, work_item_title, rule_version,
                           input_version, output_version, retry_count, error_class,
                           finished_at
                    FROM activity
                    {where_clause}
                    ORDER BY occurred_at DESC, entry_id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        ).mappings().all()
    return {
        "summary": {
            "todayActivity": int(summary["today_activity"] or 0),
            "waitingApproval": int(summary["waiting_approval"] or 0),
            "running": int(summary["running"] or 0),
            "failedLast24h": int(summary["failed_last_24h"] or 0),
        },
        "items": [
            {
                "occurredAt": row["occurred_at"].isoformat(),
                "entryType": row["entry_type"],
                "entryId": row["entry_id"],
                "status": row["status"],
                "category": row["category"],
                "triggerType": row["trigger_type"],
                "source": row["source"],
                "actor": {
                    "type": row["actor_type"],
                    "displayName": row["actor_name"],
                },
                "case": (
                    {
                        "caseId": row["case_id"],
                        "caseNumber": row["case_number"],
                    }
                    if row["case_id"] is not None
                    else None
                ),
                "workItem": (
                    {
                        "workItemId": row["work_item_id"],
                        "title": row["work_item_title"],
                    }
                    if row["work_item_id"] is not None
                    else None
                ),
                "run": (
                    {
                        "ruleVersion": row["rule_version"],
                        "inputVersion": row["input_version"],
                        "outputVersion": row["output_version"],
                        "retryCount": int(row["retry_count"] or 0),
                        "errorClass": row["error_class"],
                        "finishedAt": (
                            row["finished_at"].isoformat()
                            if row["finished_at"] is not None
                            else None
                        ),
                    }
                    if row["entry_type"] == "AUTOMATION_RUN"
                    else None
                ),
            }
            for row in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "dataAsOf": datetime.now(UTC).isoformat(),
    }


def automation_policies(settings: Settings) -> dict[str, Any]:
    sources = [
        {
            "source": "NFDS",
            "enabled": settings.profile == "DEMO" or settings.nfds_enabled,
            "mode": "FIXTURE" if settings.profile == "DEMO" else "LIVE",
        },
        {
            "source": "KMA_WARNING",
            "enabled": True,
            "mode": "FIXTURE" if settings.profile == "DEMO" else "LIVE",
        },
        {
            "source": "DISASTER_MESSAGE",
            "enabled": True,
            "mode": "FIXTURE" if settings.profile == "DEMO" else "LIVE",
        },
    ]
    return {
        "policyVersion": "automation-policy-v1",
        "mutable": False,
        "profile": settings.profile,
        "scope": {
            "regions": [
                {"regionCode": "29", "name": "광주광역시"},
                {"regionCode": "46", "name": "전라남도"},
            ],
            "weatherWarningTypes": "ALL",
            "disasterMessageFilter": "ELECTRICAL_AND_NATURAL_HAZARD_V1",
        },
        "schedule": {
            "pollIntervalMinutes": 10,
            "jitterSeconds": {"minimum": 0, "maximum": 60},
            "caseReflectionTargetMinutes": 2,
            "delayedAfterMinutes": 30,
            "outageAfterMinutes": 60,
        },
        "sources": sources,
        "deterministicRules": {
            "sameSourceUpdate": True,
            "crossSourceFireWindowHours": 2,
            "crossSourceFireDistanceM": 500,
            "pointImpactDefaultRadiusM": 100,
            "allowedImpactRadiusM": [100, 500, 1000, 3000, 5000],
            "weatherImpactScope": "ADMIN_REGION",
            "highRiskTopPercentile": 10,
            "automaticMergeByLlm": False,
        },
        "approvalBoundary": {
            "singleUserSingleStage": True,
            "decisions": ["APPROVED", "ON_HOLD", "DISCARDED"],
            "externalEffectWithoutApproval": False,
            "actualEmailOrOfficialDispatch": False,
            "sourceResolvedRequiresUserClose": True,
        },
        "retry": {
            "sourceSchemaBackoffMinutes": [20, 40, 80],
            "automaticAiRetries": 1,
            "externalEffectRetries": 0,
        },
        "capabilities": [
            {
                "code": "SIGNAL_INGESTION",
                "label": "외부 신호 수집·원문 보존",
                "status": "ACTIVE",
            },
            {
                "code": "CANONICAL_EVENT",
                "label": "표준 이벤트 변환·중복 억제",
                "status": "ACTIVE",
            },
            {
                "code": "CASE_IMPACT",
                "label": "Case 영향 범위·건물 계산",
                "status": "READY_NOT_CONNECTED",
            },
            {
                "code": "RAG_RECOMMENDATION",
                "label": "근거 검색·대응안 생성",
                "status": "NOT_IMPLEMENTED",
            },
            {
                "code": "DOCUMENT_OUTPUT",
                "label": "HWPX·PDF 생성",
                "status": "NOT_IMPLEMENTED",
            },
        ],
    }
