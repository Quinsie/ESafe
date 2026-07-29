from uuid import UUID

import pytest

from app.recommendations import (
    RecommendationGenerationError,
    recommendation_response_schema,
    validate_recommendation_payload,
)

OFFICIAL_ONE = UUID("00000000-0000-4000-8000-000000000101")
OFFICIAL_TWO = UUID("00000000-0000-4000-8000-000000000102")
PAST = UUID("00000000-0000-4000-8000-000000000103")


def evidence_rows() -> list[dict[str, object]]:
    return [
        {
            "evidence_item_id": OFFICIAL_ONE,
            "evidence_group": "OFFICIAL",
            "current_status": "CURRENT",
            "excerpt": "현장 접근 전 전원 차단 여부를 확인한다.",
            "locator": "제3장 > 초동조치",
            "document_id": UUID("00000000-0000-4000-8000-000000000201"),
        },
        {
            "evidence_item_id": OFFICIAL_TWO,
            "evidence_group": "OFFICIAL",
            "current_status": "CURRENT",
            "excerpt": "안전이 확인되기 전에는 설비에 접근하지 않는다.",
            "locator": "제4장 > 안전조치",
            "document_id": UUID("00000000-0000-4000-8000-000000000202"),
        },
        {
            "evidence_item_id": PAST,
            "evidence_group": "PAST_INCIDENT",
            "current_status": "REFERENCE",
            "excerpt": "과거 사고에서는 배전반 상태를 먼저 기록하였다.",
            "locator": "사고 개요",
            "document_id": UUID("00000000-0000-4000-8000-000000000203"),
        },
    ]


def proposal(
    *,
    evidence_item_id: UUID = OFFICIAL_ONE,
    evidence_status: str = "SUFFICIENT",
    quote: str = "전원 차단 여부를 확인한다.",
    support_type: str = "DIRECT",
) -> dict[str, object]:
    return {
        "situationSummary": "광주 지역 화재 신호의 전기안전 확인이 필요합니다.",
        "requiredChecks": ["전원 차단 여부"],
        "uncertainties": [],
        "conflicts": [],
        "actions": [
            {
                "title": "전원 차단 확인",
                "description": "현장 접근 전 전원 상태를 확인합니다.",
                "dueGuidance": "즉시",
                "evidenceStatus": evidence_status,
                "warning": None,
                "citations": [
                    {
                        "evidenceItemId": str(evidence_item_id),
                        "supportType": support_type,
                        "quote": quote,
                    }
                ],
                "checklist": ["전원 차단 여부 기록"],
            }
        ],
    }


def test_official_exact_quote_is_sufficient() -> None:
    result = validate_recommendation_payload(proposal(), evidence_rows())

    assert result.evidence_status == "SUFFICIENT"
    assert result.actions[0].evidence_status == "SUFFICIENT"
    assert result.actions[0].citations[0].locator == "제3장 > 초동조치"


def test_hallucinated_quote_is_removed_and_warned() -> None:
    result = validate_recommendation_payload(
        proposal(quote="원문에 없는 인용"),
        evidence_rows(),
    )

    assert result.evidence_status == "INSUFFICIENT"
    assert result.actions[0].citations[0].support_type == "CONTEXT"
    assert (
        result.actions[0].citations[0].quote
        == evidence_rows()[0]["excerpt"]
    )
    assert result.actions[0].warning is not None


def test_response_schema_only_allows_supplied_evidence_ids() -> None:
    schema = recommendation_response_schema(evidence_rows())

    citation = schema["$defs"]["CitationProposal"]
    assert set(citation["properties"]["evidenceItemId"]["enum"]) == {
        str(OFFICIAL_ONE),
        str(OFFICIAL_TWO),
        str(PAST),
    }


def test_past_incident_cannot_become_direct_sufficient_evidence() -> None:
    result = validate_recommendation_payload(
        proposal(
            evidence_item_id=PAST,
            quote="과거 사고에서는 배전반 상태를 먼저 기록하였다.",
        ),
        evidence_rows(),
    )

    assert result.actions[0].evidence_status == "INSUFFICIENT"
    assert result.actions[0].citations[0].support_type == "CASE_EXAMPLE"


def test_conflict_requires_two_distinct_official_documents() -> None:
    value = proposal(evidence_status="CONFLICT")
    action = value["actions"][0]  # type: ignore[index]
    action["citations"].append(  # type: ignore[index,union-attr]
        {
            "evidenceItemId": str(OFFICIAL_TWO),
            "supportType": "DIRECT",
            "quote": "안전이 확인되기 전에는 설비에 접근하지 않는다.",
        }
    )
    value["conflicts"] = ["두 공식 문서의 접근 시점 표현을 확인해야 합니다."]

    result = validate_recommendation_payload(value, evidence_rows())

    assert result.evidence_status == "CONFLICT"
    assert result.actions[0].evidence_status == "CONFLICT"
    assert result.conflicts


def test_invalid_shape_is_rejected_before_persistence() -> None:
    with pytest.raises(
        RecommendationGenerationError,
        match="OUTPUT_SCHEMA_INVALID",
    ):
        validate_recommendation_payload({"actions": []}, evidence_rows())
