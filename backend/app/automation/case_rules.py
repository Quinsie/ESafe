from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.signals.contracts import EventType, SourceStatus

DEFAULT_POINT_RADIUS_M: Final = 1000
ALLOWED_RADII_M: Final = frozenset({500, 1000, 3000, 5000})
CASE_RULE_VERSION: Final = "case-lifecycle-v1"
IMPACT_RULE_VERSION: Final = "case-impact-v1"


class CaseStatus(StrEnum):
    DETECTED = "DETECTED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    SOURCE_RESOLVED_REVIEW = "SOURCE_RESOLVED_REVIEW"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class CaseType(StrEnum):
    FIRE = "FIRE"
    WEATHER_WARNING = "WEATHER_WARNING"
    DISASTER_MESSAGE = "DISASTER_MESSAGE"


class ImpactScopeType(StrEnum):
    RADIUS = "RADIUS"
    ADMIN_REGION = "ADMIN_REGION"


@dataclass(frozen=True, slots=True)
class SignalFacts:
    event_type: EventType
    source_status: SourceStatus
    region_codes: tuple[str, ...]
    longitude: float | None = None
    latitude: float | None = None

    def __post_init__(self) -> None:
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be present together")


@dataclass(frozen=True, slots=True)
class ImpactScope:
    scope_type: ImpactScopeType
    radius_m: int | None
    region_codes: tuple[str, ...]
    precision_warning: str | None


def case_type_for(event_type: EventType) -> CaseType:
    if event_type is EventType.FIRE_DISPATCH:
        return CaseType.FIRE
    if event_type is EventType.WEATHER_WARNING:
        return CaseType.WEATHER_WARNING
    return CaseType.DISASTER_MESSAGE


def initial_case_status(source_status: SourceStatus) -> CaseStatus:
    if source_status is SourceStatus.RESOLVED:
        return CaseStatus.SOURCE_RESOLVED_REVIEW
    return CaseStatus.ACTIVE


def next_case_status(current: CaseStatus, source_status: SourceStatus) -> CaseStatus:
    if current in (CaseStatus.CLOSED, CaseStatus.MERGED):
        return current
    if source_status is SourceStatus.RESOLVED:
        return CaseStatus.SOURCE_RESOLVED_REVIEW
    if current is CaseStatus.SOURCE_RESOLVED_REVIEW:
        return CaseStatus.ACTIVE
    return current


def select_impact_scope(
    signal: SignalFacts,
    radius_m: int = DEFAULT_POINT_RADIUS_M,
) -> ImpactScope:
    if radius_m not in ALLOWED_RADII_M:
        raise ValueError("radius_m must be one of 500, 1000, 3000, or 5000")
    if signal.longitude is not None:
        return ImpactScope(
            scope_type=ImpactScopeType.RADIUS,
            radius_m=radius_m,
            region_codes=(),
            precision_warning=None,
        )
    if not signal.region_codes:
        raise ValueError("a signal without a point must identify an administrative region")
    warning = (
        "LOCATION_PRECISION_SIDO"
        if all(len(region_code) == 2 for region_code in signal.region_codes)
        else None
    )
    return ImpactScope(
        scope_type=ImpactScopeType.ADMIN_REGION,
        radius_m=None,
        region_codes=signal.region_codes,
        precision_warning=warning,
    )
