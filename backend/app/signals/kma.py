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

PARSER_VERSION: Final = "kma-warning-v3"
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
_GWANGJU_SIGUNGU: Final = {
    "동구": ("29110", "광주광역시 동구"),
    "서구": ("29140", "광주광역시 서구"),
    "남구": ("29155", "광주광역시 남구"),
    "북구": ("29170", "광주광역시 북구"),
    "광산구": ("29200", "광주광역시 광산구"),
}
_JEONNAM_SIGUNGU: Final = {
    "목포": ("46110", "전라남도 목포시"),
    "여수": ("46130", "전라남도 여수시"),
    "순천": ("46150", "전라남도 순천시"),
    "나주": ("46170", "전라남도 나주시"),
    "광양": ("46230", "전라남도 광양시"),
    "담양": ("46710", "전라남도 담양군"),
    "곡성": ("46720", "전라남도 곡성군"),
    "구례": ("46730", "전라남도 구례군"),
    "고흥": ("46770", "전라남도 고흥군"),
    "보성": ("46780", "전라남도 보성군"),
    "화순": ("46790", "전라남도 화순군"),
    "장흥": ("46800", "전라남도 장흥군"),
    "강진": ("46810", "전라남도 강진군"),
    "해남": ("46820", "전라남도 해남군"),
    "영암": ("46830", "전라남도 영암군"),
    "무안": ("46840", "전라남도 무안군"),
    "함평": ("46860", "전라남도 함평군"),
    "영광": ("46870", "전라남도 영광군"),
    "장성": ("46880", "전라남도 장성군"),
    "완도": ("46890", "전라남도 완도군"),
    "진도": ("46900", "전라남도 진도군"),
    "신안": ("46910", "전라남도 신안군"),
}


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


def _parent_regions(
    text: str,
    labels: tuple[str, ...],
    parent_code: str,
    parent_name: str,
    mapping: Mapping[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    label_pattern = "|".join(re.escape(label) for label in labels)
    group = re.search(rf"(?:{label_pattern})\s*\(([^)]*)\)", text)
    if group is not None:
        group_text = group.group(1)
        if "제외" not in group_text:
            matched = [value for name, value in mapping.items() if name in group_text]
            if matched:
                return matched
    if any(label in text for label in labels):
        return [(parent_code, parent_name)]
    return []


def _affected_regions(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    # KMA messages often contain “경기도(광주, …)”. Remove that group before
    # looking for an unqualified Gwangju so Gyeonggi Gwangju is never selected.
    scoped_text = re.sub(r"경기도\s*\([^)]*\)", "", text)
    regions = _parent_regions(
        scoped_text,
        ("광주광역시",),
        "29",
        "광주광역시",
        _GWANGJU_SIGUNGU,
    )
    if not regions and re.search(
        r"(^|[\s,:()])광주($|[\s,:()])",
        scoped_text,
    ):
        regions.append(("29", "광주광역시"))
    regions.extend(
        _parent_regions(
            scoped_text,
            ("전라남도", "전남"),
            "46",
            "전라남도",
            _JEONNAM_SIGUNGU,
        )
    )
    unique = dict(regions)
    return tuple(unique), tuple(unique.values())


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
    # t6 is a nationwide current-status appendix, not the affected area of
    # this announcement. Only the announcement/action fields decide scope.
    decision_text = normalize_space(f"{title} {_value(detail, 't1')} {_value(detail, 't2')}")
    action_text = _value(detail, "t1")
    display_title = (
        normalize_space(f"{title} · {action_text}")
        if action_text and action_text not in title
        else title
    )
    region_codes, region_names = _affected_regions(decision_text)
    warning_type = _warning_type(decision_text)
    is_resolved = "해제" in decision_text and not any(
        token in decision_text for token in ("발효", "발령", "변경")
    )
    severity = (
        "WARNING" if "경보" in decision_text else ("WATCH" if "주의보" in decision_text else None)
    )
    published_at = _parse_tm_fc(forecast_time)
    return CanonicalSignal(
        source=SignalSource.KMA_WARNING,
        external_id=f"{station_id}:{forecast_time}:{sequence}",
        event_type=EventType.WEATHER_WARNING,
        event_subtype=warning_type,
        severity=severity,
        source_status=SourceStatus.RESOLVED if is_resolved else SourceStatus.ACTIVE,
        title=display_title,
        summary=detail_text or None,
        source_published_at=published_at,
        effective_at=published_at,
        expires_at=None,
        address=None,
        region_codes=region_codes,
        region_names=region_names,
        longitude=None,
        latitude=None,
        location_precision=(
            "SIGUNGU"
            if region_codes and all(len(code) == 5 for code in region_codes)
            else "SIDO"
        )
        if region_codes
        else None,
        is_relevant=bool(region_codes),
        relevance_reasons=("GWANGJU_JEONNAM_REGION",) if region_codes else ("OUT_OF_SCOPE_REGION",),
    )
