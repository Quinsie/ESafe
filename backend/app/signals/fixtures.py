import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import PurePosixPath
from uuid import UUID

from app.signals.adapters import (
    DISASTER_LICENSE_NOTE,
    KMA_LICENSE_NOTE,
    NFDS_LICENSE_NOTE,
    FetchedDocument,
    SourceBatch,
    SourceRecord,
)
from app.signals.contracts import SignalSource
from app.signals.disaster_message import parse_disaster_messages
from app.signals.kma import parse_kma_warning
from app.signals.nfds import nfds_records, parse_nfds

DEFAULT_SCENARIO_ID = UUID("8da9f96c-a255-5ed8-a6a9-6d80783f7261")
_BASELINE_FILES = {
    SignalSource.NFDS: "nfds_baseline.json",
    SignalSource.KMA_WARNING: "kma_baseline.json",
    SignalSource.DISASTER_MESSAGE: "disaster_message_baseline.html",
}


def _read(name: str) -> str:
    safe = PurePosixPath(name)
    if safe.name != name or safe.suffix not in {".json", ".html"}:
        raise ValueError("invalid fixture file name")
    return files("app.demo.fixtures").joinpath(name).read_text(encoding="utf-8")


def _document(
    fixture_name: str,
    payload_format: str,
    body: str,
    scenario_id: UUID,
    source_time: datetime | None,
) -> FetchedDocument:
    return FetchedDocument(
        label=PurePosixPath(fixture_name).stem,
        payload_format=payload_format,
        body=body,
        content_type="application/json" if payload_format == "JSON" else "text/html",
        fetched_at=datetime.now(UTC),
        request_metadata={
            "fixture": fixture_name,
            "scenarioId": str(scenario_id),
            "sourceTime": source_time.isoformat() if source_time is not None else None,
            "replayedAt": datetime.now(UTC).isoformat(),
        },
    )


def load_named_fixture_batch(
    source: SignalSource,
    fixture_name: str,
    scenario_id: UUID,
    source_time: datetime | None = None,
) -> SourceBatch:
    body = _read(fixture_name)
    if source is SignalSource.NFDS:
        payload = json.loads(body)
        original = {str(item.get("sidoOvrNum", "")): item for item in nfds_records(payload)}
        records = tuple(
            SourceRecord(signal, dict(original[signal.external_id]), 0)
            for signal in parse_nfds(payload)
        )
        return SourceBatch(
            source,
            (_document(fixture_name, "JSON", body, scenario_id, source_time),),
            records,
            NFDS_LICENSE_NOTE,
        )
    if source is SignalSource.KMA_WARNING:
        payload = json.loads(body)
        pairs = payload.get("announcements")
        if not isinstance(pairs, list):
            raise ValueError("KMA fixture announcements must be an array")
        records_list: list[SourceRecord] = []
        for pair in pairs:
            if not isinstance(pair, dict):
                raise ValueError("KMA fixture announcement must be an object")
            list_item = pair.get("listItem")
            detail_item = pair.get("detailItem")
            if not isinstance(list_item, dict) or not isinstance(detail_item, dict):
                raise ValueError("KMA fixture must include listItem and detailItem")
            signal = parse_kma_warning(list_item, detail_item)
            records_list.append(SourceRecord(signal, pair, 0))
        return SourceBatch(
            source,
            (_document(fixture_name, "JSON", body, scenario_id, source_time),),
            tuple(records_list),
            KMA_LICENSE_NOTE,
        )
    records = tuple(
        SourceRecord(
            signal,
            {
                "externalId": signal.external_id,
                "message": signal.title,
                "sourcePublishedAt": (
                    signal.source_published_at.isoformat()
                    if signal.source_published_at is not None
                    else None
                ),
            },
            0,
        )
        for signal in parse_disaster_messages(body)
    )
    return SourceBatch(
        source,
        (_document(fixture_name, "HTML", body, scenario_id, source_time),),
        records,
        DISASTER_LICENSE_NOTE,
    )


def load_fixture_batch(source: SignalSource) -> tuple[SourceBatch, UUID]:
    return (
        load_named_fixture_batch(
            source,
            _BASELINE_FILES[source],
            DEFAULT_SCENARIO_ID,
        ),
        DEFAULT_SCENARIO_ID,
    )
