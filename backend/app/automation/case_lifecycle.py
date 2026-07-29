# ruff: noqa: E501
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.automation.case_rules import (
    CASE_RULE_VERSION,
    CaseStatus,
    case_type_for,
    initial_case_status,
    next_case_status,
)
from app.automation.impact import ImpactResult, rebuild_case_impact
from app.signals.contracts import EventType, SignalSource, SourceStatus

KST: Final = ZoneInfo("Asia/Seoul")
_KMA_UPDATE_TOKENS: Final = (
    "change",
    "cancel",
    "replace",
    "expand",
    "reduce",
    "upgrade",
    "downgrade",
    "lift",
)
_KMA_UPDATE_TOKENS_KO: Final = (
    "변경",
    "해제",
    "대치",
    "확대",
    "축소",
    "상향",
    "하향",
    "전환",
)
_FIRE_TOKENS: Final = (
    "화재",
    "산불",
    "폭발",
    "정전",
    "감전",
    "누전",
    "전기",
    "전력",
    "변압기",
    "송전",
    "배전",
)


@dataclass(frozen=True, slots=True)
class CaseLifecycleResult:
    case_id: UUID
    case_number: str
    outcome: str
    link_type: str
    impact: ImpactResult


def is_kma_lifecycle_update(title: str, summary: str | None) -> bool:
    combined = f"{title} {summary or ''}".casefold()
    return any(token in combined for token in _KMA_UPDATE_TOKENS) or any(
        token in combined for token in _KMA_UPDATE_TOKENS_KO
    )


def case_number_prefix(profile: str) -> str:
    if profile == "LIVE":
        return "ES"
    if profile == "DEMO":
        return "DEMO"
    raise ValueError(f"unsupported profile: {profile}")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _event_time(signal: dict[str, Any]) -> datetime:
    value = signal["effective_at"] or signal["source_published_at"] or signal["updated_at"]
    if not isinstance(value, datetime):
        raise TypeError("signal event time must be a datetime")
    return value


def _is_fire_family(signal: dict[str, Any]) -> bool:
    if signal["event_type"] == EventType.FIRE_DISPATCH.value:
        return True
    subtype = str(signal["event_subtype"] or "")
    return any(token in subtype for token in _FIRE_TOKENS)


def _is_weather_family(signal: dict[str, Any]) -> bool:
    return signal["event_type"] == EventType.WEATHER_WARNING.value or not _is_fire_family(
        signal
    )


def _priority(signal: dict[str, Any], aggregate_status: SourceStatus) -> str:
    if aggregate_status is SourceStatus.RESOLVED:
        return "ATTENTION"
    if _is_fire_family(signal) or signal["severity"] == "WARNING":
        return "URGENT"
    return "ATTENTION"


