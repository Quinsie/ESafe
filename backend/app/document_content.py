from __future__ import annotations

import hashlib
import html
import json
from datetime import date, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.document_templates import TEMPLATE_BY_KEY

DocumentVariant = Literal[
    "INCIDENT_REPORT",
    "CRISIS_ASSESSMENT",
    "BASIC_NOTICE",
    "BASIC_PLAN",
    "REGION_ANALYSIS",
    "BUILDING_ANALYSIS",
    "INSPECTION_REQUEST",
]
EvidenceStatus = Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"]
ArtifactStage = Literal["REVIEW", "FINAL"]
ShortText = Annotated[str, Field(max_length=500)]
BodyText = Annotated[str, Field(max_length=8000)]

VARIANT_TEMPLATE_KEYS: dict[DocumentVariant, str] = {
    "INCIDENT_REPORT": "incident-report",
    "CRISIS_ASSESSMENT": "crisis-assessment",
    "BASIC_NOTICE": "official-notice",
    "BASIC_PLAN": "response-plan",
    "REGION_ANALYSIS": "incident-report",
    "BUILDING_ANALYSIS": "incident-report",
    "INSPECTION_REQUEST": "official-notice",
}
VARIANT_FAMILIES: dict[DocumentVariant, str] = {
    "INCIDENT_REPORT": "SITUATION_REPORT",
    "CRISIS_ASSESSMENT": "SITUATION_REPORT",
    "BASIC_NOTICE": "OFFICIAL_NOTICE",
    "BASIC_PLAN": "RESPONSE_PLAN",
    "REGION_ANALYSIS": "SITUATION_REPORT",
    "BUILDING_ANALYSIS": "SITUATION_REPORT",
    "INSPECTION_REQUEST": "OFFICIAL_NOTICE",
}
VARIANT_TITLES: dict[DocumentVariant, str] = {
    "INCIDENT_REPORT": "전기재해 사고·상황 보고서",
    "CRISIS_ASSESSMENT": "위기상황판단 평가보고서",
    "BASIC_NOTICE": "전기재해 예방 대응 협조 요청",
    "BASIC_PLAN": "전기재해 예방 대응 계획",
    "REGION_ANALYSIS": "지역 전기재해 예방 위험 분석 보고서",
    "BUILDING_ANALYSIS": "건물 전기재해 예방 위험 분석 보고서",
    "INSPECTION_REQUEST": "전기설비 현장점검 협조 요청",
}
EVIDENCE_WARNINGS: dict[EvidenceStatus, str] = {
    "SUFFICIENT": "",
    "INSUFFICIENT": "근거 부족·추가 확인 필요",
    "CONFLICT": "근거 충돌·사용자 판단 필요",
}


class DocumentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: ShortText
    date: ShortText
    year: ShortText
    number: ShortText = ""


class AuthorFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortText = ""
    department: ShortText = ""
    approver: ShortText = ""


class ContactFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: ShortText = ""
    email: ShortText = ""
    block: BodyText = ""


class IncidentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ShortText
    occurred_at: ShortText = Field(alias="occurredAt")
    location: ShortText
    cause: BodyText = ""
    summary: BodyText
    detail: BodyText = ""
    damage: BodyText = ""
    agencies: BodyText = ""


class FacilityFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortText = ""
    address: ShortText = ""
    use: ShortText = ""
    risk: ShortText = ""
    region: ShortText = ""
    detail: BodyText = ""


class AnalysisFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: BodyText
    uncertainties: list[ShortText] = Field(default_factory=list, max_length=32)
    conflicts: list[ShortText] = Field(default_factory=list, max_length=32)


class MonitoringFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: BodyText
    signals: list[ShortText] = Field(default_factory=list, max_length=32)


class ResponseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: BodyText
    priority: ShortText
    actions: list[BodyText] = Field(default_factory=list, max_length=32)
    evidence: list[BodyText] = Field(default_factory=list, max_length=64)
    plan: list[BodyText] = Field(default_factory=list, max_length=32)
    recipients: list[ShortText] = Field(default_factory=list, max_length=32)
    coordination: BodyText = ""
    approval_procedure: BodyText = Field(default="", alias="approvalProcedure")
    reporting_procedure: BodyText = Field(default="", alias="reportingProcedure")
    reporting_timing: BodyText = Field(default="", alias="reportingTiming")
    emergency_plan: BodyText = Field(default="", alias="emergencyPlan")


class EvidenceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvidenceStatus
    references: list[BodyText] = Field(default_factory=list, max_length=64)


class NoticeFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: ShortText = ""
    delivery_route: ShortText = Field(default="", alias="deliveryRoute")
    opening: BodyText = ""
    grounds: list[BodyText] = Field(default_factory=list, max_length=32)
    request: list[BodyText] = Field(default_factory=list, max_length=32)
    deadline: ShortText = ""


class AttachmentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ShortText] = Field(default_factory=list, max_length=32)


class ReviewFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning: ShortText = ""


class DocumentPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    case_id: str | None = Field(default=None, alias="caseId", min_length=36, max_length=36)
    case_number: ShortText = Field(default="", alias="caseNumber")
    variant: DocumentVariant
    document: DocumentIdentity
    author: AuthorFields
    contact: ContactFields
    incident: IncidentFields
    facility: FacilityFields
    analysis: AnalysisFields
    monitoring: MonitoringFields
    response: ResponseFields
    evidence: EvidenceFields
    notice: NoticeFields
    attachments: AttachmentFields
    review: ReviewFields


def canonical_payload_hash(payload: DocumentPayload) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _citation_lines(actions: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for action in actions:
        citations = action.get("citations")
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            title = str(citation.get("documentTitle") or "근거 문서").strip()
            locator = str(citation.get("locator") or "").strip()
            quote = str(citation.get("quote") or "").strip()
            heading = f"{title} ({locator})" if locator else title
            line = f"{heading}: {quote}" if quote else heading
            if line not in result:
                result.append(line)
    return result


def build_initial_document_payload(
    *,
    variant: DocumentVariant,
    case: dict[str, Any],
    recommendation: dict[str, Any] | None,
    now: datetime,
) -> DocumentPayload:
    case_id = str(case["caseId"])
    case_number = str(case["caseNumber"])
    case_title = str(case.get("title") or VARIANT_TITLES[variant])
    evidence_status = (
        str(recommendation.get("evidenceStatus"))
        if recommendation
        else "INSUFFICIENT"
    )
    if evidence_status not in EVIDENCE_WARNINGS:
        evidence_status = "INSUFFICIENT"
    typed_evidence_status = cast(EvidenceStatus, evidence_status)
    actions = (
        [
            action
            for action in recommendation.get("actions", [])
            if isinstance(action, dict)
        ]
        if recommendation
        else []
    )
    action_lines = [
        f"{action.get('title', '').strip()}: {action.get('description', '').strip()}".strip(
            ": "
        )
        for action in actions
        if str(action.get("title") or action.get("description") or "").strip()
    ]
    citation_lines = _citation_lines(actions)
    required_checks = (
        _as_list(recommendation.get("requiredChecks")) if recommendation else []
    )
    uncertainties = (
        _as_list(recommendation.get("uncertainties")) if recommendation else []
    )
    conflicts = _as_list(recommendation.get("conflicts")) if recommendation else []
    warning = EVIDENCE_WARNINGS[typed_evidence_status]
    if recommendation and recommendation.get("warning"):
        warning = str(recommendation["warning"])
    occurred_at = (
        str(case.get("openedAt") or case.get("updatedAt") or now.isoformat())
    )
    location = str(
        case.get("normalizedAddress")
        or case.get("regionName")
        or "위치 확인 필요"
    )
    situation_summary = str(
        recommendation.get("situationSummary") if recommendation else case_title
    ).strip()
    priority = str(case.get("monitoringPriority") or "NORMAL")
    source_status = str(case.get("sourceStatus") or "확인 필요")
    document_title = VARIANT_TITLES[variant]
    if variant != "BASIC_NOTICE":
        document_title = f"{case_number} {document_title}"
    opening = f"{case_title} 상황과 관련하여 전기재해 예방 대응 협조를 요청드립니다."
    return DocumentPayload.model_validate(
        {
            "schemaVersion": 1,
            "caseId": case_id,
            "caseNumber": case_number,
            "variant": variant,
            "document": {
                "title": document_title,
                "date": now.date().isoformat(),
                "year": str(now.year),
                "number": "",
            },
            "author": {"name": "", "department": "", "approver": ""},
            "contact": {"phone": "", "email": "", "block": ""},
            "incident": {
                "type": str(case.get("caseType") or "전기재해"),
                "occurredAt": occurred_at,
                "location": location,
                "cause": "",
                "summary": situation_summary,
                "detail": f"사건 상태: {case.get('status', '확인 필요')}",
                "damage": "",
                "agencies": "",
            },
            "facility": {
                "name": "",
                "address": location,
                "use": "",
                "risk": str(case.get("riskLabel") or ""),
                "region": str(case.get("regionName") or ""),
                "detail": "",
            },
            "analysis": {
                "result": situation_summary,
                "uncertainties": uncertainties,
                "conflicts": conflicts,
            },
            "monitoring": {
                "summary": f"원천 상태 {source_status}, 관제 우선순위 {priority}",
                "signals": [source_status],
            },
            "response": {
                "summary": situation_summary,
                "priority": priority,
                "actions": action_lines,
                "evidence": citation_lines,
                "plan": required_checks or action_lines,
                "recipients": [],
                "coordination": "",
                "approvalProcedure": "",
                "reportingProcedure": "",
                "reportingTiming": "",
                "emergencyPlan": "",
            },
            "evidence": {
                "status": typed_evidence_status,
                "references": citation_lines,
            },
            "notice": {
                "recipient": "",
                "deliveryRoute": "",
                "opening": opening,
                "grounds": citation_lines,
                "request": action_lines,
                "deadline": "",
            },
            "attachments": {"items": []},
            "review": {"warning": warning},
        }
    )


def build_standalone_document_payload(
    *,
    variant: Literal["REGION_ANALYSIS", "BUILDING_ANALYSIS", "INSPECTION_REQUEST"],
    target: dict[str, Any],
    now: datetime,
) -> DocumentPayload:
    target_name = str(target["name"])
    address = str(target.get("address") or target.get("regionName") or "")
    region_name = str(target.get("regionName") or target_name)
    building_count = int(target.get("buildingCount") or 0)
    top10_count = int(target.get("top10Count") or 0)
    active_case_count = int(target.get("activeCaseCount") or 0)
    rank = target.get("regionalRank")
    percentile = target.get("topPercentile")
    score = target.get("finalScore")
    risk_band = str(target.get("riskBandLabel") or "")
    facility_count = int(target.get("facilityCount") or 0)
    common_warning = "대응 근거 부족·추가 확인 필요"

    if variant == "REGION_ANALYSIS":
        title = f"{target_name} 전기재해 예방 위험 분석 보고서"
        summary = (
            f"{target_name}의 모델 대상 건물 {building_count:,}개를 광주·전남 전체 "
            f"상대순위와 네 위험구간으로 분석했습니다."
        )
        risk_summary = f"상위 10% 건물 {top10_count:,}개"
        actions = [
            str(item)
            for item in target.get("topBuildings", [])
            if str(item).strip()
        ]
        plan = [
            "상위 위험 건물의 기준정보와 최근 점검 이력을 확인합니다.",
            "활성 재난 신호가 있는 경우 해당 Case의 대응 업무를 별도로 확인합니다.",
        ]
        facility_name = target_name
        facility_detail = f"현재 연결된 활성 Case {active_case_count:,}건"
        incident_type = "지역 위험 분석"
    else:
        title = (
            f"{target_name} 전기재해 예방 위험 분석 보고서"
            if variant == "BUILDING_ANALYSIS"
            else f"{target_name} 전기설비 현장점검 협조 요청"
        )
        rank_text = f"광주·전남 {int(rank):,}위" if rank is not None else "순위 확인 필요"
        percentile_text = (
            f"상위 {float(percentile):.2f}%" if percentile is not None else ""
        )
        score_text = f"상대점수 {float(score):.6f}" if score is not None else ""
        risk_summary = " · ".join(
            item for item in (risk_band, rank_text, percentile_text, score_text) if item
        )
        summary = (
            f"{target_name}은(는) {risk_summary}입니다. 이 값은 현장 확인 우선순위를 "
            "정하기 위한 상대값이며 사고 발생확률이 아닙니다."
        )
        actions = [
            "건축물 및 연결 전기설비의 현장 상태를 확인합니다.",
            "최근 점검 이후 설비 변경과 이상 징후를 확인합니다.",
            "점검 결과와 필요한 후속조치를 시스템에 기록합니다.",
        ]
        plan = list(actions)
        facility_name = target_name
        facility_detail = (
            f"연결 설비 {facility_count:,}건 · 현재 연결된 활성 Case "
            f"{active_case_count:,}건"
        )
        incident_type = "건물 위험 분석" if variant == "BUILDING_ANALYSIS" else "현장점검 요청"

    notice_opening = (
        f"{target_name}의 전기재해 예방을 위한 현장점검 협조를 요청드립니다."
        if variant == "INSPECTION_REQUEST"
        else ""
    )
    return DocumentPayload.model_validate(
        {
            "schemaVersion": 1,
            "caseId": None,
            "caseNumber": "",
            "variant": variant,
            "document": {
                "title": title,
                "date": now.date().isoformat(),
                "year": str(now.year),
                "number": "",
            },
            "author": {"name": "", "department": "", "approver": ""},
            "contact": {"phone": "", "email": "", "block": ""},
            "incident": {
                "type": incident_type,
                "occurredAt": now.date().isoformat(),
                "location": address or region_name,
                "cause": "",
                "summary": summary,
                "detail": facility_detail,
                "damage": "해당 없음 · 예방 분석 및 점검 목적",
                "agencies": "",
            },
            "facility": {
                "name": facility_name,
                "address": address,
                "use": str(target.get("use") or ""),
                "risk": risk_summary,
                "region": region_name,
                "detail": facility_detail,
            },
            "analysis": {
                "result": summary,
                "uncertainties": ["현장 상태와 최신 점검 이력은 사용자 확인이 필요합니다."],
                "conflicts": [],
            },
            "monitoring": {
                "summary": f"현재 연결된 활성 Case {active_case_count:,}건",
                "signals": [],
            },
            "response": {
                "summary": summary,
                "priority": risk_band or "NORMAL",
                "actions": actions,
                "evidence": [],
                "plan": plan,
                "recipients": [],
                "coordination": "",
                "approvalProcedure": "",
                "reportingProcedure": "",
                "reportingTiming": "",
                "emergencyPlan": "",
            },
            "evidence": {"status": "INSUFFICIENT", "references": []},
            "notice": {
                "recipient": "",
                "deliveryRoute": "",
                "opening": notice_opening,
                "grounds": [
                    "v27.1 · 2026-03 · 향후 60일 광주·전남 상대위험 기준",
                    risk_summary,
                ],
                "request": actions if variant == "INSPECTION_REQUEST" else [],
                "deadline": "",
            },
            "attachments": {
                "items": (
                    [f"붙임 1. {target_name} 위험 분석 요약 1부."]
                    if variant == "INSPECTION_REQUEST"
                    else []
                )
            },
            "review": {"warning": common_warning},
        }
    )


def _lines(values: list[str], *, empty: str = "") -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    return "\n".join(f"{index}. {value}" for index, value in enumerate(cleaned, 1)) or empty


def hwpx_values(payload: DocumentPayload, stage: ArtifactStage) -> dict[str, str]:
    warning = payload.review.warning if stage == "REVIEW" else ""
    values = {
        "document.title": payload.document.title,
        "document.date": payload.document.date,
        "document.year": payload.document.year,
        "document.number": payload.document.number,
        "author.name": payload.author.name,
        "author.department": payload.author.department,
        "contact.phone": payload.contact.phone,
        "contact.block": payload.contact.block,
        "incident.type": payload.incident.type,
        "incident.occurredAt": payload.incident.occurred_at,
        "incident.location": payload.incident.location,
        "incident.cause": payload.incident.cause,
        "incident.summary": payload.incident.summary,
        "incident.detail": payload.incident.detail,
        "incident.damage": payload.incident.damage,
        "incident.agencies": payload.incident.agencies,
        "facility.name": payload.facility.name,
        "facility.address": payload.facility.address,
        "facility.use": payload.facility.use,
        "facility.risk": payload.facility.risk,
        "facility.region": payload.facility.region,
        "facility.detail": payload.facility.detail,
        "analysis.result": payload.analysis.result,
        "analysis.uncertainties": _lines(payload.analysis.uncertainties),
        "analysis.conflicts": _lines(payload.analysis.conflicts),
        "monitoring.summary": payload.monitoring.summary,
        "monitoring.signals": _lines(payload.monitoring.signals),
        "response.summary": payload.response.summary,
        "response.priority": payload.response.priority,
        "response.actions": _lines(payload.response.actions),
        "response.evidence": _lines(payload.response.evidence),
        "response.plan": _lines(payload.response.plan),
        "response.recipients": _lines(payload.response.recipients),
        "response.coordination": payload.response.coordination,
        "response.approvalProcedure": payload.response.approval_procedure,
        "response.reportingProcedure": payload.response.reporting_procedure,
        "response.reportingTiming": payload.response.reporting_timing,
        "response.emergencyPlan": payload.response.emergency_plan,
        "evidence.references": _lines(payload.evidence.references),
        "notice.recipient": payload.notice.recipient,
        "notice.deliveryRoute": payload.notice.delivery_route,
        "notice.opening": payload.notice.opening,
        "notice.grounds": _lines(payload.notice.grounds),
        "notice.request": _lines(payload.notice.request),
        "notice.deadline": payload.notice.deadline,
        "attachments.list": _lines(payload.attachments.items),
        "review.warning": warning,
    }
    template_key = VARIANT_TEMPLATE_KEYS[payload.variant]
    return {
        token: values[token]
        for token in TEMPLATE_BY_KEY[template_key].token_names
    }


def missing_administrative_fields(payload: DocumentPayload) -> list[str]:
    candidates = {
        "작성자": payload.author.name,
        "승인자": payload.author.approver,
        "문서번호": payload.document.number,
        "전화번호": payload.contact.phone,
    }
    if payload.variant in {"BASIC_NOTICE", "INSPECTION_REQUEST"}:
        candidates["수신기관"] = payload.notice.recipient
    return [label for label, value in candidates.items() if not value.strip()]


def _escaped(value: str) -> str:
    return html.escape(value, quote=True).replace("\n", "<br>")


def _html_list(values: list[str], *, empty_label: str = "") -> str:
    items = "".join(f"<li>{_escaped(value)}</li>" for value in values if value.strip())
    if items:
        return f"<ol>{items}</ol>"
    return f'<div class="blank">{_escaped(empty_label)}</div>'


def _field(label: str, value: str) -> str:
    rendered = _escaped(value) if value.strip() else '<span class="blank-line"></span>'
    return (
        '<div class="field">'
        f'<span class="field-label">{_escaped(label)}</span>'
        f'<span class="field-value">{rendered}</span>'
        "</div>"
    )


def _section(title: str, body: str) -> str:
    return f'<section><h2>{_escaped(title)}</h2>{body}</section>'


def _incident_value(value: str) -> str:
    return _escaped(value) if value.strip() else '<span class="incident-blank"></span>'


def _incident_line(label: str, value: str) -> str:
    return (
        '<p class="incident-line">'
        f'<span class="incident-bullet">ㅇ</span> {label}: {_incident_value(value)}'
        "</p>"
    )


def _incident_numbered_lines(values: list[str]) -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    if not cleaned:
        return '<p class="incident-line incident-empty">&nbsp;</p>'
    return "".join(
        f'<p class="incident-line">{index}. {_escaped(value)}</p>'
        for index, value in enumerate(cleaned, 1)
    )


def _incident_report_html(payload: DocumentPayload, stage: ArtifactStage) -> str:
    warning = payload.review.warning if stage == "REVIEW" else ""
    warning_line = (
        f'<p class="incident-warning">{_escaped(warning)}</p>' if warning else ""
    )
    facility_detail = (
        f'<p class="incident-line">{_escaped(payload.facility.detail)}</p>'
        if payload.facility.detail.strip()
        else ""
    )
    attachments = _incident_numbered_lines(payload.attachments.items)
    contact = (
        f'<p class="incident-line">{_escaped(payload.contact.block)}</p>'
        if payload.contact.block.strip()
        else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{_escaped(payload.document.title)}</title>
<style>
@page {{ size: A4; margin: 10mm 20mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  color: #000;
  font-family: "Noto Serif CJK KR", "Batang", serif;
  font-size: 15pt;
  line-height: 1.35;
  word-break: keep-all;
  overflow-wrap: break-word;
}}
.incident-report {{ width: 170mm; margin: 0 auto; }}
.incident-title {{
  margin: 0;
  text-align: center;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 19pt;
  font-weight: 900;
  line-height: 1;
  letter-spacing: -0.03em;
}}
.incident-title span {{
  display: inline;
  padding-bottom: 0.5mm;
  border-bottom: 0.65mm double #000;
}}
.incident-approval-grid {{
  display: grid;
  width: 92mm;
  height: 20mm;
  margin: 2.5mm 0 0 auto;
  grid-template-columns: 10mm repeat(4, 1fr);
  grid-template-rows: 7mm 13mm;
  border-top: 0.12mm solid #000;
  border-left: 0.12mm solid #000;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 9pt;
  line-height: 1.2;
}}
.incident-approval-grid span {{
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 0.12mm solid #000;
  border-bottom: 0.12mm solid #000;
}}
.incident-approval-grid .approval-label {{
  grid-row: 1 / 3;
  font-weight: 800;
  writing-mode: vertical-rl;
  letter-spacing: 0.18em;
}}
.incident-approval-grid .approval-role {{ font-weight: 700; }}
.incident-date {{
  margin: 1.8mm 0 2.8mm;
  text-align: center;
  font-family: "Noto Serif CJK KR", "Batang", serif;
  font-size: 14pt;
}}
.incident-section {{
  margin: 0 0 2.4mm;
  break-inside: auto;
}}
.incident-section h2 {{
  margin: 0 0 0.7mm;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 15pt;
  font-weight: 800;
  line-height: 1.35;
  break-after: avoid;
}}
.incident-line {{
  margin: 0;
  padding-left: 5mm;
  text-indent: 0;
  white-space: pre-wrap;
}}
.incident-bullet {{ font-family: "Noto Sans CJK KR", sans-serif; }}
.incident-summary {{ margin: 0; padding-left: 10mm; white-space: pre-wrap; }}
.incident-blank {{
  display: inline-block;
  min-width: 45mm;
  min-height: 1em;
  vertical-align: bottom;
}}
.incident-facility {{
  width: 100%;
  margin: 0 0 2.4mm;
  border-collapse: collapse;
  table-layout: fixed;
  break-inside: avoid;
}}
.incident-facility td {{
  padding: 0.5mm 1.8mm;
  border: 0.12mm solid #000;
  vertical-align: top;
}}
.incident-facility-title {{
  width: 53mm;
  text-align: center;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 15pt;
  font-weight: 800;
}}
.incident-facility-body {{ min-height: 26.7mm; padding: 1.1mm 1.8mm 1.4mm !important; }}
.incident-warning {{
  margin: 0;
  padding-left: 5mm;
  color: #7a1d1d;
  font-weight: 700;
}}
.incident-empty {{ min-height: 1.35em; }}
</style>
</head>
<body>
<article class="incident-report">
  <h1 class="incident-title"><span>{_escaped(payload.document.title)}</span></h1>
  <div class="incident-approval-grid" aria-label="결재 정보">
    <span class="approval-label">결재</span>
    <span class="approval-role">상황요원</span><span class="approval-role">상황실장</span>
    <span class="approval-role">부장</span><span class="approval-role">처장</span>
    <span></span><span></span><span></span><span></span>
  </div>
  <p class="incident-date">{_escaped(payload.document.date)}</p>
  <section class="incident-section">
    <h2>1. 사고 개요</h2>
    {_incident_line("발생일시", payload.incident.occurred_at)}
    {_incident_line("발생장소", payload.incident.location)}
    {_incident_line("사고원인", payload.incident.cause)}
    <p class="incident-line"><span class="incident-bullet">ㅇ</span> 상황개요</p>
    <p class="incident-summary">{_escaped(payload.incident.summary)}</p>
    <p class="incident-summary">{_escaped(payload.incident.detail)}</p>
  </section>
  <table class="incident-facility">
    <tbody>
      <tr><td></td><td class="incident-facility-title">2. 시설 현황</td><td></td></tr>
      <tr>
        <td colspan="3" class="incident-facility-body">
          {_incident_line("시설명", payload.facility.name)}
          {_incident_line("주소", payload.facility.address)}
          {_incident_line("용도", payload.facility.use)}
          {_incident_line("기준 위험도", payload.facility.risk)}
          {_incident_line("관할지역", payload.facility.region)}
          {facility_detail}
        </td>
      </tr>
    </tbody>
  </table>
  <section class="incident-section">
    <h2>3. 피해 현황</h2>
    <p class="incident-line">{_incident_value(payload.incident.damage)}</p>
  </section>
  <section class="incident-section">
    <h2>4. 조치 사항</h2>
    {_incident_numbered_lines(payload.response.actions)}
    {_incident_numbered_lines(payload.response.evidence)}
    {warning_line}
  </section>
  <section class="incident-section">
    <h2>5. 향후 계획</h2>
    {_incident_numbered_lines(payload.response.plan)}
  </section>
  <section class="incident-section">
    <h2>6. 참고 자료</h2>
    {_incident_numbered_lines(payload.evidence.references)}
    {attachments}
    {contact}
  </section>
</article>
</body>
</html>
"""


def _report_body(payload: DocumentPayload) -> str:
    return (
        _section(
            "사고 개요",
            _field("발생일시", payload.incident.occurred_at)
            + _field("발생장소", payload.incident.location)
            + _field("사고원인", payload.incident.cause)
            + f"<p>{_escaped(payload.incident.summary)}</p>"
            + f"<p>{_escaped(payload.incident.detail)}</p>",
        )
        + _section(
            "시설 현황",
            _field("시설명", payload.facility.name)
            + _field("주소", payload.facility.address)
            + _field("용도", payload.facility.use)
            + _field("기준 위험도", payload.facility.risk),
        )
        + _section("피해 현황", f"<p>{_escaped(payload.incident.damage)}</p>")
        + _section("조치 사항", _html_list(payload.response.actions))
        + _section("판단 근거", _html_list(payload.evidence.references))
        + _section("향후 계획", _html_list(payload.response.plan))
    )


def _crisis_body(payload: DocumentPayload) -> str:
    return (
        _section(
            "위기상황 개요",
            _field("재난유형", payload.incident.type)
            + _field("보고시각", payload.document.date)
            + _field("관계기관", payload.incident.agencies)
            + f"<p>{_escaped(payload.incident.summary)}</p>",
        )
        + _section("판단 근거", _html_list(payload.evidence.references))
        + _section("전파 대상", _html_list(payload.response.recipients))
        + _section("상황 모니터링", _html_list(payload.monitoring.signals))
        + _section(
            "위기상황 분석",
            f"<p>{_escaped(payload.analysis.result)}</p>"
            + _html_list(payload.analysis.uncertainties)
            + _html_list(payload.analysis.conflicts),
        )
        + _section("대응 조치", _html_list(payload.response.actions))
    )


def _notice_body(payload: DocumentPayload) -> str:
    return (
        '<div class="notice-meta">'
        + _field("수신", payload.notice.recipient)
        + _field("경유", payload.notice.delivery_route)
        + _field("제목", payload.document.title)
        + "</div>"
        + f"<p>{_escaped(payload.notice.opening)}</p>"
        + _section("관련 근거", _html_list(payload.notice.grounds))
        + _section("요청 사항", _html_list(payload.notice.request))
        + _field("제출·회신 기한", payload.notice.deadline)
        + _section("붙임", _html_list(payload.attachments.items))
        + '<div class="sender">한국전기안전공사 사장</div>'
    )


def _official_notice_html(payload: DocumentPayload, stage: ArtifactStage) -> str:
    warning = payload.review.warning if stage == "REVIEW" else ""
    warning_html = (
        f'<div class="official-warning">{_escaped(warning)}</div>' if warning else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{_escaped(payload.document.title)}</title>
<style>
@page {{ size: A4; margin: 18mm 18mm 15mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  color: #000;
  font-family: "Noto Serif CJK KR", "Batang", serif;
  font-size: 12pt;
  line-height: 1.65;
  word-break: keep-all;
}}
.official-document {{ width: 174mm; min-height: 264mm; margin: 0 auto; }}
.official-brand {{
  margin: 0 0 13mm;
  text-align: center;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 24pt;
  font-weight: 900;
  letter-spacing: 0.18em;
}}
.official-meta {{
  display: grid;
  grid-template-columns: 19mm 1fr;
  border-top: 0.35mm solid #000;
  border-bottom: 0.35mm solid #000;
}}
.official-meta dt,
.official-meta dd {{
  min-height: 9mm;
  margin: 0;
  padding: 1.3mm 2mm;
  border-bottom: 0.12mm solid #000;
}}
.official-meta dt {{ font-weight: 800; }}
.official-meta > :nth-last-child(-n + 2) {{ border-bottom: 0; }}
.official-title {{ font-weight: 800; }}
.official-body {{ min-height: 118mm; padding: 8mm 3mm 4mm; }}
.official-body p {{ margin: 0 0 5mm; white-space: pre-wrap; }}
.official-body h2 {{ margin: 5mm 0 1.5mm; font-size: 12pt; }}
.official-body ol {{ margin: 0 0 4mm; padding-left: 8mm; }}
.official-attachment {{ margin-top: 8mm; }}
.official-sender {{
  margin: 11mm 0 12mm;
  text-align: center;
  font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif;
  font-size: 18pt;
  font-weight: 900;
  letter-spacing: 0.12em;
}}
.official-admin {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 0.35mm solid #000;
  border-bottom: 0.35mm solid #000;
  font-size: 9.5pt;
}}
.official-admin div {{ min-height: 8mm; padding: 1.3mm 2mm; }}
.official-admin span {{ display: inline-block; min-width: 17mm; font-weight: 700; }}
.official-warning {{
  margin: 3mm 0;
  padding: 2mm 3mm;
  border: 0.2mm solid #8b1f1f;
  color: #7a1d1d;
  font-weight: 700;
}}
</style>
</head>
<body>
<article class="official-document">
  <h1 class="official-brand">한국전기안전공사</h1>
  <dl class="official-meta">
    <dt>수신</dt><dd>{_incident_value(payload.notice.recipient)}</dd>
    <dt>(경유)</dt><dd>{_incident_value(payload.notice.delivery_route)}</dd>
    <dt>제목</dt><dd class="official-title">{_escaped(payload.document.title)}</dd>
  </dl>
  <section class="official-body">
    <p>{_escaped(payload.notice.opening)}</p>
    <h2>1. 관련 근거</h2>
    {_html_list(payload.notice.grounds, empty_label="사용자 입력")}
    <h2>2. 요청 사항</h2>
    {_html_list(payload.notice.request, empty_label="사용자 입력")}
    <p>회신 기한: {_incident_value(payload.notice.deadline)}</p>
    <div class="official-attachment">
      <strong>붙임</strong>
      {_html_list(payload.attachments.items, empty_label="없음")}
    </div>
    {warning_html}
  </section>
  <div class="official-sender">한국전기안전공사 사장</div>
  <div class="official-admin">
    <div><span>문서번호</span>{_incident_value(payload.document.number)}</div>
    <div><span>시행일자</span>{_escaped(payload.document.date)}</div>
    <div><span>작성자</span>{_incident_value(payload.author.name)}</div>
    <div><span>승인자</span>{_incident_value(payload.author.approver)}</div>
    <div><span>전화</span>{_incident_value(payload.contact.phone)}</div>
    <div><span>전자우편</span>{_incident_value(payload.contact.email)}</div>
  </div>
</article>
</body>
</html>
"""


def _plan_body(payload: DocumentPayload) -> str:
    return (
        _section(
            "Ⅰ. 상황 개요 및 판단 근거",
            f"<p>{_escaped(payload.incident.summary)}</p>"
            + f"<p>{_escaped(payload.analysis.result)}</p>"
            + _html_list(payload.evidence.references),
        )
        + _section(
            "Ⅱ. 주요 대응 계획",
            f"<p>{_escaped(payload.response.summary)}</p>"
            + _html_list(payload.response.actions),
        )
        + _section("Ⅲ. 세부 실행 과제", _html_list(payload.response.plan))
        + _section(
            "Ⅳ. 상황관리 및 협업 체계",
            f"<p>{_escaped(payload.monitoring.summary)}</p>"
            + f"<p>{_escaped(payload.response.coordination)}</p>"
            + _html_list(payload.response.recipients),
        )
        + _section(
            "Ⅴ. 보고 및 승인 절차",
            f"<p>{_escaped(payload.response.reporting_procedure)}</p>"
            + f"<p>{_escaped(payload.response.approval_procedure)}</p>",
        )
    )


def render_document_html(payload: DocumentPayload, stage: ArtifactStage) -> str:
    if payload.variant in {"INCIDENT_REPORT", "REGION_ANALYSIS", "BUILDING_ANALYSIS"}:
        return _incident_report_html(payload, stage)
    if payload.variant in {"BASIC_NOTICE", "INSPECTION_REQUEST"}:
        return _official_notice_html(payload, stage)
    body_by_variant = {
        "INCIDENT_REPORT": _report_body,
        "CRISIS_ASSESSMENT": _crisis_body,
        "BASIC_NOTICE": _notice_body,
        "BASIC_PLAN": _plan_body,
        "REGION_ANALYSIS": _report_body,
        "BUILDING_ANALYSIS": _report_body,
        "INSPECTION_REQUEST": _notice_body,
    }
    warning = ""
    if stage == "REVIEW" and payload.review.warning:
        warning = f'<div class="warning">{_escaped(payload.review.warning)}</div>'
    body = body_by_variant[payload.variant](payload)
    admin = (
        '<div class="admin-grid">'
        + _field("문서번호", payload.document.number)
        + _field("작성자", payload.author.name)
        + _field("승인자", payload.author.approver)
        + _field("연락처", payload.contact.phone)
        + "</div>"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{_escaped(payload.document.title)}</title>
<style>
@page {{ size: A4; margin: 18mm 17mm 20mm; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; color: #111827; font-family: "Noto Sans CJK KR", "Noto Sans KR", sans-serif;
  font-size: 10.5pt; line-height: 1.58; word-break: keep-all;
}}
header {{ border-bottom: 2px solid #123b67; padding-bottom: 10px; margin-bottom: 18px; }}
.agency {{ color: #123b67; font-size: 11pt; font-weight: 700; letter-spacing: .03em; }}
h1 {{ margin: 7px 0 3px; text-align: center; font-size: 20pt; line-height: 1.35; }}
.document-date {{ text-align: center; color: #4b5563; }}
.warning {{ margin: 12px 0; padding: 10px 12px; border: 1px solid #d97706;
  background: #fffbeb; color: #92400e; font-weight: 700; }}
.admin-grid {{ display: grid; grid-template-columns: 1fr 1fr; border: 1px solid #9ca3af;
  margin: 12px 0 18px; }}
.admin-grid .field {{ border-bottom: 1px solid #d1d5db; }}
.field {{ display: flex; min-height: 28px; align-items: stretch; }}
.field-label {{ width: 100px; padding: 5px 8px; background: #f3f4f6; font-weight: 700; }}
.field-value {{ flex: 1; padding: 5px 8px; white-space: pre-wrap; }}
.blank-line {{ display: inline-block; width: 100%; min-height: 16px;
  border-bottom: 1px solid #9ca3af; }}
section {{ break-inside: avoid; margin: 0 0 17px; }}
h2 {{ margin: 0 0 8px; padding: 5px 8px; border-left: 4px solid #123b67;
  background: #eef4fa; font-size: 13pt; }}
p {{ margin: 6px 0; white-space: normal; }}
ol {{ margin: 5px 0; padding-left: 24px; }}
li {{ margin: 3px 0; white-space: normal; }}
.blank {{ min-height: 24px; border-bottom: 1px solid #d1d5db; }}
.sender {{ margin-top: 28px; text-align: right; font-size: 16pt; font-weight: 800; }}
</style>
</head>
<body>
<header>
  <div class="agency">한국전기안전공사</div>
  <h1>{_escaped(payload.document.title)}</h1>
  <div class="document-date">{_escaped(payload.document.date)}</div>
</header>
{warning}
{admin}
{body}
</body>
</html>
"""
