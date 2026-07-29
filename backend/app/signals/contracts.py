import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalSource(StrEnum):
    NFDS = "NFDS"
    KMA_WARNING = "KMA_WARNING"
    DISASTER_MESSAGE = "DISASTER_MESSAGE"


class EventType(StrEnum):
    FIRE_DISPATCH = "FIRE_DISPATCH"
    WEATHER_WARNING = "WEATHER_WARNING"
    DISASTER_MESSAGE = "DISASTER_MESSAGE"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    UPDATED = "UPDATED"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class PayloadSchemaError(ValueError):
    """Raised when an upstream payload cannot be parsed without guessing."""


@dataclass(frozen=True, slots=True)
class CanonicalSignal:
    source: SignalSource
    external_id: str
    event_type: EventType
    event_subtype: str | None
    severity: str | None
    source_status: SourceStatus
    title: str
    summary: str | None
    source_published_at: datetime | None
    effective_at: datetime | None
    expires_at: datetime | None
    address: str | None
    region_codes: tuple[str, ...]
    region_names: tuple[str, ...]
    longitude: float | None
    latitude: float | None
    location_precision: str | None
    is_relevant: bool
    relevance_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.external_id.strip():
            raise ValueError("external_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be present together")
        if self.is_relevant and not self.region_codes:
            raise ValueError("relevant signals must identify a Gwangju/Jeonnam region")


def normalize_space(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize_address(value: object | None) -> str | None:
    normalized = normalize_space(value)
    if not normalized:
        return None
    normalized = unicodedata.normalize("NFKC", normalized)
    for character in (" ", "\t", "\r", "\n", ",", "(", ")"):
        normalized = normalized.replace(character, "")
    return normalized or None
