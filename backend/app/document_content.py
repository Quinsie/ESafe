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
}
VARIANT_FAMILIES: dict[DocumentVariant, str] = {
    "INCIDENT_REPORT": "SITUATION_REPORT",
    "CRISIS_ASSESSMENT": "SITUATION_REPORT",
    "BASIC_NOTICE": "OFFICIAL_NOTICE",
    "BASIC_PLAN": "RESPONSE_PLAN",
}
VARIANT_TITLES: dict[DocumentVariant, str] = {
    "INCIDENT_REPORT": "전기재해 사고·상황 보고서",
    "CRISIS_ASSESSMENT": "위기상황판단 평가보고서",
    "BASIC_NOTICE": "전기재해 예방 대응 협조 요청",
    "BASIC_PLAN": "전기재해 예방 대응 계획",
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
    case_id: str = Field(alias="caseId", min_length=36, max_length=36)
    case_number: ShortText = Field(alias="caseNumber")
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
    if payload.variant == "BASIC_NOTICE":
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
    body_by_variant = {
        "INCIDENT_REPORT": _report_body,
        "CRISIS_ASSESSMENT": _crisis_body,
        "BASIC_NOTICE": _notice_body,
        "BASIC_PLAN": _plan_body,
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
