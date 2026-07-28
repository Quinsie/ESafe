import math

import pytest

from esafe_importer.domain import building_uuid, rank_risks


def test_stable_building_uuid() -> None:
    assert building_uuid("30104609") == building_uuid("30104609")
    assert building_uuid("30104609") != building_uuid("30104610")


def test_ranking_breaks_equal_scores_by_numeric_source_key() -> None:
    rows = rank_risks({"10": 0.5, "2": 0.5, "7": 0.9})
    assert [(row.source_building_key, row.rank) for row in rows] == [
        ("7", 1),
        ("2", 2),
        ("10", 3),
    ]
    assert rows[-1].top_percentile == 100.0


def test_risk_band_boundaries_use_ceiling() -> None:
    rows = rank_risks({str(index): 1 - index / 1000 for index in range(101)})
    assert sum(row.band == "TOP_1" for row in rows) == math.ceil(101 * 0.01)
    assert sum(row.band in {"TOP_1", "HIGH_1_10"} for row in rows) == math.ceil(101 * 0.10)
    assert sum(row.band != "GENERAL" for row in rows) == math.ceil(101 * 0.25)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_scores_are_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="invalid final_score"):
        rank_risks({"1": score})
