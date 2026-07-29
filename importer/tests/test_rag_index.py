from __future__ import annotations

from esafe_importer.rag_index import (
    extract_disaster_types,
    extract_regions,
    source_date,
)


def test_rag_metadata_extractors_are_deterministic() -> None:
    value = "2026.04.12. 전남 완도군 호우·화재 대응 보고"
    reported_on = source_date(value)

    assert extract_disaster_types(value) == ["화재", "호우"]
    assert extract_regions(value) == ["전라남도"]
    assert reported_on is not None
    assert reported_on.isoformat() == "2026-04-12"


def test_rag_metadata_extractors_leave_national_scope_empty() -> None:
    value = "전기재난 현장조치 행동매뉴얼"

    assert extract_disaster_types(value) == ["전기재난"]
    assert extract_regions(value) == []