async def _load_signal(connection: AsyncConnection, signal_event_id: UUID) -> dict[str, Any]:
    row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT signal_event_id, source, external_id, event_type, event_subtype,
                           severity, source_status, title, summary, source_published_at,
                           effective_at, region_codes, region_names, location,
                           location_precision, normalized_address, is_relevant,
                           is_simulated, scenario_id, version, updated_at
                    FROM signal_event
                    WHERE signal_event_id = :signal_event_id
                    FOR UPDATE
                    """
                ),
                {"signal_event_id": signal_event_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"signal event does not exist: {signal_event_id}")
    return dict(row)


async def allocate_case_number(
    connection: AsyncConnection,
    profile: str,
    opened_at: datetime,
) -> str:
    business_date: date = opened_at.astimezone(KST).date()
    value = (
        await connection.execute(
            text(
                """
                INSERT INTO case_number_counter (business_date, last_value)
                VALUES (:business_date, 1)
                ON CONFLICT (business_date) DO UPDATE
                SET last_value = case_number_counter.last_value + 1,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING last_value
                """
            ),
            {"business_date": business_date},
        )
    ).scalar_one()
    return f"{case_number_prefix(profile)}-{business_date:%Y%m%d}-{int(value):06d}"


async def _known_primary_region(
    connection: AsyncConnection,
    region_codes: tuple[str, ...],
) -> str | None:
    if not region_codes:
        return None
    value = (
        await connection.execute(
            text(
                """
                SELECT requested.code
                FROM unnest(CAST(:region_codes AS varchar(10)[]))
                     WITH ORDINALITY AS requested(code, ordinal)
                JOIN admin_region region ON region.region_code = requested.code
                ORDER BY requested.ordinal
                LIMIT 1
                """
            ),
            {"region_codes": list(region_codes)},
        )
    ).scalar_one_or_none()
    return str(value) if value is not None else None


async def _owner_case(
    connection: AsyncConnection,
    signal_event_id: UUID,
) -> tuple[UUID, str] | None:
    row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT link.case_id, link.link_type
                    FROM case_signal_link link
                    WHERE link.signal_event_id = :signal_event_id
                      AND link.link_type IN ('PRIMARY', 'UPDATE', 'MERGED_SOURCE')
                    FOR UPDATE
                    """
                ),
                {"signal_event_id": signal_event_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return UUID(str(row["case_id"])), str(row["link_type"])


async def _weather_candidates(
    connection: AsyncConnection,
    signal: dict[str, Any],
) -> list[UUID]:
    rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT DISTINCT c.case_id
                    FROM case_record c
                    JOIN case_signal_link link ON link.case_id = c.case_id
                    JOIN signal_event linked ON linked.signal_event_id = link.signal_event_id
                    WHERE c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                      AND linked.event_subtype = :event_subtype
                      AND linked.region_codes && CAST(:region_codes AS varchar(10)[])
                      AND (
                          c.source_resolved_at IS NULL
                          OR :event_time <= c.source_resolved_at + INTERVAL '6 hours'
                      )
                    ORDER BY c.case_id
                    """
                ),
                {
                    "event_subtype": signal["event_subtype"],
                    "region_codes": list(signal["region_codes"] or []),
                    "event_time": _event_time(signal),
                },
            )
        )
        .scalars()
        .all()
    )
    return [UUID(str(value)) for value in rows]


async def _strict_fire_candidates(
    connection: AsyncConnection,
    signal: dict[str, Any],
) -> list[UUID]:
    rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT DISTINCT c.case_id
                    FROM case_record c
                    JOIN case_signal_link link ON link.case_id = c.case_id
                    JOIN signal_event linked ON linked.signal_event_id = link.signal_event_id
                    JOIN signal_event current
                      ON current.signal_event_id = :signal_event_id
                    WHERE c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                      AND (
                          linked.event_type = 'FIRE_DISPATCH'
                          OR linked.event_subtype ~ '(화재|산불|폭발|정전|감전|누전|전기|전력|변압기|송전|배전)'
                      )
                      AND abs(extract(epoch FROM (
                          coalesce(linked.effective_at, linked.source_published_at, linked.updated_at)
                          - :event_time
                      ))) <= 7200
                      AND (
                          (
                              current.normalized_address IS NOT NULL
                              AND linked.normalized_address = current.normalized_address
                          )
                          OR (
                              current.location IS NOT NULL
                              AND linked.location IS NOT NULL
                              AND ST_DWithin(
                                  linked.location::geography,
                                  current.location::geography,
                                  500
                              )
                          )
                      )
                    ORDER BY c.case_id
                    """
                ),
                {
                    "event_time": _event_time(signal),
                    "signal_event_id": signal["signal_event_id"],
                },
            )
        )
        .scalars()
        .all()
    )
    return [UUID(str(value)) for value in rows]


