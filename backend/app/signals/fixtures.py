import json
from datetime import UTC, datetime
from importlib.resources import files
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


def _read(name: str) -> str:
    return files("app.demo.fixtures").joinpath(name).read_text(encoding="utf-8")


def _document(label: str, payload_format: str, body: str) -> FetchedDocument:
    return FetchedDocument(
        label=label,
        payload_format=payload_format,
        body=body,
        content_type="application/json" if payload_format == "JSON" else "text/html",
        fetched_at=datetime.now(UTC),
        request_metadata={"fixture": label, "scenarioId": str(DEFAULT_SCENARIO_ID)},
    )


def load_fixture_batch(source: SignalSource) -> tuple[SourceBatch, UUID]:
    if source is SignalSource.NFDS:
        body = _read("nfds_baseline.json")
        payload = json.loads(body)
        original = {str(item.get("sidoOvrNum", "")): item for item in nfds_records(payload)}
        records = tuple(
            SourceRecord(signal, dict(original[signal.external_id]), 0)
            for signal in parse_nfds(payload)
        )
        batch = SourceBatch(
            source,
            (_document("nfds-baseline", "JSON", body),),
            records,
            NFDS_LICENSE_NOTE,
        )
    elif source is SignalSource.KMA_WARNING:
        body = _read("kma_baseline.json")
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
        batch = SourceBatch(
            source,
            (_document("kma-baseline", "JSON", body),),
            tuple(records_list),
            KMA_LICENSE_NOTE,
        )
    else:
        body = _read("disaster_message_baseline.html")
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
        batch = SourceBatch(
            source,
            (_document("disaster-message-baseline", "HTML", body),),
            records,
            DISASTER_LICENSE_NOTE,
        )
    return batch, DEFAULT_SCENARIO_ID
