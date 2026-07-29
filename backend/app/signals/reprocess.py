import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.signals.contracts import CanonicalSignal, PayloadSchemaError
from app.signals.kma import PARSER_VERSION, parse_kma_warning

PREVIOUS_KMA_PARSER_VERSION = "kma-warning-v1"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_stored_kma_payload(payload: object) -> CanonicalSignal:
    if not isinstance(payload, Mapping):
        raise PayloadSchemaError("Stored KMA raw payload is not an object")
    list_item = payload.get("listItem")
    detail_item = payload.get("detailItem")
    if not isinstance(list_item, Mapping) or not isinstance(detail_item, Mapping):
        raise PayloadSchemaError("Stored KMA raw payload lacks listItem or detailItem")
    return parse_kma_warning(list_item, detail_item)


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _signal_state(signal: CanonicalSignal) -> dict[str, object]:
    return {
        "eventType": signal.event_type.value,
        "eventSubtype": signal.event_subtype,
        "severity": signal.severity,
        "sourceStatus": signal.source_status.value,
        "title": signal.title,
        "summary": signal.summary,
        "sourcePublishedAt": _iso(signal.source_published_at),
        "effectiveAt": _iso(signal.effective_at),
        "expiresAt": _iso(signal.expires_at),
        "address": signal.address,
        "regionCodes": list(signal.region_codes),
        "regionNames": list(signal.region_names),
        "locationPrecision": signal.location_precision,
        "isRelevant": signal.is_relevant,
        "relevanceReason": {"reasons": list(signal.relevance_reasons)},
    }


def _stored_state(row: RowMapping) -> dict[str, object]:
    return {
        "eventType": row["event_type"],
        "eventSubtype": row["event_subtype"],
        "severity": row["severity"],
        "sourceStatus": row["source_status"],
        "title": row["title"],
        "summary": row["summary"],
        "sourcePublishedAt": _iso(row["source_published_at"]),
        "effectiveAt": _iso(row["effective_at"]),
        "expiresAt": _iso(row["expires_at"]),
        "address": row["address"],
        "regionCodes": list(row["region_codes"]),
        "regionNames": list(row["region_names"]),
        "locationPrecision": row["location_precision"],
        "isRelevant": row["is_relevant"],
        "relevanceReason": row["relevance_reason"],
    }


async def reprocess_kma_events(settings: Settings) -> dict[str, object]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        return await _reprocess_kma_events(engine, settings.profile)
    finally:
        await engine.dispose()