async def _loose_fire_candidates(
    connection: AsyncConnection,
    signal: dict[str, Any],
) -> list[UUID]:
    rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT DISTINCT c.case_id
                    FROM case_record c
                    JOIN case_signal_link link ON link.case_id = c.case_id
                    JOIN signal_event linked ON linked.signal_event_id = link.signal_event_id
                    WHERE c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                      AND (
                          linked.event_type = 'FIRE_DISPATCH'
                          OR linked.event_subtype ~ '(화재|산불|폭발|정전|감전|누전|전기|전력|변압기|송전|배전)'
                      )
                      AND abs(extract(epoch FROM (
                          coalesce(linked.effective_at, linked.source_published_at, linked.updated_at)
                          - :event_time
                      ))) <= 7200
                      AND linked.region_codes && CAST(:region_codes AS varchar(10)[])
                    ORDER BY c.case_id
                    """
                ),
                {
                    "event_time": _event_time(signal),
                    "region_codes": list(signal["region_codes"] or []),
                },
            )
        )
        .scalars()
        .all()
    )
    return [UUID(str(value)) for value in rows]


async def _candidate_cases(
    connection: AsyncConnection,
    signal: dict[str, Any],
) -> tuple[list[UUID], list[UUID]]:
    source = SignalSource(str(signal["source"]))
    if source is SignalSource.KMA_WARNING:
        is_update = signal["source_status"] == SourceStatus.RESOLVED.value or (
            is_kma_lifecycle_update(str(signal["title"]), None)
        )
        if not is_update:
            return [], []
    if _is_weather_family(signal):
        candidates = await _weather_candidates(connection, signal)
        return candidates, candidates
    strict = await _strict_fire_candidates(connection, signal)
    loose = await _loose_fire_candidates(connection, signal)
    return strict, loose


async def _create_case(
    connection: AsyncConnection,
    profile: str,
    signal: dict[str, Any],
    now: datetime,
) -> tuple[UUID, str]:
    case_id = uuid4()
    case_number = await allocate_case_number(connection, profile, now)
    source_status = SourceStatus(str(signal["source_status"]))
    status = initial_case_status(source_status)
    await connection.execute(
        text(
            """
            INSERT INTO case_record (
                case_id, case_number, case_type, title, status, source_status,
                monitoring_priority, primary_region_code, location,
                normalized_address, location_precision, opened_at, updated_at,
                source_resolved_at, is_simulated, scenario_id
            )
            VALUES (
                :case_id, :case_number, :case_type, :title, :status, :source_status,
                :monitoring_priority, :primary_region_code, :location,
                :normalized_address, :location_precision, :opened_at, :updated_at,
                :source_resolved_at, :is_simulated, :scenario_id
            )
            """
        ),
        {
            "case_id": case_id,
            "case_number": case_number,
            "case_type": case_type_for(EventType(str(signal["event_type"]))).value,
            "title": signal["title"],
            "status": status.value,
            "source_status": source_status.value,
            "monitoring_priority": _priority(signal, source_status),
            "primary_region_code": await _known_primary_region(
                connection,
                tuple(signal["region_codes"] or ()),
            ),
            "location": signal["location"],
            "normalized_address": signal["normalized_address"],
            "location_precision": signal["location_precision"],
            "opened_at": now,
            "updated_at": now,
            "source_resolved_at": now if source_status is SourceStatus.RESOLVED else None,
            "is_simulated": bool(signal["is_simulated"]),
            "scenario_id": signal["scenario_id"],
        },
    )
    return case_id, case_number


async def _link_signal(
    connection: AsyncConnection,
    case_id: UUID,
    signal: dict[str, Any],
    link_type: str,
    reason: dict[str, Any],
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO case_signal_link (
                case_id, signal_event_id, link_type, is_automated,
                rule_version, decision_reason
            )
            VALUES (
                :case_id, :signal_event_id, :link_type, true,
                :rule_version, CAST(:decision_reason AS jsonb)
            )
            ON CONFLICT (case_id, signal_event_id) DO UPDATE
            SET decision_reason = EXCLUDED.decision_reason,
                rule_version = EXCLUDED.rule_version
            """
        ),
        {
            "case_id": case_id,
            "signal_event_id": signal["signal_event_id"],
            "link_type": link_type,
            "rule_version": CASE_RULE_VERSION,
            "decision_reason": _json(reason),
        },
    )


