import re
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from lxml import etree, html

from app.signals.contracts import (
    CanonicalSignal,
    EventType,
    PayloadSchemaError,
    SignalSource,
    SourceStatus,
    normalize_space,
)
from app.signals.kma import _affected_regions

PARSER_VERSION: Final = "safetydata-message-v1"
KST: Final = ZoneInfo("Asia/Seoul")
_HAZARD_KEYWORDS: Final = (
    "화재",
    "산불",
    "호우",
    "폭염",
    "강풍",
    "풍랑",
    "대설",
    "한파",
    "태풍",
    "침수",
    "붕괴",
    "정전",
    "감전",
    "누전",
    "대피",
)
_TIME_PATTERN: Final = re.compile(r"20\d{2}[-./]\d{2}[-./]\d{2}\s+\d{2}:\d{2}(?::\d{2})?")
_ID_PATTERN: Final = re.compile(r"(?:sn|seq|no|id)[^0-9]{0,8}(\d+)", re.IGNORECASE)


def _published_at(text: str) -> datetime | None:
    match = _TIME_PATTERN.search(text)
    if not match:
        return None
    normalized = match.group(0).replace(".", "-").replace("/", "-")
    format_string = "%Y-%m-%d %H:%M:%S" if normalized.count(":") == 2 else "%Y-%m-%d %H:%M"
    try:
        return datetime.strptime(normalized, format_string).replace(tzinfo=KST)
    except ValueError:
        return None


def _event_id(row: html.HtmlElement, cells: list[str]) -> str:
    attributes = " ".join(
        value
        for element in row.iterdescendants()
        for value in (element.get("href"), element.get("onclick"), element.get("data-sn"))
        if value
    )
    match = _ID_PATTERN.search(attributes)
    if match:
        return match.group(1)
    if cells and cells[0].isdigit():
        return cells[0]
    raise PayloadSchemaError("disaster message row is missing its public sequence identifier")


def parse_disaster_messages(payload: bytes | str) -> list[CanonicalSignal]:
    if isinstance(payload, bytes):
        try:
            source = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise PayloadSchemaError("disaster message page is not valid UTF-8") from error
    else:
        source = payload
    try:
        document = html.fromstring(source)
    except (etree.ParserError, ValueError, TypeError) as error:
        raise PayloadSchemaError("disaster message page is not valid HTML") from error
    if not document.xpath("//table"):
        raise PayloadSchemaError("disaster message page no longer contains the expected table")

    signals: list[CanonicalSignal] = []
    for row in document.xpath("//table//tr[td]"):
        cells = [normalize_space(" ".join(cell.itertext())) for cell in row.xpath("./td")]
        if not cells:
            continue
        event_id = _event_id(row, cells)
        candidates = [
            cell for cell in cells if not cell.isdigit() and not _TIME_PATTERN.fullmatch(cell)
        ]
        if not candidates:
            raise PayloadSchemaError(f"disaster message {event_id} has no message body")
        message = max(candidates, key=len)
        region_codes, region_names = _affected_regions(message)
        hazard = next((word for word in _HAZARD_KEYWORDS if word in message), None)
        is_relevant = bool(region_codes and hazard)
        reasons: list[str] = []
        reasons.append("GWANGJU_JEONNAM_REGION" if region_codes else "OUT_OF_SCOPE_REGION")
        reasons.append("SUPPORTED_HAZARD" if hazard else "UNSUPPORTED_MESSAGE")
        signals.append(
            CanonicalSignal(
                source=SignalSource.DISASTER_MESSAGE,
                external_id=event_id,
                event_type=EventType.DISASTER_MESSAGE,
                event_subtype=hazard,
                severity=None,
                source_status=SourceStatus.ACTIVE,
                title=message,
                summary=None,
                source_published_at=_published_at(" ".join(cells)),
                effective_at=_published_at(" ".join(cells)),
                expires_at=None,
                address=None,
                region_codes=region_codes,
                region_names=region_names,
                longitude=None,
                latitude=None,
                location_precision="SIDO" if region_codes else None,
                is_relevant=is_relevant,
                relevance_reasons=tuple(reasons),
            )
        )
    return signals