async def _reprocess_kma_events(
    engine: AsyncEngine,
    profile: str,
) -> dict[str, object]:
    started_at = datetime.now().astimezone()
    run_id = uuid4()
    run_key = f"reprocess:{profile}:KMA_WARNING:{PARSER_VERSION}"
    output_hashes: list[str] = []
    scanned = updated = relevant = 0
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": run_key},
        )
        existing = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT status, metadata
                    FROM automation_run
                    WHERE idempotency_key = :run_key
                    """
                    ),
                    {"run_key": run_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            return {
                "status": "SKIPPED",
                "parserVersion": PARSER_VERSION,
                "reason": "ALREADY_APPLIED",
                "previousRunStatus": existing["status"],
            }

        rows = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT e.signal_event_id, e.event_type, e.event_subtype,
                           e.severity, e.source_status, e.title, e.summary,
                           e.source_published_at, e.effective_at, e.expires_at,
                           e.address, e.region_codes, e.region_names,
                           e.location_precision, e.is_relevant, e.relevance_reason,
                           e.version, r.payload_json, r.payload_sha256
                    FROM signal_event e
                    JOIN raw_signal r
                      ON r.raw_signal_id = e.latest_raw_signal_id
                    WHERE e.source = 'KMA_WARNING'
                    ORDER BY e.signal_event_id
                    FOR UPDATE OF e
                    """
                    )
                )
            )
            .mappings()
            .all()
        )

        for row in rows:
            scanned += 1
            signal = parse_stored_kma_payload(row["payload_json"])
            before_state = _stored_state(row)
            after_state = _signal_state(signal)
            after_hash = _sha256(_json(after_state))
            output_hashes.append(after_hash)
            relevant += signal.is_relevant
            if before_state == after_state:
                continue

            updated += 1
            next_version = int(row["version"]) + 1
            await connection.execute(
                text(
                    """
                    UPDATE signal_event
                    SET event_type = :event_type,
                        event_subtype = :event_subtype,
                        severity = :severity,
                        source_status = :source_status,
                        title = :title,
                        summary = :summary,
                        source_published_at = :source_published_at,
                        effective_at = :effective_at,
                        expires_at = :expires_at,
                        address = :address,
                        region_codes = CAST(:region_codes AS varchar(10)[]),
                        region_names = CAST(:region_names AS text[]),
                        location = NULL,
                        location_precision = :location_precision,
                        is_relevant = :is_relevant,
                        relevance_reason = CAST(:relevance_reason AS jsonb),
                        version = :next_version,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE signal_event_id = :signal_event_id
                    """
                ),
                {
                    "event_type": signal.event_type.value,
                    "event_subtype": signal.event_subtype,
                    "severity": signal.severity,
                    "source_status": signal.source_status.value,
                    "title": signal.title,
                    "summary": signal.summary,
                    "source_published_at": signal.source_published_at,
                    "effective_at": signal.effective_at,
                    "expires_at": signal.expires_at,
                    "address": signal.address,
                    "region_codes": list(signal.region_codes),
                    "region_names": list(signal.region_names),
                    "location_precision": signal.location_precision,
                    "is_relevant": signal.is_relevant,
                    "relevance_reason": _json(after_state["relevanceReason"]),
                    "next_version": next_version,
                    "signal_event_id": row["signal_event_id"],
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO audit_event (
                        audit_event_id, profile, actor_type, action, target_type,
                        target_id, target_version, before_state, after_state,
                        reason, correlation_id, idempotency_key,
                        input_sha256, output_sha256, metadata
                    )
                    VALUES (
                        :audit_id, :profile, 'SYSTEM', 'SIGNAL_REPROCESSED',
                        'signal_event', :target_id, :target_version,
                        CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                        CAST(:reason AS jsonb), :correlation_id, :idempotency_key,
                        :input_sha256, :output_sha256, CAST(:metadata AS jsonb)
                    )
                    """
                ),
                {
                    "audit_id": uuid4(),
                    "profile": profile,
                    "target_id": str(row["signal_event_id"]),
                    "target_version": next_version,
                    "before_state": _json(before_state),
                    "after_state": _json(after_state),
                    "reason": _json({"reasonCode": "KMA_SCOPE_RULE_CORRECTION"}),
                    "correlation_id": run_id,
                    "idempotency_key": (
                        f"audit:reprocess:{profile}:{PARSER_VERSION}:{row['signal_event_id']}"
                    ),
                    "input_sha256": row["payload_sha256"],
                    "output_sha256": after_hash,
                    "metadata": _json(
                        {
                            "fromParserVersion": PREVIOUS_KMA_PARSER_VERSION,
                            "toParserVersion": PARSER_VERSION,
                        }
                    ),
                },
            )

        aggregate_hash = _sha256("|".join(output_hashes))
        finished_at = datetime.now().astimezone()
        metadata = {
            "scanned": scanned,
            "updated": updated,
            "unchanged": scanned - updated,
            "relevant": relevant,
        }
        await connection.execute(
            text(
                """
                INSERT INTO automation_run (
                    automation_run_id, profile, run_type, trigger_type, status,
                    source, input_version, output_version, rule_version,
                    idempotency_key, started_at, finished_at, metadata
                )
                VALUES (
                    :run_id, :profile, 'SIGNAL_REPROCESS', 'USER', 'SUCCEEDED',
                    'KMA_WARNING', :input_version, :output_version, :rule_version,
                    :run_key, :started_at, :finished_at, CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "run_id": run_id,
                "profile": profile,
                "input_version": PREVIOUS_KMA_PARSER_VERSION,
                "output_version": aggregate_hash,
                "rule_version": PARSER_VERSION,
                "run_key": run_key,
                "started_at": started_at,
                "finished_at": finished_at,
                "metadata": _json(metadata),
            },
        )
        await connection.execute(
            text(
                """
                UPDATE source_health
                SET parser_version = :parser_version, updated_at = CURRENT_TIMESTAMP
                WHERE source = 'KMA_WARNING'
                """
            ),
            {"parser_version": PARSER_VERSION},
        )
        await connection.execute(
            text(
                """
                UPDATE source_checkpoint
                SET parser_version = :parser_version, updated_at = CURRENT_TIMESTAMP
                WHERE source = 'KMA_WARNING'
                """
            ),
            {"parser_version": PARSER_VERSION},
        )
    return {
        "status": "SUCCEEDED",
        "parserVersion": PARSER_VERSION,
        "scanned": scanned,
        "updated": updated,
        "unchanged": scanned - updated,
        "relevant": relevant,
    }
