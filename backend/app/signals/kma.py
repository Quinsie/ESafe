import re
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

PARSER_VERSION: Final = "kma-warning-v1"
KST: Final = ZoneInfo("Asia/Seoul")
_WARNING_TYPES: Final = (
    "호우",
    "폭염",
    "강풍",
    "풍랑",
    "대설",
    "한파",
    "건조",
    "태풍",
    "황사",
    "지진",
)


def _value(payload: Mapping[str, object], key: str) -> str:
    return normalize_space(payload.get(key))


def _parse_tm_fc(value: str) -> datetime | None:
    digits = "".join(character for character in value if character.isdigit())
    for format_string, length in (("%Y%m%d%H%M", 12), ("%Y%m%d%H", 10)):
        if len(digits) >= length:
            try:
                return datetime.strptime(digits[:length], format_string).replace(tzinfo=KST)
            except ValueError:
                continue
    return None


def _affected_regions(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    # KMA messages often contain “경기도(광주, …)”. Remove that group before
    # looking for an unqualified Gwangju so Gyeonggi Gwangju is never selected.
    without_gyeonggi = re.sub(r"경기도\s*\([^)]*\)", "", text)
    codes: list[str] = []
    names: list[str] = []
    mentions_gwangju = "광주광역시" in without_gyeonggi or re.search(
        r"(^|[\s,:()])광주($|[\s,:()])",
        without_gyeonggi,
    )
    if mentions_gwangju:
        codes.append("29")
        names.append("광주광역시")
    if "전라남도" in text or "전남" in text:
        codes.append("46")
        names.append("전라남도")
    return tuple(codes), tuple(names)


def _warning_type(text: str) -> str:
    return next((warning for warning in _WARNING_TYPES if warning in text), "기상특보")


def parse_kma_warning(
    list_item: Mapping[str, object],
    detail_item: Mapping[str, object] | None = None,
) -> CanonicalSignal:
    detail = detail_item or {}
    station_id = _value(list_item, "stnId")
    forecast_time = _value(list_item, "tmFc")
    sequence = _value(list_item, "tmSeq")
    title = _value(list_item, "title")
    if not station_id or not forecast_time or not sequence or not title:
        raise PayloadSchemaError("KMA warning list item is missing stnId, tmFc, tmSeq, or title")

    detail_text = " ".join(
        value for key in ("t1", "t2", "t3", "t6", "t7") if (value := _value(detail, key))
    )
    combined = normalize_space(f"{title} {detail_text}")
    region_codes, region_names = _affected_regions(combined)
    warning_type = _warning_type(combined)
    is_resolved = "해제" in combined and not any(
        token in combined for token in ("발효", "발령", "변경")
    )
    severity = "WARNING" if "경보" in combined else ("WATCH" if "주의보" in combined else None)
    published_at = _parse_tm_fc(forecast_time)
    return CanonicalSignal(
        source=SignalSource.KMA_WARNING,
        external_id=f"{station_id}:{forecast_time}:{sequence}",
        event_type=EventType.WEATHER_WARNING,
        event_subtype=warning_type,
        severity=severity,
        source_status=SourceStatus.RESOLVED if is_resolved else SourceStatus.ACTIVE,
        title=title,
        summary=detail_text or None,
        source_published_at=published_at,
        effective_at=published_at,
        expires_at=None,
        address=None,
        region_codes=region_codes,
        region_names=region_names,
        longitude=None,
        latitude=None,
        location_precision="SIDO" if region_codes else None,
        is_relevant=bool(region_codes),
        relevance_reasons=("GWANGJU_JEONNAM_REGION",) if region_codes else ("OUT_OF_SCOPE_REGION",),
    )
