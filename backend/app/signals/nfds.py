import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from app.signals.contracts import (
    CanonicalSignal,
    EventType,
    PayloadSchemaError,
    SignalSource,
    SourceStatus,
    normalize_space,
)

PARSER_VERSION: Final = "nfds-json-v1"
KST: Final = ZoneInfo("Asia/Seoul")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PayloadSchemaError("NFDS defail item is not an object")
    return {str(key): item for key, item in value.items()}


def _value(fields: Mapping[str, object], *names: str) -> str:
    lowered = {key.lower(): value for key, value in fields.items()}
    for name in names:
        value = normalize_space(lowered.get(name.lower()))
        if value:
            return value
    return ""


def _parse_payload(payload: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(payload, Mapping):
        return {str(key): value for key, value in payload.items()}
    try:
        decoded = (
            payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else payload
        )
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PayloadSchemaError("NFDS payload is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PayloadSchemaError("NFDS payload root is not an object")
    return {str(key): item for key, item in value.items()}


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    compact = "".join(character for character in value if character.isdigit())
    for format_string, length in (
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d%H%M", 12),
        ("%Y%m%d", 8),
    ):
        if len(compact) >= length:
            try:
                return datetime.strptime(compact[:length], format_string).replace(tzinfo=KST)
            except ValueError:
                continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or KST)


def _coordinate(value: str, lower: float, upper: float) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if lower <= result <= upper else None


def _region(fields: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    code = _value(fields, "lawSidoCd", "sidoCd")
    name = _value(fields, "sidoNm", "sidoName")
    if code.startswith("29") or "광주" in name:
        return ("29",), ("광주광역시",)
    if code.startswith("46") or "전남" in name or "전라남도" in name:
        return ("46",), ("전라남도",)
    return (), ()


def _external_id(fields: Mapping[str, object]) -> str:
    supplied = _value(fields, "sidoOvrNum", "sidoOvrNo", "overNum", "eventId")
    if supplied:
        return supplied
    stable = "|".join(
        _value(fields, name)
        for name in ("addr", "overDate", "frfalTypeCd", "lawSidoCd", "lawGunguCd")
    )
    if not stable.strip("|"):
        raise PayloadSchemaError("NFDS record has neither an event identifier nor stable fields")
    return f"derived-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:24]}"


def nfds_records(payload: bytes | str | Mapping[str, object]) -> list[dict[str, object]]:
    root = _parse_payload(payload)
    if "defail" not in root:
        raise PayloadSchemaError("NFDS payload is missing the expected defail field")
    records = root["defail"]
    if records is None:
        return []
    if isinstance(records, Mapping):
        return [_mapping(records)]
    if not isinstance(records, list):
        raise PayloadSchemaError("NFDS defail field is neither an array nor an object")
    return [_mapping(record) for record in records]


def parse_nfds(payload: bytes | str | Mapping[str, object]) -> list[CanonicalSignal]:
    parsed: list[CanonicalSignal] = []
    for fields in nfds_records(payload):
        address = _value(fields, "addr", "address")
        region_codes, region_names = _region(fields)
        progress = _value(fields, "progressNm", "progressStat")
        resolved = any(token in progress for token in ("종료", "완료", "해제"))
        longitude = _coordinate(_value(fields, "longitude", "lon", "markerX", "x"), 124, 132)
        latitude = _coordinate(_value(fields, "latitude", "lat", "markerY", "y"), 32, 39)
        if longitude is None or latitude is None:
            longitude = latitude = None
        event_id = _external_id(fields)
        event_kind = _value(fields, "frfalTypeCd", "frfalTypeNm") or "화재 출동"
        published_at = _parse_time(_value(fields, "overDate", "occurDate", "regDate"))
        title = normalize_space(f"{region_names[0] if region_names else '관할 외'} {event_kind}")
        location_precision = (
            "COORDINATE" if longitude is not None else ("EUPMYEONDONG" if address else "SIDO")
        )
        relevance_reasons = (
            ("GWANGJU_JEONNAM_REGION",) if region_codes else ("OUT_OF_SCOPE_REGION",)
        )
        parsed.append(
            CanonicalSignal(
                source=SignalSource.NFDS,
                external_id=event_id,
                event_type=EventType.FIRE_DISPATCH,
                event_subtype=event_kind,
                severity=None,
                source_status=SourceStatus.RESOLVED if resolved else SourceStatus.ACTIVE,
                title=title,
                summary=progress or None,
                source_published_at=published_at,
                effective_at=published_at,
                expires_at=None,
                address=address or None,
                region_codes=region_codes,
                region_names=region_names,
                longitude=longitude,
                latitude=latitude,
                location_precision=location_precision,
                is_relevant=bool(region_codes),
                relevance_reasons=relevance_reasons,
            )
        )
    return parsed
