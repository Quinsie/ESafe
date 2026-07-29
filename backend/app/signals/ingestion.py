import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings
from app.signals.adapters import (
    SourceBatch,
    SourceRequestError,
    fetch_disaster_messages,
    fetch_kma_warnings,
    fetch_nfds,
)
from app.signals.contracts import (
    CanonicalSignal,
    PayloadSchemaError,
    SignalSource,
    normalize_address,
)
from app.signals.disaster_message import PARSER_VERSION as DISASTER_PARSER_VERSION
from app.signals.fixtures import load_fixture_batch
from app.signals.kma import PARSER_VERSION as KMA_PARSER_VERSION
from app.signals.nfds import PARSER_VERSION as NFDS_PARSER_VERSION

PARSER_VERSIONS = {
    SignalSource.NFDS: NFDS_PARSER_VERSION,
    SignalSource.KMA_WARNING: KMA_PARSER_VERSION,
    SignalSource.DISASTER_MESSAGE: DISASTER_PARSER_VERSION,
}
CONTRACT_VERSION = "canonical-signal-v1"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _signal_payload(signal: CanonicalSignal) -> dict[str, object]:
    return {
        "source": signal.source.value,
        "externalId": signal.external_id,
        "eventType": signal.event_type.value,
        "eventSubtype": signal.event_subtype,
        "severity": signal.severity,
        "sourceStatus": signal.source_status.value,
        "title": signal.title,
        "summary": signal.summary,
        "sourcePublishedAt": (
            signal.source_published_at.isoformat()
            if signal.source_published_at is not None
            else None
        ),
        "effectiveAt": signal.effective_at.isoformat() if signal.effective_at else None,
        "expiresAt": signal.expires_at.isoformat() if signal.expires_at else None,
        "address": signal.address,
        "regionCodes": list(signal.region_codes),
        "regionNames": list(signal.region_names),
        "longitude": signal.longitude,
        "latitude": signal.latitude,
        "locationPrecision": signal.location_precision,
        "isRelevant": signal.is_relevant,
        "relevanceReasons": list(signal.relevance_reasons),
    }


