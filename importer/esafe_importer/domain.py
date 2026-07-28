from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

REFERENCE_NAMESPACE = uuid.UUID("963b5245-20a9-5500-80ab-ac380507d08f")
REFERENCE_MONTH = "2026-03-01"
HORIZON_DAYS = 60
LINEAGE_VERSION = "v27.1-focus-2026-03-60d"
SOURCE_CLASS = "V27_1_FOCUS_FINAL_SCORE"
EXPECTED_BUILDING_COUNT = 217_238


@dataclass(frozen=True, slots=True)
class RankedRisk:
    source_building_key: str
    score: float
    rank: int
    top_percentile: float
    band: str


def stable_uuid(kind: str, source_key: str) -> uuid.UUID:
    return uuid.uuid5(REFERENCE_NAMESPACE, f"{kind}:{source_key}")


def building_uuid(source_key: str) -> uuid.UUID:
    return stable_uuid("building", source_key)


def facility_uuid(source_key: str) -> uuid.UUID:
    return stable_uuid("facility", source_key)


def risk_uuid(source_key: str) -> uuid.UUID:
    return stable_uuid("risk", f"{source_key}:{LINEAGE_VERSION}")


def rank_risks(scores: dict[str, float]) -> list[RankedRisk]:
    """Return a complete deterministic ordinal ranking over Gwangju-Jeonnam buildings."""
    if not scores:
        raise ValueError("risk score input is empty")
    for key, score in scores.items():
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"invalid final_score for building {key}")

    ordered = sorted(scores.items(), key=lambda item: (-item[1], int(item[0])))
    total = len(ordered)
    top_1_limit = math.ceil(total * 0.01)
    top_10_limit = math.ceil(total * 0.10)
    top_25_limit = math.ceil(total * 0.25)
    ranked: list[RankedRisk] = []
    for rank, (source_key, score) in enumerate(ordered, start=1):
        if rank <= top_1_limit:
            band = "TOP_1"
        elif rank <= top_10_limit:
            band = "HIGH_1_10"
        elif rank <= top_25_limit:
            band = "WATCH_10_25"
        else:
            band = "GENERAL"
        ranked.append(
            RankedRisk(
                source_building_key=source_key,
                score=score,
                rank=rank,
                top_percentile=rank * 100.0 / total,
                band=band,
            )
        )
    return ranked
