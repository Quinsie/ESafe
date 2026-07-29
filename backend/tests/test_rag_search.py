from __future__ import annotations

from datetime import date

from app.rag_search import RETRIEVAL_VERSION, _query_text, fuse_candidates, select_context


def candidate(
    chunk_id: str,
    *,
    family: str = "AUTHORITATIVE_MANUAL",
    authority: int = 1,
    regions: list[str] | None = None,
    distance: float = 0.2,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": f"document-{chunk_id}",
        "document_family": family,
        "authority_level": authority,
        "regions": regions or [],
        "published_at": date(2026, 1, 1),
        "vector_distance": distance,
    }


def test_rrf_keeps_official_and_incident_groups_separate() -> None:
    official = candidate("official")
    incident = candidate(
        "incident",
        family="INCIDENT_CASE",
        authority=4,
    )

    fused = fuse_candidates(
        [official],
        [incident, official],
        primary_region_code="29",
        today=date(2026, 7, 29),
    )
    selected = select_context(fused)

    assert selected[0].group == "OFFICIAL"
    assert any(item.group == "PAST_INCIDENT" for item in selected)
    assert selected[0].fused_score > selected[1].fused_score


def test_vector_only_candidate_below_similarity_threshold_is_removed() -> None:
    weak = candidate("weak", distance=0.95)

    fused = fuse_candidates(
        [],
        [weak],
        primary_region_code="46",
        today=date(2026, 7, 29),
    )

    assert fused == []


def test_case_query_prefers_korean_signal_terms_without_priority_noise() -> None:
    query = _query_text(
        {
            "title": "전남 목포시 조선소 화재 발생",
            "case_type": "FIRE",
            "region_name": "전라남도",
            "monitoring_priority": "URGENT",
        }
    )

    assert RETRIEVAL_VERSION == "rag-hybrid-rrf-v2"
    assert query == "전남 목포시 조선소 화재 발생 전라남도 화재 소방"
    assert "URGENT" not in query