async def _refresh_case(
    connection: AsyncConnection,
    case_id: UUID,
    signal: dict[str, Any],
    now: datetime,
) -> tuple[str, int]:
    current = (
        (
            await connection.execute(
                text(
                    """
                    SELECT case_number, status, version
                    FROM case_record
                    WHERE case_id = :case_id
                    FOR UPDATE
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one()
    )
    aggregate = (
        (
            await connection.execute(
                text(
                    """
                    WITH latest_by_source AS (
                        SELECT DISTINCT ON (event.source)
                               event.source, event.source_status
                        FROM case_signal_link link
                        JOIN signal_event event
                          ON event.signal_event_id = link.signal_event_id
                        WHERE link.case_id = :case_id
                          AND link.link_type IN ('PRIMARY', 'UPDATE', 'MERGED_SOURCE')
                        ORDER BY event.source,
                                 coalesce(
                                     event.effective_at,
                                     event.source_published_at,
                                     event.updated_at
                                 ) DESC,
                                 event.version DESC,
                                 event.updated_at DESC
                    )
                    SELECT bool_or(source_status <> 'RESOLVED') AS has_active
                    FROM latest_by_source
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one()
    )
    aggregate_status = SourceStatus.ACTIVE if bool(aggregate["has_active"]) else SourceStatus.RESOLVED
    next_status = next_case_status(CaseStatus(str(current["status"])), aggregate_status)
    await connection.execute(
        text(
            """
            UPDATE case_record
            SET title = :title,
                status = :status,
                source_status = :source_status,
                monitoring_priority = :monitoring_priority,
                primary_region_code = coalesce(primary_region_code, :primary_region_code),
                location = coalesce(:location, location),
                normalized_address = coalesce(:normalized_address, normalized_address),
                location_precision = coalesce(:location_precision, location_precision),
                source_resolved_at = CASE
                    WHEN CAST(:source_status AS varchar) = 'RESOLVED'
                    THEN coalesce(source_resolved_at, :now)
                    ELSE NULL
                END,
                updated_at = :now,
                version = version + 1
            WHERE case_id = :case_id
            """
        ),
        {
            "case_id": case_id,
            "title": signal["title"],
            "status": next_status.value,
            "source_status": aggregate_status.value,
            "monitoring_priority": _priority(signal, aggregate_status),
            "primary_region_code": await _known_primary_region(
                connection,
                tuple(signal["region_codes"] or ()),
            ),
            "location": signal["location"],
            "normalized_address": signal["normalized_address"],
            "location_precision": signal["location_precision"],
            "now": now,
        },
    )
    return str(current["case_number"]), int(current["version"]) + 1


async def _create_relations(
    connection: AsyncConnection,
    new_case_id: UUID,
    candidate_ids: list[UUID],
    signal: dict[str, Any],
) -> None:
    for candidate_id in sorted(set(candidate_ids), key=str):
        if candidate_id == new_case_id:
            continue
        await connection.execute(
            text(
                """
                INSERT INTO case_relation (
                    case_relation_id, source_case_id, target_case_id,
                    relation_type, evidence
                )
                VALUES (
                    :relation_id, :source_case_id, :target_case_id,
                    'POSSIBLE_SAME_EVENT', CAST(:evidence AS jsonb)
                )
                ON CONFLICT (source_case_id, target_case_id, relation_type) DO NOTHING
                """
            ),
            {
                "relation_id": uuid4(),
                "source_case_id": new_case_id,
                "target_case_id": candidate_id,
                "evidence": _json(
                    {
                        "ruleVersion": CASE_RULE_VERSION,
                        "reason": "AMBIGUOUS_OR_LOCATION_INSUFFICIENT",
                        "signalEventId": str(signal["signal_event_id"]),
                    }
                ),
            },
        )


async def _audit_lifecycle(
    connection: AsyncConnection,
    *,
    profile: str,
    correlation_id: UUID,
    signal: dict[str, Any],
    case_id: UUID,
    case_number: str,
    case_version: int,
    action: str,
    link_type: str,
    impact: ImpactResult,
) -> None:
    after_state = {
        "caseNumber": case_number,
        "signalEventId": str(signal["signal_event_id"]),
        "signalVersion": int(signal["version"]),
        "linkType": link_type,
        "impactBuildingCount": impact.building_count,
        "highRiskBuildingCount": impact.high_risk_count,
        "precisionWarning": impact.precision_warning,
    }
    idempotency_suffix = f"{signal['signal_event_id']}:{signal['version']}"
    await connection.execute(
        text(
            """
            INSERT INTO automation_run (
                automation_run_id, profile, run_type, trigger_type, status,
                source, case_id, input_version, output_version, rule_version,
                idempotency_key, started_at, finished_at, metadata
            )
            VALUES (
                :run_id, :profile, 'CASE_LIFECYCLE', 'EVENT', 'SUCCEEDED',
                :source, :case_id, :input_version, :output_version, :rule_version,
                :run_key, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CAST(:metadata AS jsonb)
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        {
            "run_id": uuid4(),
            "profile": profile,
            "source": signal["source"],
            "case_id": case_id,
            "input_version": idempotency_suffix,
            "output_version": _sha256(after_state),
            "rule_version": CASE_RULE_VERSION,
            "run_key": f"case-lifecycle:{idempotency_suffix}",
            "metadata": _json(after_state),
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO audit_event (
                audit_event_id, profile, actor_type, action, target_type,
                target_id, target_version, after_state, reason,
                correlation_id, idempotency_key, output_sha256, metadata
            )
            VALUES (
                :audit_id, :profile, 'SYSTEM', :action, 'case_record',
                :target_id, :target_version, CAST(:after_state AS jsonb),
                CAST(:reason AS jsonb), :correlation_id, :audit_key,
                :output_sha256, CAST(:metadata AS jsonb)
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        {
            "audit_id": uuid4(),
            "profile": profile,
            "action": action,
            "target_id": str(case_id),
            "target_version": case_version,
            "after_state": _json(after_state),
            "reason": _json({"ruleVersion": CASE_RULE_VERSION}),
            "correlation_id": correlation_id,
            "audit_key": f"audit:case-lifecycle:{idempotency_suffix}",
            "output_sha256": _sha256(after_state),
            "metadata": _json({"source": signal["source"]}),
        },
    )


async def apply_signal_to_case(
    connection: AsyncConnection,
    *,
    profile: str,
    signal_event_id: UUID,
    correlation_id: UUID,
) -> CaseLifecycleResult | None:
    signal = await _load_signal(connection, signal_event_id)
    if not bool(signal["is_relevant"]):
        return None

    owner = await _owner_case(connection, signal_event_id)
    created = False
    candidate_count = 0
    if owner is not None:
        case_id, link_type = owner
    else:
        strict_candidates, relation_candidates = await _candidate_cases(connection, signal)
        candidate_count = len(strict_candidates)
        if len(strict_candidates) == 1:
            case_id = strict_candidates[0]
            existing_source = (
                await connection.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM case_signal_link link
                            JOIN signal_event event ON event.signal_event_id = link.signal_event_id
                            WHERE link.case_id = :case_id AND event.source = :source
                        )
                        """
                    ),
                    {"case_id": case_id, "source": signal["source"]},
                )
            ).scalar_one()
            link_type = "UPDATE" if bool(existing_source) else "MERGED_SOURCE"
        else:
            now = datetime.now(UTC)
            case_id, _ = await _create_case(connection, profile, signal, now)
            link_type = "PRIMARY"
            created = True
            await _create_relations(
                connection,
                case_id,
                strict_candidates or relation_candidates,
                signal,
            )
        await _link_signal(
            connection,
            case_id,
            signal,
            link_type,
            {
                "candidateCount": candidate_count,
                "source": signal["source"],
                "ruleVersion": CASE_RULE_VERSION,
            },
        )

    now = datetime.now(UTC)
    case_number, case_version = await _refresh_case(connection, case_id, signal, now)
    impact = await rebuild_case_impact(connection, case_id)
    await _audit_lifecycle(
        connection,
        profile=profile,
        correlation_id=correlation_id,
        signal=signal,
        case_id=case_id,
        case_number=case_number,
        case_version=case_version,
        action="CASE_CREATED" if created else "CASE_SIGNAL_APPLIED",
        link_type=link_type,
        impact=impact,
    )
    return CaseLifecycleResult(
        case_id=case_id,
        case_number=case_number,
        outcome="CREATED" if created else "UPDATED",
        link_type=link_type,
        impact=impact,
    )
