# ruff: noqa: E501
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

OPEN_CASE_STATUSES: Final = (
    "DETECTED",
    "ACTIVE",
    "ON_HOLD",
    "SOURCE_RESOLVED_REVIEW",
)
CASE_STATUSES: Final = frozenset((*OPEN_CASE_STATUSES, "CLOSED", "MERGED"))
CASE_TYPES: Final = frozenset(("FIRE", "WEATHER_WARNING", "DISASTER_MESSAGE"))
SIGNAL_SOURCES: Final = frozenset(("NFDS", "KMA_WARNING", "DISASTER_MESSAGE"))
RISK_LINEAGE_VERSION: Final = "v27.1-focus-2026-03-60d"


@dataclass(frozen=True)
class CaseContractError(Exception):
    status_code: int
    code: str
    message: str


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _geojson(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("GeoJSON object expected")
    return parsed


def _validate_filter(value: str | None, allowed: frozenset[str], code: str) -> None:
    if value is not None and value not in allowed:
        raise CaseContractError(422, code, "Case 조회 조건이 올바르지 않습니다.")


def _case_item(row: Any) -> dict[str, Any]:
    return {
        "caseId": str(row["case_id"]),
        "caseNumber": row["case_number"],
        "caseType": row["case_type"],
        "title": row["title"],
        "status": row["status"],
        "sourceStatus": row["source_status"],
        "monitoringPriority": row["monitoring_priority"],
        "primaryRegion": (
            {
                "regionCode": row["primary_region_code"],
                "name": row["region_name"],
                "fullName": row["region_full_name"],
            }
            if row["primary_region_code"] is not None
            else None
        ),
        "locationPrecision": row["location_precision"],
        "sources": list(row["sources"] or []),
        "signalCount": int(row["signal_count"]),
        "impactBuildingCount": int(row["impact_building_count"]),
        "highRiskBuildingCount": int(row["high_risk_building_count"]),
        "incidentBuildingCount": int(row["incident_building_count"]),
        "openWorkItemCount": int(row["open_work_item_count"]),
        "relationCandidateCount": int(row["relation_candidate_count"]),
        "openedAt": _iso(row["opened_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "sourceResolvedAt": _iso(row["source_resolved_at"]),
        "isSimulated": bool(row["is_simulated"]),
        "scenarioId": str(row["scenario_id"]) if row["scenario_id"] is not None else None,
        "version": int(row["version"]),
    }


async def case_list(
    engine: AsyncEngine,
    *,
    page: int,
    page_size: int,
    status: str | None,
    case_type: str | None,
    source: str | None,
    region_code: str | None,
    search: str | None,
    sort: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    _validate_filter(status, CASE_STATUSES, "INVALID_CASE_STATUS")
    _validate_filter(case_type, CASE_TYPES, "INVALID_CASE_TYPE")
    _validate_filter(source, SIGNAL_SOURCES, "INVALID_SIGNAL_SOURCE")
    order_by = {
        "updated": "c.updated_at DESC, c.case_id",
        "opened": "c.opened_at DESC, c.case_id",
        "priority": (
            "CASE c.monitoring_priority WHEN 'URGENT' THEN 0 "
            "WHEN 'ATTENTION' THEN 1 ELSE 2 END, c.updated_at DESC, c.case_id"
        ),
    }.get(sort)
    if order_by is None:
        raise CaseContractError(422, "INVALID_CASE_SORT", "Case 정렬값이 올바르지 않습니다.")
    normalized_search = search.strip() if search and search.strip() else None
    params = {
        "status": status,
        "case_type": case_type,
        "source": source,
        "region_code": region_code,
        "search": f"%{normalized_search}%" if normalized_search else None,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters = """
        (CAST(:status AS varchar) IS NULL OR c.status = CAST(:status AS varchar))
        AND (CAST(:case_type AS varchar) IS NULL OR c.case_type = CAST(:case_type AS varchar))
        AND (
            CAST(:source AS varchar) IS NULL
            OR EXISTS (
                SELECT 1
                FROM case_signal_link source_link
                JOIN signal_event source_event
                  ON source_event.signal_event_id = source_link.signal_event_id
                WHERE source_link.case_id = c.case_id
                  AND source_event.source = CAST(:source AS varchar)
            )
        )
        AND (
            CAST(:region_code AS varchar) IS NULL
            OR c.primary_region_code = CAST(:region_code AS varchar)
            OR EXISTS (
                SELECT 1
                FROM case_signal_link region_link
                JOIN signal_event region_event
                  ON region_event.signal_event_id = region_link.signal_event_id
                WHERE region_link.case_id = c.case_id
                  AND CAST(:region_code AS varchar) = ANY(region_event.region_codes)
            )
        )
        AND (
            CAST(:search AS varchar) IS NULL
            OR c.case_number ILIKE CAST(:search AS varchar)
            OR c.title ILIKE CAST(:search AS varchar)
            OR coalesce(c.normalized_address, '') ILIKE CAST(:search AS varchar)
            OR coalesce(region.full_name, '') ILIKE CAST(:search AS varchar)
        )
    """

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            total = int(
                (
                    await connection.execute(
                        text(
                            f"""
                            SELECT count(1)
                            FROM case_record c
                            LEFT JOIN admin_region region
                              ON region.region_code = c.primary_region_code
                            WHERE {filters}
                            """
                        ),
                        params,
                    )
                ).scalar_one()
            )
            rows = (
                (
                    await connection.execute(
                        text(
                            f"""
                            WITH selected AS (
                                SELECT c.*
                                FROM case_record c
                                LEFT JOIN admin_region region
                                  ON region.region_code = c.primary_region_code
                                WHERE {filters}
                                ORDER BY {order_by}
                                LIMIT :limit OFFSET :offset
                            )
                            SELECT c.*,
                                   region.name AS region_name,
                                   region.full_name AS region_full_name,
                                   coalesce(signals.sources, '{{}}'::text[]) AS sources,
                                   coalesce(signals.signal_count, 0) AS signal_count,
                                   coalesce(impact.impact_count, 0) AS impact_building_count,
                                   coalesce(impact.high_risk_count, 0) AS high_risk_building_count,
                                   coalesce(impact.incident_count, 0) AS incident_building_count,
                                   coalesce(work.open_count, 0) AS open_work_item_count,
                                   coalesce(relations.candidate_count, 0) AS relation_candidate_count
                            FROM selected c
                            LEFT JOIN admin_region region
                              ON region.region_code = c.primary_region_code
                            LEFT JOIN LATERAL (
                                SELECT array_agg(DISTINCT event.source ORDER BY event.source) AS sources,
                                       count(1) AS signal_count
                                FROM case_signal_link link
                                JOIN signal_event event
                                  ON event.signal_event_id = link.signal_event_id
                                WHERE link.case_id = c.case_id
                            ) signals ON true
                            LEFT JOIN LATERAL (
                                SELECT count(1) AS impact_count,
                                       count(1) FILTER (WHERE is_high_risk) AS high_risk_count,
                                       count(1) FILTER (WHERE is_incident_building) AS incident_count
                                FROM case_building
                                WHERE case_id = c.case_id
                            ) impact ON true
                            LEFT JOIN LATERAL (
                                SELECT count(1) AS open_count
                                FROM work_item
                                WHERE case_id = c.case_id
                                  AND status IN (
                                      'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                                      'ON_HOLD', 'FAILED'
                                  )
                            ) work ON true
                            LEFT JOIN LATERAL (
                                SELECT count(1) AS candidate_count
                                FROM case_relation
                                WHERE (source_case_id = c.case_id OR target_case_id = c.case_id)
                                  AND relation_type = 'POSSIBLE_SAME_EVENT'
                                  AND resolved_at IS NULL
                            ) relations ON true
                            ORDER BY {order_by.replace("c.", "c.")}
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            summary = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT count(1) AS total,
                                   count(1) FILTER (
                                       WHERE status IN (
                                           'DETECTED', 'ACTIVE', 'ON_HOLD',
                                           'SOURCE_RESOLVED_REVIEW'
                                       )
                                   ) AS open_count,
                                   count(1) FILTER (
                                       WHERE status = 'SOURCE_RESOLVED_REVIEW'
                                   ) AS review_count,
                                   count(1) FILTER (
                                       WHERE monitoring_priority = 'URGENT'
                                         AND status IN (
                                             'DETECTED', 'ACTIVE', 'ON_HOLD',
                                             'SOURCE_RESOLVED_REVIEW'
                                         )
                                   ) AS urgent_count,
                                   count(1) FILTER (WHERE is_simulated) AS simulated_count,
                                   max(updated_at) AS data_as_of
                            FROM case_record
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )
        return {
            "summary": {
                "total": int(summary["total"]),
                "open": int(summary["open_count"]),
                "sourceResolvedReview": int(summary["review_count"]),
                "urgent": int(summary["urgent_count"]),
                "simulated": int(summary["simulated_count"]),
            },
            "items": [_case_item(row) for row in rows],
            "page": page,
            "pageSize": page_size,
            "total": total,
            "dataAsOf": _iso(summary["data_as_of"]),
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.0))


async def case_detail(
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
                            SELECT c.*,
                                   region.name AS region_name,
                                   region.full_name AS region_full_name,
                                   CASE WHEN c.location IS NULL
                                        THEN NULL
                                        ELSE ST_AsGeoJSON(c.location, 7)
                                   END AS location_geojson,
                                   scope.impact_scope_id,
                                   scope.scope_type,
                                   CASE WHEN scope.center IS NULL
                                        THEN NULL
                                        ELSE ST_AsGeoJSON(scope.center, 7)
                                   END AS scope_center_geojson,
                                   scope.radius_m,
                                   scope.region_codes AS scope_region_codes,
                                   scope.precision_warning,
                                   scope.rule_version AS impact_rule_version,
                                   scope.calculated_at AS impact_calculated_at,
                                   coalesce(impact.impact_count, 0) AS impact_building_count,
                                   coalesce(impact.high_risk_count, 0) AS high_risk_building_count,
                                   coalesce(impact.incident_count, 0) AS incident_building_count,
                                   coalesce(work.total_count, 0) AS work_item_count,
                                   coalesce(work.open_count, 0) AS open_work_item_count
                            FROM case_record c
                            LEFT JOIN admin_region region
                              ON region.region_code = c.primary_region_code
                            LEFT JOIN LATERAL (
                                SELECT *
                                FROM case_impact_scope
                                WHERE case_id = c.case_id
                                ORDER BY calculated_at DESC, impact_scope_id DESC
                                LIMIT 1
                            ) scope ON true
                            LEFT JOIN LATERAL (
                                SELECT count(1) AS impact_count,
                                       count(1) FILTER (WHERE is_high_risk) AS high_risk_count,
                                       count(1) FILTER (WHERE is_incident_building) AS incident_count
                                FROM case_building
                                WHERE case_id = c.case_id
                            ) impact ON true
                            LEFT JOIN LATERAL (
                                SELECT count(1) AS total_count,
                                       count(1) FILTER (
                                           WHERE status IN (
                                               'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                                               'ON_HOLD', 'FAILED'
                                           )
                                       ) AS open_count
                                FROM work_item
                                WHERE case_id = c.case_id
                            ) work ON true
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
            signals = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT event.signal_event_id, event.source, event.external_id,
                                   event.event_type, event.event_subtype, event.severity,
                                   event.source_status, event.title, event.summary,
                                   event.source_published_at, event.effective_at, event.expires_at,
                                   event.address, event.region_codes, event.region_names,
                                   event.location_precision, event.is_relevant,
                                   event.relevance_reason, event.version, event.updated_at,
                                   link.link_type, link.is_automated, link.rule_version,
                                   link.decision_reason, link.linked_at
                            FROM case_signal_link link
                            JOIN signal_event event
                              ON event.signal_event_id = link.signal_event_id
                            WHERE link.case_id = :case_id
                            ORDER BY coalesce(
                                event.source_published_at, event.created_at
                            ) DESC, event.signal_event_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
            relations = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT relation.case_relation_id,
                                   relation.source_case_id, source_case.case_number AS source_number,
                                   relation.target_case_id, target_case.case_number AS target_number,
                                   relation.relation_type, relation.evidence,
                                   relation.created_at, relation.resolved_at
                            FROM case_relation relation
                            JOIN case_record source_case
                              ON source_case.case_id = relation.source_case_id
                            JOIN case_record target_case
                              ON target_case.case_id = relation.target_case_id
                            WHERE relation.source_case_id = :case_id
                               OR relation.target_case_id = :case_id
                            ORDER BY relation.created_at DESC, relation.case_relation_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .all()
            )
        return {
            **_case_item(
                {
                    **dict(row),
                    "sources": sorted({str(item["source"]) for item in signals}),
                    "signal_count": len(signals),
                    "relation_candidate_count": sum(
                        item["relation_type"] == "POSSIBLE_SAME_EVENT"
                        and item["resolved_at"] is None
                        for item in relations
                    ),
                }
            ),
            "normalizedAddress": row["normalized_address"],
            "location": _geojson(row["location_geojson"]),
            "closeReason": row["close_reason"],
            "closedAt": _iso(row["closed_at"]),
            "impactScope": (
                {
                    "impactScopeId": str(row["impact_scope_id"]),
                    "scopeType": row["scope_type"],
                    "center": _geojson(row["scope_center_geojson"]),
                    "radiusM": row["radius_m"],
                    "regionCodes": list(row["scope_region_codes"] or []),
                    "precisionWarning": row["precision_warning"],
                    "ruleVersion": row["impact_rule_version"],
                    "calculatedAt": _iso(row["impact_calculated_at"]),
                }
                if row["impact_scope_id"] is not None
                else None
            ),
            "workItemCount": int(row["work_item_count"]),
            "signals": [
                {
                    "signalEventId": str(signal["signal_event_id"]),
                    "source": signal["source"],
                    "externalId": signal["external_id"],
                    "eventType": signal["event_type"],
                    "eventSubtype": signal["event_subtype"],
                    "severity": signal["severity"],
                    "sourceStatus": signal["source_status"],
                    "title": signal["title"],
                    "summary": signal["summary"],
                    "sourcePublishedAt": _iso(signal["source_published_at"]),
                    "effectiveAt": _iso(signal["effective_at"]),
                    "expiresAt": _iso(signal["expires_at"]),
                    "address": signal["address"],
                    "regionCodes": list(signal["region_codes"] or []),
                    "regionNames": list(signal["region_names"] or []),
                    "locationPrecision": signal["location_precision"],
                    "isRelevant": bool(signal["is_relevant"]),
                    "relevanceReason": signal["relevance_reason"],
                    "version": int(signal["version"]),
                    "updatedAt": _iso(signal["updated_at"]),
                    "linkType": signal["link_type"],
                    "isAutomatedLink": bool(signal["is_automated"]),
                    "linkRuleVersion": signal["rule_version"],
                    "linkDecisionReason": signal["decision_reason"],
                    "linkedAt": _iso(signal["linked_at"]),
                }
                for signal in signals
            ],
            "relations": [
                {
                    "caseRelationId": str(relation["case_relation_id"]),
                    "sourceCaseId": str(relation["source_case_id"]),
                    "sourceCaseNumber": relation["source_number"],
                    "targetCaseId": str(relation["target_case_id"]),
                    "targetCaseNumber": relation["target_number"],
                    "relationType": relation["relation_type"],
                    "evidence": relation["evidence"],
                    "createdAt": _iso(relation["created_at"]),
                    "resolvedAt": _iso(relation["resolved_at"]),
                }
                for relation in relations
            ],
            "riskReference": {
                "referenceMonth": "2026-03",
                "horizonDays": 60,
                "lineageVersion": RISK_LINEAGE_VERSION,
                "isProbability": False,
            },
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def case_timeline(
    engine: AsyncEngine,
    case_id: UUID,
    *,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    params = {
        "case_id": case_id,
        "case_id_text": str(case_id),
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    timeline_cte = """
        WITH linked_identity AS (
            SELECT DISTINCT event.source, event.external_id
            FROM case_signal_link link
            JOIN signal_event event
              ON event.signal_event_id = link.signal_event_id
            WHERE link.case_id = :case_id
        ),
        timeline AS (
            SELECT raw.fetched_at AS occurred_at,
                   'SIGNAL_RAW'::varchar AS entry_type,
                   raw.raw_signal_id::text AS entry_id,
                   raw.source::text AS category,
                   ('원천 신호 수신 · ' || raw.source)::text AS title,
                   jsonb_build_object(
                       'externalId', raw.external_id,
                       'payloadSha256', raw.payload_sha256,
                       'parserVersion', raw.parser_version,
                       'sourcePublishedAt', raw.source_published_at,
                       'isSimulated', raw.is_simulated
                   ) AS detail
            FROM linked_identity identity
            JOIN raw_signal raw
              ON raw.source = identity.source
             AND raw.external_id = identity.external_id
            UNION ALL
            SELECT audit.occurred_at,
                   'AUDIT'::varchar,
                   audit.audit_event_id::text,
                   audit.action::text,
                   audit.action::text,
                   jsonb_build_object(
                       'actorType', audit.actor_type,
                       'targetType', audit.target_type,
                       'targetVersion', audit.target_version,
                       'reason', audit.reason,
                       'metadata', audit.metadata
                   )
            FROM audit_event audit
            WHERE (
                audit.target_type = 'case_record'
                AND audit.target_id = :case_id_text
            ) OR audit.correlation_id IN (
                SELECT automation_run_id
                FROM automation_run
                WHERE case_id = :case_id
            )
            UNION ALL
            SELECT work.updated_at,
                   'WORK_ITEM'::varchar,
                   work.work_item_id::text,
                   work.work_type::text,
                   work.title::text,
                   jsonb_build_object(
                       'status', work.status,
                       'priority', work.priority,
                       'progress', work.progress,
                       'errorClass', work.error_class
                   )
            FROM work_item work
            WHERE work.case_id = :case_id
        )
    """

    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            exists = (
                await connection.execute(
                    text("SELECT 1 FROM case_record WHERE case_id = :case_id"),
                    {"case_id": case_id},
                )
            ).scalar_one_or_none()
            if exists is None:
                return None
            total = int(
                (
                    await connection.execute(
                        text(f"{timeline_cte} SELECT count(1) FROM timeline"),
                        params,
                    )
                ).scalar_one()
            )
            rows = (
                (
                    await connection.execute(
                        text(
                            f"""
                            {timeline_cte}
                            SELECT occurred_at, entry_type, entry_id, category, title, detail
                            FROM timeline
                            ORDER BY occurred_at DESC, entry_type, entry_id
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
        return {
            "items": [
                {
                    "occurredAt": _iso(row["occurred_at"]),
                    "entryType": row["entry_type"],
                    "entryId": row["entry_id"],
                    "category": row["category"],
                    "title": row["title"],
                    "detail": row["detail"],
                }
                for row in rows
            ],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.0))


async def case_impact_buildings(
    engine: AsyncEngine,
    case_id: UUID,
    *,
    page: int,
    page_size: int,
    risk_threshold: int | None,
    incident_only: bool,
    search: str | None,
    sort: str,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if risk_threshold is not None and risk_threshold not in (1, 5, 10, 25):
        raise CaseContractError(
            422,
            "INVALID_RISK_THRESHOLD",
            "위험도 필터는 상위 1%·5%·10%·25% 중에서 선택해 주세요.",
        )
    order_by = {
        "priority": "case_building.priority_order, case_building.building_id",
        "risk": "risk.final_score DESC, case_building.building_id",
        "distance": "case_building.distance_m ASC NULLS LAST, case_building.building_id",
        "name": (
            "coalesce(nullif(building.building_name, ''), "
            "building.road_address, building.lot_address), case_building.building_id"
        ),
    }.get(sort)
    if order_by is None:
        raise CaseContractError(
            422, "INVALID_IMPACT_SORT", "영향 건물 정렬값이 올바르지 않습니다."
        )
    normalized_search = search.strip() if search and search.strip() else None
    params = {
        "case_id": case_id,
        "risk_threshold": risk_threshold,
        "incident_only": incident_only,
        "search": f"%{normalized_search}%" if normalized_search else None,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters = """
        case_building.case_id = :case_id
        AND (
            CAST(:risk_threshold AS integer) IS NULL
            OR case_building.is_incident_building
            OR risk.top_percentile <= CAST(:risk_threshold AS integer)
        )
        AND (NOT :incident_only OR case_building.is_incident_building)
        AND (
            CAST(:search AS varchar) IS NULL
            OR coalesce(building.building_name, '') ILIKE CAST(:search AS varchar)
            OR coalesce(building.road_address, '') ILIKE CAST(:search AS varchar)
            OR building.lot_address ILIKE CAST(:search AS varchar)
            OR building.source_building_key ILIKE CAST(:search AS varchar)
        )
    """

    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            case_exists = (
                await connection.execute(
                    text("SELECT 1 FROM case_record WHERE case_id = :case_id"),
                    {"case_id": case_id},
                )
            ).scalar_one_or_none()
            if case_exists is None:
                return None
            totals = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT count(1) AS impact_count,
                                   count(1) FILTER (WHERE is_high_risk) AS high_risk_count,
                                   count(1) FILTER (WHERE is_incident_building) AS incident_count
                            FROM case_building
                            WHERE case_id = :case_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one()
            )
            filtered_total = int(
                (
                    await connection.execute(
                        text(
                            f"""
                            SELECT count(1)
                            FROM case_building
                            JOIN building
                              ON building.building_id = case_building.building_id
                            JOIN building_risk_snapshot risk
                              ON risk.risk_snapshot_id = case_building.risk_snapshot_id
                            WHERE {filters}
                            """
                        ),
                        params,
                    )
                ).scalar_one()
            )
            rows = (
                (
                    await connection.execute(
                        text(
                            f"""
                            SELECT case_building.building_id,
                                   case_building.match_reason,
                                   case_building.distance_m,
                                   case_building.is_incident_building,
                                   case_building.is_high_risk,
                                   case_building.priority_order,
                                   case_building.rule_version,
                                   case_building.calculated_at,
                                   building.source_building_key,
                                   building.region_code,
                                   building.road_address,
                                   building.lot_address,
                                   building.building_name,
                                   ST_X(building.centroid) AS longitude,
                                   ST_Y(building.centroid) AS latitude,
                                   risk.final_score,
                                   risk.regional_rank,
                                   risk.top_percentile,
                                   risk.risk_band,
                                   risk.lineage_version
                            FROM case_building
                            JOIN building
                              ON building.building_id = case_building.building_id
                            JOIN building_risk_snapshot risk
                              ON risk.risk_snapshot_id = case_building.risk_snapshot_id
                            WHERE {filters}
                            ORDER BY {order_by}
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            scope = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT impact_scope_id, scope_type, radius_m, region_codes,
                                   precision_warning, rule_version, calculated_at
                            FROM case_impact_scope
                            WHERE case_id = :case_id
                            ORDER BY calculated_at DESC, impact_scope_id DESC
                            LIMIT 1
                            """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return {
            "summary": {
                "impactBuildings": int(totals["impact_count"]),
                "highRiskBuildings": int(totals["high_risk_count"]),
                "incidentBuildings": int(totals["incident_count"]),
            },
            "scope": (
                {
                    "impactScopeId": str(scope["impact_scope_id"]),
                    "scopeType": scope["scope_type"],
                    "radiusM": scope["radius_m"],
                    "regionCodes": list(scope["region_codes"] or []),
                    "precisionWarning": scope["precision_warning"],
                    "ruleVersion": scope["rule_version"],
                    "calculatedAt": _iso(scope["calculated_at"]),
                }
                if scope is not None
                else None
            ),
            "items": [
                {
                    "buildingId": str(row["building_id"]),
                    "sourceBuildingKey": row["source_building_key"],
                    "regionCode": row["region_code"],
                    "name": row["building_name"] or "건물명 미등록",
                    "roadAddress": row["road_address"],
                    "lotAddress": row["lot_address"],
                    "centroid": [float(row["longitude"]), float(row["latitude"])],
                    "matchReason": row["match_reason"],
                    "distanceM": (
                        round(float(row["distance_m"]), 1)
                        if row["distance_m"] is not None
                        else None
                    ),
                    "isIncidentBuilding": bool(row["is_incident_building"]),
                    "isHighRisk": bool(row["is_high_risk"]),
                    "priorityOrder": int(row["priority_order"]),
                    "risk": {
                        "referenceMonth": "2026-03",
                        "horizonDays": 60,
                        "finalScore": float(row["final_score"]),
                        "regionalRank": int(row["regional_rank"]),
                        "topPercentile": float(row["top_percentile"]),
                        "riskBand": row["risk_band"],
                        "lineageVersion": row["lineage_version"],
                        "isProbability": False,
                    },
                    "ruleVersion": row["rule_version"],
                    "calculatedAt": _iso(row["calculated_at"]),
                }
                for row in rows
            ],
            "filters": {
                "riskThreshold": risk_threshold,
                "incidentOnly": incident_only,
                "search": normalized_search,
                "sort": sort,
            },
            "page": page,
            "pageSize": page_size,
            "total": filtered_total,
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))
