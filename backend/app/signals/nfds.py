import hashlib
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from lxml import etree

from app.signals.contracts import (
    CanonicalSignal,
    EventType,
    PayloadSchemaError,
    SignalSource,
    SourceStatus,
    normalize_space,
)

PARSER_VERSION: Final = "nfds-v1"
KST: Final = ZoneInfo("Asia/Seoul")
_ROW_NAMES: Final = frozenset({"item", "row", "record", "list"})


def _local_name(element: etree._Element) -> str:
    return str(etree.QName(element).localname).lower()


def _fields(element: etree._Element) -> dict[str, str]:
    return {
        _local_name(child): normalize_space(child.text)
        for child in element
        if isinstance(child.tag, str)
    }


def _first(fields: dict[str, str], *names: str) -> str:
    for name in names:
        value = fields.get(name.lower(), "")
        if value:
            return value
    return ""


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


def _region(fields: dict[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    code = _first(fields, "lawSidoCd", "sidoCd")
    name = _first(fields, "sidoNm", "sidoName")
    if code.startswith("29") or "광주" in name:
        return ("29",), ("광주광역시",)
    if code.startswith("46") or "전남" in name or "전라남도" in name:
        return ("46",), ("전라남도",)
    return (), ()


def _external_id(fields: dict[str, str]) -> str:
    supplied = _first(fields, "sidoOvrNum", "sidoOvrNo", "overNum", "eventId")
    if supplied:
        return supplied
    stable = "|".join(
        _first(fields, name)
        for name in ("addr", "overDate", "frfalTypeCd", "lawSidoCd", "lawGunguCd")
    )
    if not stable.strip("|"):
        raise PayloadSchemaError("NFDS record has neither an event identifier nor stable fields")
    return f"derived-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:24]}"


def _records(root: etree._Element) -> list[etree._Element]:
    containers = [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and _local_name(element) == "defail"
    ]
    if not containers:
        raise PayloadSchemaError("NFDS payload is missing the expected defail container")
    records: list[etree._Element] = []
    for container in containers:
        rows = [
            child
            for child in container
            if isinstance(child.tag, str) and _local_name(child) in _ROW_NAMES
        ]
        if rows:
            records.extend(rows)
        elif any(_local_name(child) in {"addr", "sidoovrnum", "overdate"} for child in container):
            records.append(container)
    return records


def parse_nfds(payload: bytes | str) -> list[CanonicalSignal]:
    encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(encoded, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as error:
        raise PayloadSchemaError("NFDS payload is not valid XML") from error

    parsed: list[CanonicalSignal] = []
    for record in _records(root):
        fields = _fields(record)
        address = _first(fields, "addr", "address")
        region_codes, region_names = _region(fields)
        progress = _first(fields, "progressNm", "progressStat")
        resolved = any(token in progress for token in ("종료", "완료", "해제"))
        longitude = _coordinate(_first(fields, "longitude", "lon", "markerX", "x"), 124, 132)
        latitude = _coordinate(_first(fields, "latitude", "lat", "markerY", "y"), 32, 39)
        if longitude is None or latitude is None:
            longitude = latitude = None
        event_id = _external_id(fields)
        event_kind = _first(fields, "frfalTypeCd", "frfalTypeNm") or "화재 출동"
        published_at = _parse_time(_first(fields, "overDate", "occurDate", "regDate"))
        title = normalize_space(f"{region_names[0] if region_names else '관할 외'} {event_kind}")
        if longitude is not None:
            location_precision = "COORDINATE"
        else:
            location_precision = "EUPMYEONDONG" if address else "SIDO"
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
