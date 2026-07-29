import json
from uuid import UUID

import pytest

from app.config import Settings
from app.recommendations import (
    GENERATION_VERSION,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    RecommendationGenerationError,
    _build_input,
    recommendation_response_schema,
    validate_recommendation_payload,
)

OFFICIAL_ONE = UUID("00000000-0000-4000-8000-000000000101")
OFFICIAL_TWO = UUID("00000000-0000-4000-8000-000000000102")
PAST = UUID("00000000-0000-4000-8000-000000000103")


def test_prompt_treats_unapplied_official_amendment_as_conflict() -> None:
    assert PROMPT_VERSION == "case-recommendation-ko-v4"
    assert GENERATION_VERSION == "recommendation-generator-v4"
    assert "변경 전 용어나 내용이 그대로 남아 있으면" in SYSTEM_PROMPT
    assert "하나의 CONFLICT 행동" in SYSTEM_PROMPT


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
        "answerEvidenceStatus": evidence_status,
        "answerWarning": None,
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
    assert result.actions[0].citations[0].quote == evidence_rows()[0]["excerpt"]
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
    action["citations"].append(
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


def test_insufficient_core_answer_cannot_be_upgraded_by_generic_action() -> None:
    value = proposal(evidence_status="SUFFICIENT")
    value["answerEvidenceStatus"] = "INSUFFICIENT"
    value["answerWarning"] = "질문의 핵심 의무를 뒷받침하는 근거가 없습니다."

    result = validate_recommendation_payload(value, evidence_rows())

    assert result.actions[0].evidence_status == "SUFFICIENT"
    assert result.evidence_status == "INSUFFICIENT"
    assert result.warning == value["answerWarning"]


def test_generation_input_includes_case_title_and_retrieval_query() -> None:
    case_row = {
        "case_id": UUID("00000000-0000-4000-8000-000000000301"),
        "case_number": "EVAL-001",
        "case_type": "FIRE",
        "title": "호우 특보 시 배수펌프장 전기설비를 어떻게 점검해야 하나?",
        "status": "ACTIVE",
        "source_status": "EVALUATION",
        "monitoring_priority": "ATTENTION",
        "primary_region_code": "29170",
        "region_name": "광주광역시 북구",
        "is_simulated": False,
        "version": 1,
        "impact_count": 3,
        "high_risk_count": 1,
        "incident_count": 0,
    }
    bundle = {
        "evidence_bundle_id": UUID("00000000-0000-4000-8000-000000000302"),
        "version": 1,
        "query_text": "호우 특보 배수펌프장 전기설비 점검",
    }
    rows = [
        {
            "evidence_item_id": OFFICIAL_ONE,
            "evidence_group": "OFFICIAL",
            "rank": 1,
            "current_status": "CURRENT",
            "document_title": "여름철 전기안전 종합대책",
            "issuing_agency": "한국전기안전공사",
            "document_number": None,
            "published_at": None,
            "excerpt": "배수펌프장 전기설비를 점검한다.",
            "locator": "제2장",
        }
    ]

    _, user_prompt, _ = _build_input(Settings(), case_row, bundle, rows)
    prompt = json.loads(user_prompt)

    assert prompt["caseFacts"]["caseTitle"] == case_row["title"]
    assert prompt["caseFacts"]["retrievalQuery"] == bundle["query_text"]
