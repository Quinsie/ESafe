from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.document_content import (
    VARIANT_TEMPLATE_KEYS,
    DocumentPayload,
    build_initial_document_payload,
    build_standalone_document_payload,
    canonical_payload_hash,
    hwpx_values,
    missing_administrative_fields,
    render_document_html,
)
from app.document_templates import TEMPLATE_BY_KEY, render_hwpx

CASE = {
    "caseId": "11111111-1111-4111-8111-111111111111",
    "caseNumber": "ES-20260729-000001",
    "title": "광주 북구 전기화재 감시",
    "caseType": "FIRE",
    "status": "ACTIVE",
    "sourceStatus": "NFDS 현장출동",
    "monitoringPriority": "URGENT",
    "openedAt": "2026-07-29T05:00:00+00:00",
    "normalizedAddress": "광주광역시 북구",
    "regionName": "광주광역시 북구",
    "riskLabel": "상위 1%",
}
RECOMMENDATION = {
    "evidenceStatus": "INSUFFICIENT",
    "warning": "공식 현행 근거가 부족합니다.",
    "situationSummary": "현장 전기설비의 안전 상태를 우선 확인해야 합니다.",
    "requiredChecks": ["현장 통전 여부 확인", "관계기관 상황 확인"],
    "uncertainties": ["발화 원인 미확인"],
    "conflicts": [],
    "actions": [
        {
            "title": "현장 안전 상태 확인",
            "description": "통전 여부와 접근 가능 여부를 확인합니다.",
            "citations": [
                {
                    "documentTitle": "전기재난 현장조치 행동매뉴얼",
                    "locator": "12쪽",
                    "quote": "현장 안전을 우선 확인한다.",
                }
            ],
        }
    ],
}
NOW = datetime(2026, 7, 29, 6, 30, tzinfo=UTC)
TEMPLATE_DIR = Path(__file__).parents[1] / "app" / "assets" / "document_templates"


@pytest.mark.parametrize("variant", list(VARIANT_TEMPLATE_KEYS))
def test_initial_payload_matches_each_template_contract(variant: str) -> None:
    payload = build_initial_document_payload(
        variant=variant,  # type: ignore[arg-type]
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )
    definition = TEMPLATE_BY_KEY[VARIANT_TEMPLATE_KEYS[payload.variant]]

    assert payload.author.name == ""
    assert payload.author.approver == ""
    assert payload.document.number == ""
    assert payload.contact.phone == ""
    assert payload.evidence.status == "INSUFFICIENT"
    assert set(hwpx_values(payload, "REVIEW")) == set(definition.token_names)
    assert hwpx_values(payload, "REVIEW")["review.warning"]
    assert hwpx_values(payload, "FINAL")["review.warning"] == ""


def test_initial_payload_without_recommendation_still_creates_warning_draft() -> None:
    payload = build_initial_document_payload(
        variant="INCIDENT_REPORT",
        case=CASE,
        recommendation=None,
        now=NOW,
    )

    assert payload.evidence.status == "INSUFFICIENT"
    assert payload.review.warning == "근거 부족·추가 확인 필요"
    assert payload.response.actions == []
    assert payload.incident.summary == CASE["title"]


def test_payload_hash_is_canonical() -> None:
    payload = build_initial_document_payload(
        variant="BASIC_PLAN",
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )
    reloaded = DocumentPayload.model_validate(
        payload.model_dump(mode="json", by_alias=True)
    )

    assert canonical_payload_hash(payload) == canonical_payload_hash(reloaded)
    assert len(canonical_payload_hash(payload)) == 64


def test_missing_administrative_fields_are_warnings_not_validation_errors() -> None:
    payload = build_initial_document_payload(
        variant="BASIC_NOTICE",
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )

    assert missing_administrative_fields(payload) == [
        "작성자",
        "승인자",
        "문서번호",
        "전화번호",
        "수신기관",
    ]


def test_html_escapes_user_content_and_final_removes_internal_warning() -> None:
    payload = build_initial_document_payload(
        variant="BASIC_NOTICE",
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )
    changed = payload.model_copy(deep=True)
    changed.document.title = "<script>alert(1)</script>"
    changed.notice.recipient = "광주 & 전남"

    review_html = render_document_html(changed, "REVIEW")
    final_html = render_document_html(changed, "FINAL")

    assert "<script>alert(1)</script>" not in review_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in review_html
    assert "광주 &amp; 전남" in review_html
    assert "한국전기안전공사 사장" in review_html
    assert changed.review.warning in review_html
    assert changed.review.warning not in final_html