async def _begin_poll(
    engine: AsyncEngine,
    settings: Settings,
    source: SignalSource,
    idempotency_key_override: str | None = None,
) -> tuple[UUID, frozenset[str]] | None:
    now = datetime.now(UTC)
    bucket = int(now.timestamp()) // 600
    poll_id = uuid4()
    idempotency_key = idempotency_key_override or (f"{settings.profile}:{source.value}:{bucket}")
    async with engine.begin() as connection:
        health = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT enabled, backoff_until
                    FROM source_health
                    WHERE source = :source
                    FOR UPDATE
                    """
                    ),
                    {"source": source.value},
                )
            )
            .mappings()
            .one_or_none()
        )
        if health is None:
            raise RuntimeError(f"source_health is not seeded for {source.value}")
        if not bool(health["enabled"]):
            return None
        if health["backoff_until"] is not None and health["backoff_until"] > now:
            return None
        inserted = (
            await connection.execute(
                text(
                    """
                    INSERT INTO source_poll (
                        poll_id, source, execution_mode, result, started_at,
                        parser_version, idempotency_key
                    )
                    VALUES (
                        :poll_id, :source, :execution_mode, 'RUNNING', :started_at,
                        :parser_version, :idempotency_key
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING poll_id
                    """
                ),
                {
                    "poll_id": poll_id,
                    "source": source.value,
                    "execution_mode": "EXTERNAL" if settings.profile == "LIVE" else "FIXTURE",
                    "started_at": now,
                    "parser_version": PARSER_VERSIONS[source],
                    "idempotency_key": idempotency_key,
                },
            )
        ).scalar_one_or_none()
        if inserted is None:
            return None
        known = (
            (
                await connection.execute(
                    text("SELECT external_id FROM signal_event WHERE source = :source"),
                    {"source": source.value},
                )
            )
            .scalars()
            .all()
        )
        await connection.execute(
            text(
                """
                UPDATE source_health
                SET last_attempt_at = :now, updated_at = :now
                WHERE source = :source
                """
            ),
            {"source": source.value, "now": now},
        )
    return poll_id, frozenset(str(value) for value in known)


async def _fetch_batch(
    settings: Settings,
    source: SignalSource,
    known_external_ids: frozenset[str],
    client: httpx.AsyncClient | None,
) -> tuple[SourceBatch, UUID | None]:
    if settings.profile == "DEMO":
        return load_fixture_batch(source)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=settings.signal_http_timeout_seconds,
        follow_redirects=True,
    )
    try:
        if source is SignalSource.NFDS:
            if not settings.nfds_enabled:
                raise RuntimeError("NFDS poll was invoked while NFDS_ENABLED is false")
            batch = await fetch_nfds(settings, active_client)
        elif source is SignalSource.KMA_WARNING:
            batch = await fetch_kma_warnings(settings, active_client, known_external_ids)
        else:
            batch = await fetch_disaster_messages(settings, active_client)
        return batch, None
    finally:
        if owns_client:
            await active_client.aclose()


async def _store_document(
    connection: AsyncConnection,
    poll_id: UUID,
    source: SignalSource,
    document: Any,
) -> UUID:
    response_id = uuid4()
    body_hash = _sha256(document.body)
    payload_json = None
    payload_text = None
    if document.payload_format == "JSON":
        try:
            payload_json = _json(json.loads(document.body))
        except json.JSONDecodeError:
            payload_text = document.body
    if payload_json is None and payload_text is None:
        payload_json = None
        payload_text = document.body
    await connection.execute(
        text(
            """
            INSERT INTO source_response (
                source_response_id, poll_id, source, response_label,
                payload_format, payload_sha256, payload_json, payload_text,
                content_type, request_metadata, fetched_at
            )
            VALUES (
                :response_id, :poll_id, :source, :label,
                :payload_format, :payload_sha256, CAST(:payload_json AS jsonb), :payload_text,
                :content_type, CAST(:request_metadata AS jsonb), :fetched_at
            )
            """
        ),
        {
            "response_id": response_id,
            "poll_id": poll_id,
            "source": source.value,
            "label": document.label,
            "payload_format": document.payload_format,
            "payload_sha256": body_hash,
            "payload_json": payload_json,
            "payload_text": payload_text,
            "content_type": document.content_type,
            "request_metadata": _json(document.request_metadata),
            "fetched_at": document.fetched_at,
        },
    )
    return response_id


async def _store_record(
    connection: AsyncConnection,
    poll_id: UUID,
    response_id: UUID,
    record: Any,
    license_note: str,
    scenario_id: UUID | None,
) -> str:
    signal: CanonicalSignal = record.signal
    raw_json = _json(record.raw_payload)
    raw_hash = _sha256(raw_json)
    raw_id = (
        await connection.execute(
            text(
                """
                INSERT INTO raw_signal (
                    raw_signal_id, poll_id, source_response_id, source, external_id,
                    payload_format, payload_sha256, payload_json,
                    source_published_at, fetched_at, parser_version, license_note,
                    is_simulated, scenario_id
                )
                VALUES (
                    :raw_id, :poll_id, :response_id, :source, :external_id,
                    'JSON', :payload_sha256, CAST(:payload_json AS jsonb),
                    :source_published_at, CURRENT_TIMESTAMP, :parser_version, :license_note,
                    :is_simulated, :scenario_id
                )
                ON CONFLICT (source, external_id, payload_sha256) DO NOTHING
                RETURNING raw_signal_id
                """
            ),
            {
                "raw_id": uuid4(),
                "poll_id": poll_id,
                "response_id": response_id,
                "source": signal.source.value,
                "external_id": signal.external_id,
                "payload_sha256": raw_hash,
                "payload_json": raw_json,
                "source_published_at": signal.source_published_at,
                "parser_version": PARSER_VERSIONS[signal.source],
                "license_note": license_note,
                "is_simulated": scenario_id is not None,
                "scenario_id": scenario_id,
            },
        )
    ).scalar_one_or_none()
    if raw_id is None:
        raw_id = (
            await connection.execute(
                text(
                    """
                    SELECT raw_signal_id
                    FROM raw_signal
                    WHERE source = :source
                      AND external_id = :external_id
                      AND payload_sha256 = :payload_sha256
                    """
                ),
                {
                    "source": signal.source.value,
                    "external_id": signal.external_id,
                    "payload_sha256": raw_hash,
                },
            )
        ).scalar_one()
    signal_id = uuid4()
    changed = (
        await connection.execute(
            text(
                """
                INSERT INTO signal_event (
                    signal_event_id, source, external_id, event_type, event_subtype,
                    severity, source_status, title, summary, source_published_at,
                    effective_at, expires_at, address, normalized_address,
                    region_codes, region_names, location, location_precision,
                    latest_raw_signal_id, is_relevant, relevance_reason, is_simulated, scenario_id
                )
                VALUES (
                    :signal_id, :source, :external_id, :event_type, :event_subtype,
                    :severity, :source_status, :title, :summary, :source_published_at,
                    :effective_at, :expires_at, :address, :normalized_address,
                    CAST(:region_codes AS varchar(10)[]), CAST(:region_names AS text[]),
                    CASE WHEN CAST(:longitude AS double precision) IS NULL THEN NULL
                         ELSE ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) END,
                    :location_precision, :raw_id, :is_relevant,
                    CAST(:relevance_reason AS jsonb), :is_simulated, :scenario_id
                )
                ON CONFLICT (source, external_id) DO UPDATE
                SET event_type = EXCLUDED.event_type,
                    event_subtype = EXCLUDED.event_subtype,
                    severity = EXCLUDED.severity,
                    source_status = EXCLUDED.source_status,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    source_published_at = EXCLUDED.source_published_at,
                    effective_at = EXCLUDED.effective_at,
                    expires_at = EXCLUDED.expires_at,
                    address = EXCLUDED.address,
                    normalized_address = EXCLUDED.normalized_address,
                    region_codes = EXCLUDED.region_codes,
                    region_names = EXCLUDED.region_names,
                    location = EXCLUDED.location,
                    location_precision = EXCLUDED.location_precision,
                    latest_raw_signal_id = EXCLUDED.latest_raw_signal_id,
                    is_relevant = EXCLUDED.is_relevant,
                    relevance_reason = EXCLUDED.relevance_reason,
                    version = signal_event.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE signal_event.latest_raw_signal_id
                  IS DISTINCT FROM EXCLUDED.latest_raw_signal_id
                RETURNING (xmax = 0) AS inserted
                """
            ),
            {
                "signal_id": signal_id,
                "source": signal.source.value,
                "external_id": signal.external_id,
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
                "normalized_address": normalize_address(signal.address),
                "region_codes": list(signal.region_codes),
                "region_names": list(signal.region_names),
                "longitude": signal.longitude,
                "latitude": signal.latitude,
                "location_precision": signal.location_precision,
                "raw_id": raw_id,
                "is_relevant": signal.is_relevant,
                "relevance_reason": _json({"reasons": signal.relevance_reasons}),
                "is_simulated": scenario_id is not None,
                "scenario_id": scenario_id,
            },
        )
    ).scalar_one_or_none()
    if changed is None:
        return "UNCHANGED"
    return "INSERTED" if bool(changed) else "UPDATED"


async def _store_success(
    engine: AsyncEngine,
    settings: Settings,
    poll_id: UUID,
    batch: SourceBatch,
    scenario_id: UUID | None,
    *,
    run_type: str = "SIGNAL_POLL",
    trigger_type: str = "SCHEDULED",
    audit_action: str = "SIGNAL_POLL_COMPLETED",
    reason_code: str | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC)
    response_hashes = [_sha256(document.body) for document in batch.documents]
    aggregate_hash = _sha256("|".join(response_hashes))
    inserted = updated = unchanged = 0
    async with engine.begin() as connection:
        response_ids = [
            await _store_document(connection, poll_id, batch.source, document)
            for document in batch.documents
        ]
        for record in batch.records:
            outcome = await _store_record(
                connection,
                poll_id,
                response_ids[record.document_index],
                record,
                batch.license_note,
                scenario_id,
            )
            inserted += outcome == "INSERTED"
            updated += outcome == "UPDATED"
            unchanged += outcome == "UNCHANGED"
        result = "EMPTY" if not batch.records else "SUCCESS"
        await connection.execute(
            text(
                """
                UPDATE source_poll
                SET result = :result, finished_at = :now, http_status = 200,
                    received_count = :received_count, new_count = :new_count,
                    updated_count = :updated_count, response_sha256 = :response_sha256,
                    next_allowed_at = :next_poll_at
                WHERE poll_id = :poll_id
                """
            ),
            {
                "result": result,
                "now": now,
                "received_count": len(batch.records),
                "new_count": inserted,
                "updated_count": updated,
                "response_sha256": aggregate_hash,
                "next_poll_at": now + timedelta(minutes=10),
                "poll_id": poll_id,
            },
        )
        latest_ids = [record.signal.external_id for record in batch.records[:50]]
        await connection.execute(
            text(
                """
                INSERT INTO source_checkpoint (
                    source, cursor_value, cursor_metadata, last_poll_id,
                    last_success_at, consecutive_failures, backoff_until,
                    parser_version, contract_version, updated_at
                )
                VALUES (
                    :source, :cursor_value, CAST(:cursor_metadata AS jsonb), :poll_id,
                    :now, 0, NULL, :parser_version, :contract_version, :now
                )
                ON CONFLICT (source) DO UPDATE
                SET cursor_value = EXCLUDED.cursor_value,
                    cursor_metadata = EXCLUDED.cursor_metadata,
                    last_poll_id = EXCLUDED.last_poll_id,
                    last_success_at = EXCLUDED.last_success_at,
                    consecutive_failures = 0,
                    backoff_until = NULL,
                    parser_version = EXCLUDED.parser_version,
                    contract_version = EXCLUDED.contract_version,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "source": batch.source.value,
                "cursor_value": latest_ids[0] if latest_ids else None,
                "cursor_metadata": _json({"latestExternalIds": latest_ids}),
                "poll_id": poll_id,
                "now": now,
                "parser_version": PARSER_VERSIONS[batch.source],
                "contract_version": CONTRACT_VERSION,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE source_health
                SET status = 'HEALTHY', last_success_at = :now,
                    consecutive_failures = 0, next_poll_at = :next_poll_at,
                    backoff_until = NULL, last_http_status = 200,
                    last_error_code = NULL, parser_version = :parser_version,
                    contract_version = :contract_version, updated_at = :now
                WHERE source = :source
                """
            ),
            {
                "now": now,
                "next_poll_at": now + timedelta(minutes=10),
                "parser_version": PARSER_VERSIONS[batch.source],
                "contract_version": CONTRACT_VERSION,
                "source": batch.source.value,
            },
        )
        run_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO automation_run (
                    automation_run_id, profile, run_type, trigger_type, status,
                    source, input_version, output_version, rule_version,
                    idempotency_key, started_at, finished_at, metadata
                )
                SELECT :run_id, :profile, :run_type, :trigger_type, 'SUCCEEDED',
                       source, response_sha256, :output_version, :rule_version,
                       'poll:' || poll_id::text, started_at, finished_at,
                       CAST(:metadata AS jsonb)
                FROM source_poll WHERE poll_id = :poll_id
                """
            ),
            {
                "run_id": run_id,
                "profile": settings.profile,
                "run_type": run_type,
                "trigger_type": trigger_type,
                "output_version": aggregate_hash,
                "rule_version": CONTRACT_VERSION,
                "metadata": _json(
                    {
                        "received": len(batch.records),
                        "inserted": inserted,
                        "updated": updated,
                        "unchanged": unchanged,
                        "reasonCode": reason_code,
                    }
                ),
                "poll_id": poll_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, action, target_type,
                    target_id, reason, correlation_id, idempotency_key,
                    output_sha256, metadata
                )
                VALUES (
                    :audit_id, :profile, 'SYSTEM', :audit_action,
                    'source_poll', :target_id, CAST(:reason AS jsonb),
                    :correlation_id, :idempotency_key, :output_sha256,
                    CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "audit_id": uuid4(),
                "profile": settings.profile,
                "audit_action": audit_action,
                "target_id": str(poll_id),
                "reason": _json(
                    {
                        "source": batch.source.value,
                        "reasonCode": reason_code,
                    }
                ),
                "correlation_id": poll_id,
                "idempotency_key": f"audit:poll:{poll_id}",
                "output_sha256": aggregate_hash,
                "metadata": _json({"result": result}),
            },
        )
    return {
        "status": result,
        "source": batch.source.value,
        "received": len(batch.records),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def _backoff(failure_count: int, blocked: bool, schema_error: bool) -> timedelta | None:
    if blocked:
        return None
    if schema_error:
        return timedelta(minutes=80)
    minutes = (20, 40, 80)[min(max(failure_count - 1, 0), 2)]
    return timedelta(minutes=minutes)


async def _store_failure(
    engine: AsyncEngine,
    settings: Settings,
    source: SignalSource,
    poll_id: UUID,
    error: Exception,
    *,
    run_type: str = "SIGNAL_POLL",
    trigger_type: str = "SCHEDULED",
    reason_code: str | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC)
    status_code = error.status_code if isinstance(error, SourceRequestError) else None
    error_class = (
        error.error_class if isinstance(error, SourceRequestError) else type(error).__name__.upper()
    )
    blocked = status_code in (403, 429)
    documents = getattr(error, "documents", ())
    schema_error = isinstance(error, PayloadSchemaError)
    async with engine.begin() as connection:
        current_failures = (
            await connection.execute(
                text(
                    """
                    SELECT consecutive_failures
                    FROM source_health
                    WHERE source = :source FOR UPDATE
                    """
                ),
                {"source": source.value},
            )
        ).scalar_one()
        failure_count = int(current_failures) + 1
        delay = _backoff(failure_count, blocked, schema_error)
        backoff_until = (
            datetime.max.replace(tzinfo=UTC) if blocked else now + (delay or timedelta())
        )
        response_hashes = []
        for document in documents:
            await _store_document(connection, poll_id, source, document)
            response_hashes.append(_sha256(document.body))
        aggregate_hash = _sha256("|".join(response_hashes)) if response_hashes else None
        await connection.execute(
            text(
                """
                UPDATE source_poll
                SET result = 'FAILED', finished_at = :now, http_status = :http_status,
                    error_class = :error_class, next_allowed_at = :backoff_until,
                    response_sha256 = :response_sha256
                WHERE poll_id = :poll_id
                """
            ),
            {
                "now": now,
                "http_status": status_code,
                "error_class": error_class,
                "backoff_until": backoff_until,
                "poll_id": poll_id,
                "response_sha256": aggregate_hash,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE source_health
                SET status = 'OUTAGE', last_failure_at = :now,
                    consecutive_failures = :failure_count,
                    backoff_until = :backoff_until, next_poll_at = :backoff_until,
                    last_http_status = :http_status, last_error_code = :error_class,
                    parser_version = :parser_version,
                    contract_version = :contract_version, updated_at = :now
                WHERE source = :source
                """
            ),
            {
                "now": now,
                "failure_count": failure_count,
                "backoff_until": backoff_until,
                "http_status": status_code,
                "error_class": error_class,
                "parser_version": PARSER_VERSIONS[source],
                "contract_version": CONTRACT_VERSION,
                "source": source.value,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO automation_run (
                    automation_run_id, profile, run_type, trigger_type, status,
                    source, rule_version, retry_count, error_class,
                    idempotency_key, started_at, finished_at, metadata
                )
                SELECT :run_id, :profile, :run_type, :trigger_type, 'FAILED',
                       source, :rule_version, :retry_count, :error_class,
                       'poll:' || poll_id::text, started_at, finished_at,
                       CAST(:metadata AS jsonb)
                FROM source_poll WHERE poll_id = :poll_id
                """
            ),
            {
                "run_id": uuid4(),
                "profile": settings.profile,
                "run_type": run_type,
                "trigger_type": trigger_type,
                "rule_version": CONTRACT_VERSION,
                "retry_count": failure_count,
                "error_class": error_class,
                "metadata": _json(
                    {
                        "blocked": blocked,
                        "schemaError": schema_error,
                        "reasonCode": reason_code,
                    }
                ),
                "poll_id": poll_id,
            },
        )
    return {
        "status": "FAILED",
        "source": source.value,
        "errorClass": error_class,
        "httpStatus": status_code,
        "blocked": blocked,
    }


async def run_signal_poll(
    settings: Settings,
    source: SignalSource,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    if settings.profile == "LIVE" and source is SignalSource.NFDS and not settings.nfds_enabled:
        return {"status": "DISABLED", "source": source.value}
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        started = await _begin_poll(engine, settings, source)
        if started is None:
            return {"status": "SKIPPED", "source": source.value}
        poll_id, known_external_ids = started
        try:
            batch, scenario_id = await _fetch_batch(
                settings,
                source,
                known_external_ids,
                client,
            )
            return await _store_success(engine, settings, poll_id, batch, scenario_id)
        except Exception as error:
            if isinstance(error, (SourceRequestError, PayloadSchemaError, RuntimeError)):
                return await _store_failure(engine, settings, source, poll_id, error)
            raise
    finally:
        await engine.dispose()


async def run_kma_source_repair(
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    if settings.profile != "LIVE":
        raise RuntimeError("KMA source repair is available only in LIVE")
    source = SignalSource.KMA_WARNING
    repair_version = "message-window-v2"
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        started = await _begin_poll(
            engine,
            settings,
            source,
            idempotency_key_override=(f"{settings.profile}:{source.value}:repair:{repair_version}"),
        )
        if started is None:
            return {
                "status": "SKIPPED",
                "source": source.value,
                "reason": "ALREADY_APPLIED_OR_SOURCE_DELAYED",
            }
        poll_id, _ = started
        try:
            batch, scenario_id = await _fetch_batch(
                settings,
                source,
                frozenset(),
                client,
            )
            return await _store_success(
                engine,
                settings,
                poll_id,
                batch,
                scenario_id,
                run_type="SIGNAL_SOURCE_REPAIR",
                trigger_type="USER",
                audit_action="KMA_SOURCE_REPAIR_COMPLETED",
                reason_code="KMA_MESSAGE_WINDOW_CONTRACT_CORRECTION",
            )
        except Exception as error:
            if isinstance(error, (SourceRequestError, PayloadSchemaError, RuntimeError)):
                return await _store_failure(
                    engine,
                    settings,
                    source,
                    poll_id,
                    error,
                    run_type="SIGNAL_SOURCE_REPAIR",
                    trigger_type="USER",
                    reason_code="KMA_MESSAGE_WINDOW_CONTRACT_CORRECTION",
                )
            raise
    finally:
        await engine.dispose()