def test_incident_pdf_html_uses_hwpx_layout_contract() -> None:
    payload = build_initial_document_payload(
        variant="INCIDENT_REPORT",
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )

    html = render_document_html(payload, "REVIEW")

    assert '@page { size: A4; margin: 10mm 20mm; }' in html
    assert 'class="incident-approval-grid"' in html
    assert 'aria-label="결재 정보"' in html
    assert "상황요원" in html
    assert "상황실장" in html
    assert "부장" in html
    assert "처장" in html
    assert 'class="incident-facility"' in html
    assert "2. 시설 현황" in html
    assert "Noto Serif CJK KR" in html
    assert "background: #eef4fa" not in html
    assert payload.review.warning in html


def test_official_notice_pdf_uses_public_document_layout() -> None:
    payload = build_standalone_document_payload(
        variant="INSPECTION_REQUEST",
        target={
            "name": "문흥동 공간아파트",
            "address": "광주광역시 북구",
            "regionName": "광주광역시 북구",
            "regionalRank": 1,
            "topPercentile": 0.01,
            "finalScore": 0.99,
            "riskBandLabel": "최상위 위험",
            "facilityCount": 3,
        },
        now=NOW,
    )

    html = render_document_html(payload, "REVIEW")

    assert '@page { size: A4; margin: 18mm 18mm 15mm; }' in html
    assert 'class="official-brand"' in html
    assert 'class="official-meta"' in html
    assert "한국전기안전공사 사장" in html
    assert "background: #eef4fa" not in html


@pytest.mark.parametrize(
    ("variant", "target", "title_part"),
    [
        (
            "REGION_ANALYSIS",
            {
                "name": "광주광역시 북구",
                "regionName": "광주광역시 북구",
                "buildingCount": 27585,
                "top10Count": 5953,
                "activeCaseCount": 0,
                "topBuildings": ["문흥동 공간아파트 · 광주·전남 1위"],
            },
            "전기재해 예방 위험 분석 보고서",
        ),
        (
            "BUILDING_ANALYSIS",
            {
                "name": "문흥동 공간아파트",
                "address": "광주광역시 북구",
                "regionName": "광주광역시 북구",
                "regionalRank": 1,
                "topPercentile": 0.01,
                "finalScore": 0.99,
                "riskBandLabel": "최상위 위험",
                "facilityCount": 3,
            },
            "전기재해 예방 위험 분석 보고서",
        ),
        (
            "INSPECTION_REQUEST",
            {
                "name": "문흥동 공간아파트",
                "address": "광주광역시 북구",
                "regionName": "광주광역시 북구",
                "regionalRank": 1,
                "topPercentile": 0.01,
                "finalScore": 0.99,
                "riskBandLabel": "최상위 위험",
                "facilityCount": 3,
            },
            "현장점검",
        ),
    ],
)
def test_standalone_payload_uses_real_template_without_case(
    variant: str,
    target: dict[str, object],
    title_part: str,
) -> None:
    payload = build_standalone_document_payload(
        variant=variant,  # type: ignore[arg-type]
        target=target,
        now=NOW,
    )

    assert payload.case_id is None
    assert payload.case_number == ""
    assert title_part in payload.document.title
    assert payload.evidence.status == "INSUFFICIENT"
    assert set(hwpx_values(payload, "REVIEW")) == set(
        TEMPLATE_BY_KEY[VARIANT_TEMPLATE_KEYS[payload.variant]].token_names
    )


@pytest.mark.parametrize("variant", list(VARIANT_TEMPLATE_KEYS))
def test_shared_payload_renders_each_real_hwpx_template(
    variant: str,
    tmp_path: Path,
) -> None:
    payload = build_initial_document_payload(
        variant=variant,  # type: ignore[arg-type]
        case=CASE,
        recommendation=RECOMMENDATION,
        now=NOW,
    )
    template_key = VARIANT_TEMPLATE_KEYS[payload.variant]
    definition = TEMPLATE_BY_KEY[template_key]

    validation = render_hwpx(
        TEMPLATE_DIR / definition.file_name,
        tmp_path / f"{template_key}.hwpx",
        definition,
        hwpx_values(payload, "REVIEW"),
    )

    assert validation.token_names == ()
    assert validation.size_bytes > 0
