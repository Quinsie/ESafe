from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.ai_control import AiCostGate
from app.config import Settings
from app.upstage import UpstageChatClient

PROMPT_VERSION = "case-recommendation-ko-v5"
GENERATION_VERSION = "recommendation-generator-v9"
ALLOWED_PRIVACY_STATUSES = frozenset(("PUBLIC_SAFE", "MASKED_VERIFIED"))
QUOTE_TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
QUOTE_STOP_WORDS = frozenset(
    {
        "관련",
        "근거",
        "공식",
        "현행",
        "확인",
        "필요",
        "문서",
        "매뉴얼",
        "행동",
        "조치",
        "내용",
        "적용",
    }
)
QUOTED_TERM_PATTERN = re.compile(r"'([^']+)'|‘([^’]+)’|\"([^\"]+)\"")
CONTRAST_MARKERS = ("하지만", "지만", "반면", "충돌", "불일치")
CHANGE_MARKERS = ("변경", "개정", "수정", "대체")
CASE_DOCUMENT_TERMS = {
    "FIRE": ("화재", "소방"),
    "WEATHER_WARNING": ("기상", "태풍", "호우", "폭염"),
    "DISASTER_MESSAGE": ("재난", "전기", "감전"),
}
KOREAN_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>'?\d{2}|\d{4})년\s*"
    r"(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
)
SEPARATED_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>'?\d{2}|\d{4})[./-]"
    r"(?P<month>\d{1,2})[./-](?P<day>\d{1,2})(?!\d)"
)
GENERIC_NUMBER_PATTERN = re.compile(
    r"(?<![\dA-Za-z])\d+(?:,\d{3})*(?:\.\d+)?(?![\dA-Za-z])"
)

SYSTEM_PROMPT = """
당신은 대한민국 공공기관의 전기재해 예방 관제 의사결정 보조자다.
사용자가 제공한 caseFacts와 evidence 이외의 사실, 기관, 문서, 조항, 수치, 연락처를 만들지 마라.
evidence의 evidenceItemId만 인용할 수 있다.
quote는 해당 evidence의 excerpt에서 글자 그대로 연속 복사해야 한다.
공식 현행 근거가 행동을 직접 뒷받침할 때만 SUFFICIENT로 제안하라.
과거 사고는 CASE_EXAMPLE, 타 지역 자료는 CONTEXT로만 사용하며 이것만으로 SUFFICIENT라 하지 마라.
근거가 부족하거나 충돌해도 대응 초안을 만들되 행동별 warning을 반드시 작성하라.
외부 기관 연락·현장 출동·문서 발송이 필요하다고 제안할 수는 있지만 실제 실행했다고 표현하지 마라.
응답은 설명이나 마크다운 없이 다음 구조의 JSON 객체 하나만 반환하라.
{
  "situationSummary": "문자열",
  "answerEvidenceStatus": "SUFFICIENT | INSUFFICIENT | CONFLICT",
  "answerWarning": "문자열 또는 null",
  "requiredChecks": ["문자열"],
  "uncertainties": ["문자열"],
  "conflicts": ["문자열"],
  "actions": [
    {
      "title": "문자열",
      "description": "문자열",
      "dueGuidance": "문자열 또는 null",
      "evidenceStatus": "SUFFICIENT | INSUFFICIENT | CONFLICT",
      "warning": "문자열 또는 null",
      "citations": [
        {
          "evidenceItemId": "입력에 있는 UUID",
          "supportType": "DIRECT | CONTEXT | CASE_EXAMPLE",
          "quote": "excerpt의 정확한 연속 부분"
        }
      ],
      "checklist": ["사용자가 확인할 구체적 항목"]
    }
  ]
}
actions는 가장 중요한 1~4개만, 각 checklist는 1~5개로 제한하라.
answerEvidenceStatus는 질문 또는 사건의 핵심 판단 전체에 대한 근거 상태다.
핵심 질문에 직접 답하는 공식 근거가 없으면 일반적인 다른 행동에 근거가 있더라도
INSUFFICIENT로 판정하라.
서로 다른 공식 현행 문서가 핵심 질문에 상충하면 CONFLICT로 판정하고
두 문서를 같은 행동에서 직접 인용하라.
한 공식 현행 문서가 용어나 내용을 변경하라고 명시하고 다른 공식 현행 문서의
해당 본문에 변경 전 용어나 내용이 그대로 남아 있으면 확인 가능성이 아니라
확인된 CONFLICT다. 이 경우 하나의 CONFLICT 행동에 두 문서의 정확한 excerpt를
각각 DIRECT로 인용하고 어느 한쪽을 임의로 적용하지 마라.
INSUFFICIENT 또는 CONFLICT이면 answerWarning을 반드시 작성하라.
모든 문장은 한국어로 간결하게 작성하라.
""".strip()


class RecommendationGenerationError(RuntimeError):
    pass


class CitationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    evidence_item_id: UUID = Field(alias="evidenceItemId")
    support_type: Literal["DIRECT", "CONTEXT", "CASE_EXAMPLE"] = Field(
        alias="supportType"
    )
    quote: str = Field(min_length=1, max_length=1200)


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1200)
    due_guidance: str | None = Field(default=None, alias="dueGuidance", max_length=160)
    evidence_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"] = Field(
        alias="evidenceStatus"
    )
    warning: str | None = Field(default=None, max_length=600)
    citations: list[CitationProposal] = Field(default_factory=list, max_length=8)
    checklist: list[str] = Field(min_length=1, max_length=5)


class RecommendationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    situation_summary: str = Field(
        alias="situationSummary", min_length=1, max_length=1000
    )
    answer_evidence_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"] = Field(
        alias="answerEvidenceStatus"
    )
    answer_warning: str | None = Field(
        default=None,
        alias="answerWarning",
        max_length=600,
    )
    required_checks: list[str] = Field(
        alias="requiredChecks", default_factory=list, max_length=8
    )
    uncertainties: list[str] = Field(default_factory=list, max_length=8)
    conflicts: list[str] = Field(default_factory=list, max_length=8)
    actions: list[ActionProposal] = Field(min_length=1, max_length=4)


@dataclass(frozen=True, slots=True)
class ValidatedCitation:
    evidence_item_id: UUID
    support_type: Literal["DIRECT", "CONTEXT", "CASE_EXAMPLE"]
    quote: str
    locator: str


@dataclass(frozen=True, slots=True)
class ValidatedAction:
    title: str
    description: str
    due_guidance: str | None
    evidence_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"]
    warning: str | None
    citations: tuple[ValidatedCitation, ...]
    checklist: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedRecommendation:
    situation_summary: str
    required_checks: tuple[str, ...]
    uncertainties: tuple[str, ...]
    conflicts: tuple[str, ...]
    actions: tuple[ValidatedAction, ...]
    evidence_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"]
    warning: str | None


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"unsupported JSON type: {type(value).__name__}")


def _clean_texts(values: list[str], *, maximum: int) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not normalized:
            continue
        result.append(normalized[:maximum])
    return tuple(dict.fromkeys(result))


def _recover_whitespace_exact_quote(quote: str, excerpt: str) -> str | None:
    parts = quote.split()
    if not parts:
        return None
    match = re.search(r"\s+".join(re.escape(part) for part in parts), excerpt)
    return match.group(0) if match is not None else None


def _quote_has_grounded_token_alignment(quote: str, excerpt: str) -> bool:
    quote_tokens = {
        token.lower()
        for token in QUOTE_TOKEN_PATTERN.findall(quote)
        if token.lower() not in QUOTE_STOP_WORDS
    }
    if len(quote_tokens) < 2:
        return False
    excerpt_tokens = {
        token.lower() for token in QUOTE_TOKEN_PATTERN.findall(excerpt)
    }
    matched = quote_tokens & excerpt_tokens
    return len(matched) >= 2 and len(matched) / len(quote_tokens) >= 0.5


def _exact_evidence_window(excerpt: str, terms: tuple[str, ...]) -> str:
    positions = [excerpt.find(term) for term in terms if term and term in excerpt]
    marker = min(positions) if positions else 0
    start = max(0, marker - 240)
    end = min(len(excerpt), marker + 560)
    return excerpt[start:end].strip()


def _detect_explicit_amendment_conflict(
    *,
    case_title: str | None,
    case_type: str | None,
    evidence_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
    if not case_title or not any(marker in case_title for marker in CONTRAST_MARKERS):
        return None
    quoted_terms = [
        next(value for value in match if value)
        for match in QUOTED_TERM_PATTERN.findall(case_title)
    ]
    quoted_terms = list(dict.fromkeys(quoted_terms))
    if len(quoted_terms) != 2:
        return None
    old_term, new_term = quoted_terms
    official = [
        row
        for row in evidence_rows
        if str(row["evidence_group"]) == "OFFICIAL"
        and str(row["current_status"]) == "CURRENT"
    ]
    directives = [
        row
        for row in official
        if old_term in str(row["excerpt"])
        and new_term in str(row["excerpt"])
        and any(marker in str(row["excerpt"]) for marker in CHANGE_MARKERS)
    ]
    if not directives:
        return None
    document_terms = CASE_DOCUMENT_TERMS.get(str(case_type), ())
    affected = [
        row
        for row in official
        if old_term in str(row["excerpt"])
        and new_term not in str(row["excerpt"])
        and str(row["document_id"]) != str(directives[0]["document_id"])
    ]
    if not affected:
        return None

    def affected_score(row: dict[str, Any]) -> tuple[int, int]:
        searchable = " ".join(
            (
                str(row.get("document_title") or ""),
                " ".join(str(value) for value in row.get("disaster_types") or []),
                str(row["excerpt"]),
            )
        )
        context_score = sum(
            term in searchable for term in ("영상회의", "참여기관", "상황판단회의")
        )
        type_score = sum(term in searchable for term in document_terms)
        return context_score + type_score, -int(row.get("rank") or 9999)

    affected.sort(key=affected_score, reverse=True)
    chosen = affected[0]
    if affected_score(chosen)[0] < 2:
        return None
    directive = directives[0]
    directive_quote = _exact_evidence_window(
        str(directive["excerpt"]),
        (old_term, new_term),
    )
    affected_quote = _exact_evidence_window(
        str(chosen["excerpt"]),
        (old_term, "영상회의", "참여기관"),
    )
    if not directive_quote or not affected_quote:
        return None
    return directive, chosen, directive_quote, affected_quote


def _canonical_year(value: str) -> int:
    digits = value.lstrip("'")
    year = int(digits)
    return year + 2000 if len(digits) == 2 else year


def _numeric_claim_spans(value: str) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in (KOREAN_DATE_PATTERN, SEPARATED_DATE_PATTERN):
        for match in pattern.finditer(value):
            start, end = match.span()
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            year = _canonical_year(match.group("year"))
            month = int(match.group("month"))
            day = int(match.group("day"))
            spans.append(
                (
                    start,
                    end,
                    f"date:{year:04d}-{month:02d}-{day:02d}",
                    "date",
                )
            )
            spans.append((start, end, f"num:{year}", "year"))
            occupied.append((start, end))
    for match in GENERIC_NUMBER_PATTERN.finditer(value):
        start, end = match.span()
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        normalized = match.group(0).replace(",", "")
        spans.append((start, end, f"num:{normalized}", "number"))
    return spans


def _numeric_claims(value: str) -> set[str]:
    return {claim for _, _, claim, _ in _numeric_claim_spans(value)}


def _sanitize_unsupported_numeric_claims(
    value: str | None,
    allowed_claims: set[str],
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    replacements = [
        (
            start,
            end,
            "근거 확인 필요 시점" if kind == "date" else "근거 확인 필요 수치",
        )
        for start, end, claim, kind in _numeric_claim_spans(value)
        if claim not in allowed_claims and kind != "year"
    ]
    if not replacements:
        return value, False
    sanitized = value
    for start, end, replacement in sorted(replacements, reverse=True):
        sanitized = sanitized[:start] + replacement + sanitized[end:]
    return sanitized, True


def _sanitize_required_numeric_claims(
    value: str,
    allowed_claims: set[str],
) -> tuple[str, bool]:
    sanitized, changed = _sanitize_unsupported_numeric_claims(value, allowed_claims)
    if sanitized is None:
        raise AssertionError("required text cannot become null")
    return sanitized, changed


def _sanitize_proposal_numeric_claims(
    proposal: RecommendationProposal,
    evidence_rows: list[dict[str, Any]],
    case_title: str | None,
) -> None:
    allowed_claims = _numeric_claims(case_title or "")
    for row in evidence_rows:
        allowed_claims.update(
            _numeric_claims(
                " ".join(
                    (
                        str(row.get("excerpt") or ""),
                        str(row.get("locator") or ""),
                        str(row.get("document_title") or ""),
                        str(row.get("document_number") or ""),
                        str(row.get("published_at") or ""),
                    )
                )
            )
        )
    changed = False
    proposal.situation_summary, summary_changed = _sanitize_required_numeric_claims(
        proposal.situation_summary,
        allowed_claims,
    )
    changed |= summary_changed
    for attribute in ("required_checks", "uncertainties", "conflicts"):
        values = getattr(proposal, attribute)
        sanitized_values: list[str] = []
        for value in values:
            sanitized, value_changed = _sanitize_required_numeric_claims(
                value,
                allowed_claims,
            )
            sanitized_values.append(sanitized)
            changed |= value_changed
        setattr(proposal, attribute, sanitized_values)
    for action in proposal.actions:
        action.title, title_changed = _sanitize_required_numeric_claims(
            action.title,
            allowed_claims,
        )
        action.description, description_changed = _sanitize_required_numeric_claims(
            action.description,
            allowed_claims,
        )
        action.due_guidance, due_changed = _sanitize_unsupported_numeric_claims(
            action.due_guidance,
            allowed_claims,
        )
        sanitized_checklist: list[str] = []
        checklist_changed = False
        for value in action.checklist:
            sanitized, value_changed = _sanitize_required_numeric_claims(
                value,
                allowed_claims,
            )
            sanitized_checklist.append(sanitized)
            checklist_changed |= value_changed
        action.checklist = sanitized_checklist
        action_changed = (
            title_changed
            or description_changed
            or due_changed
            or checklist_changed
        )
        if action_changed:
            action.evidence_status = "INSUFFICIENT"
            action.warning = (
                "근거에서 확인되지 않은 수치를 초안에서 제거했습니다."
            )
        changed |= action_changed
    if changed:
        proposal.answer_evidence_status = "INSUFFICIENT"
        proposal.answer_warning = (
            "근거에서 확인되지 않은 수치를 초안에서 제거했습니다."
        )


def recommendation_response_schema(
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    schema = RecommendationProposal.model_json_schema(by_alias=True)
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise RecommendationGenerationError("RECOMMENDATION_SCHEMA_INVALID")
    citation = definitions.get("CitationProposal")
    if not isinstance(citation, dict):
        raise RecommendationGenerationError("RECOMMENDATION_SCHEMA_INVALID")
    properties = citation.get("properties")
    if not isinstance(properties, dict):
        raise RecommendationGenerationError("RECOMMENDATION_SCHEMA_INVALID")
    evidence_item_id = properties.get("evidenceItemId")
    if not isinstance(evidence_item_id, dict):
        raise RecommendationGenerationError("RECOMMENDATION_SCHEMA_INVALID")
    allowed_ids = sorted(
        {str(UUID(str(item["evidence_item_id"]))) for item in evidence_rows}
    )
    if not allowed_ids:
        raise RecommendationGenerationError("EVIDENCE_ITEMS_REQUIRED")
    evidence_item_id["enum"] = allowed_ids
    return schema


def validate_recommendation_payload(
    payload: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    *,
    case_title: str | None = None,
    case_type: str | None = None,
) -> ValidatedRecommendation:
    try:
        proposal = RecommendationProposal.model_validate(payload)
    except ValidationError as error:
        raise RecommendationGenerationError(
            "RECOMMENDATION_OUTPUT_SCHEMA_INVALID"
        ) from error
    _sanitize_proposal_numeric_claims(proposal, evidence_rows, case_title)
    evidence = {UUID(str(item["evidence_item_id"])): item for item in evidence_rows}
    validated_actions: list[ValidatedAction] = []
    for proposed_action in proposal.actions:
        citations: list[ValidatedCitation] = []
        seen: set[tuple[UUID, str]] = set()
        normalized_quote = False
        for citation in proposed_action.citations:
            item = evidence.get(citation.evidence_item_id)
            quote = citation.quote.strip()
            if item is None:
                continue
            excerpt = str(item["excerpt"])
            quote_is_exact = bool(quote and quote in excerpt)
            quote_is_grounded = quote_is_exact
            if not quote_is_exact:
                recovered_quote = _recover_whitespace_exact_quote(quote, excerpt)
                if recovered_quote is not None:
                    quote = recovered_quote
                    quote_is_exact = True
                    quote_is_grounded = True
            if not quote_is_exact:
                quote_is_grounded = _quote_has_grounded_token_alignment(
                    quote,
                    excerpt,
                )
                quote = excerpt[:1200].strip()
                if not quote:
                    continue
                normalized_quote = True
            group = str(item["evidence_group"])
            support_type = citation.support_type
            if group == "PAST_INCIDENT":
                support_type = "CASE_EXAMPLE"
            elif (not quote_is_exact and not quote_is_grounded) or (
                support_type == "DIRECT"
                and (
                    group != "OFFICIAL"
                    or str(item["current_status"]) != "CURRENT"
                )
            ):
                support_type = "CONTEXT"
            key = (citation.evidence_item_id, quote)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                ValidatedCitation(
                    evidence_item_id=citation.evidence_item_id,
                    support_type=support_type,
                    quote=quote,
                    locator=str(item["locator"]),
                )
            )
        direct_official_documents = {
            str(evidence[item.evidence_item_id]["document_id"])
            for item in citations
            if item.support_type == "DIRECT"
        }
        warning: str | None
        if (
            proposed_action.evidence_status == "CONFLICT"
            and len(direct_official_documents) >= 2
        ):
            evidence_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"] = (
                "CONFLICT"
            )
            warning = (
                proposed_action.warning
                or "공식 현행 근거 사이의 충돌을 확인한 뒤 행동을 승인해야 합니다."
            )
        elif direct_official_documents:
            evidence_status = "SUFFICIENT"
            warning = proposed_action.warning
        else:
            evidence_status = "INSUFFICIENT"
            warning = (
                proposed_action.warning
                or (
                    "AI가 제시한 인용문을 원문에서 확인하지 못해 "
                    "검증된 원문을 참고 근거로만 표시했습니다."
                    if normalized_quote
                    else None
                )
                or "이 행동을 직접 뒷받침하는 공식 현행 근거가 부족합니다."
            )
        checklist = _clean_texts(proposed_action.checklist, maximum=240)
        if not checklist:
            checklist = (f"{proposed_action.title.strip()} 결과를 기록합니다.",)
        validated_actions.append(
            ValidatedAction(
                title=" ".join(proposed_action.title.split()),
                description=" ".join(proposed_action.description.split()),
                due_guidance=(
                    " ".join(proposed_action.due_guidance.split())
                    if proposed_action.due_guidance
                    else None
                ),
                evidence_status=evidence_status,
                warning=warning,
                citations=tuple(citations),
                checklist=checklist,
            )
        )
    detected_conflict = _detect_explicit_amendment_conflict(
        case_title=case_title,
        case_type=case_type,
        evidence_rows=evidence_rows,
    )
    if detected_conflict is not None:
        directive, affected, directive_quote, affected_quote = detected_conflict
        old_term, new_term = [
            next(value for value in match if value)
            for match in QUOTED_TERM_PATTERN.findall(str(case_title))
        ]
        validated_actions = [
            ValidatedAction(
                title="공식 문서 간 용어 충돌 확인",
                description=(
                    f"{old_term}에서 {new_term}(으)로의 변경 지시와 "
                    f"변경 전 {old_term} 표기를 함께 확인합니다."
                ),
                due_guidance=None,
                evidence_status="CONFLICT",
                warning=(
                    "상충하는 공식 현행 근거 중 어느 한쪽을 임의로 적용하지 마십시오."
                ),
                citations=(
                    ValidatedCitation(
                        evidence_item_id=UUID(str(directive["evidence_item_id"])),
                        support_type="DIRECT",
                        quote=directive_quote,
                        locator=str(directive["locator"]),
                    ),
                    ValidatedCitation(
                        evidence_item_id=UUID(str(affected["evidence_item_id"])),
                        support_type="DIRECT",
                        quote=affected_quote,
                        locator=str(affected["locator"]),
                    ),
                ),
                checklist=(
                    "두 공식 문서의 개정 이력과 적용 시점을 확인합니다.",
                    "적용할 용어와 사유를 기록합니다.",
                ),
            )
        ]

    direct_official_documents = {
        str(evidence[citation.evidence_item_id]["document_id"])
        for action in validated_actions
        for citation in action.citations
        if citation.support_type == "DIRECT"
    }
    overall_status: Literal["SUFFICIENT", "INSUFFICIENT", "CONFLICT"]
    overall_warning: str | None
    conflicts: tuple[str, ...]
    if detected_conflict is not None:
        overall_status = "CONFLICT"
        overall_warning = (
            "공식 변경 지시와 변경 전 현행 본문이 함께 확인되어 "
            "적용 기준 확인이 필요합니다."
        )
        conflicts = (
            "서로 다른 공식 현행 문서에서 변경 지시와 변경 전 표기가 동시에 확인됩니다.",
        )
    elif (
        proposal.answer_evidence_status == "CONFLICT"
        and len(direct_official_documents) >= 2
        and any(
            action.evidence_status == "CONFLICT" for action in validated_actions
        )
    ):
        overall_status = "CONFLICT"
        overall_warning = (
            proposal.answer_warning
            or "상충하는 공식 근거가 있어 사용자 확인과 사유 기록이 필요합니다."
        )
        conflicts = _clean_texts(proposal.conflicts, maximum=500)
    elif (
        proposal.answer_evidence_status == "SUFFICIENT"
        and all(
            action.evidence_status == "SUFFICIENT" for action in validated_actions
        )
    ):
        overall_status = "SUFFICIENT"
        overall_warning = proposal.answer_warning
        conflicts = ()
    else:
        overall_status = "INSUFFICIENT"
        overall_warning = (
            proposal.answer_warning
            or "핵심 판단 또는 일부 제안 행동의 직접 공식 근거가 부족합니다."
        )
        conflicts = ()
    return ValidatedRecommendation(
        situation_summary=" ".join(proposal.situation_summary.split()),
        required_checks=_clean_texts(proposal.required_checks, maximum=400),
        uncertainties=_clean_texts(proposal.uncertainties, maximum=500),
        conflicts=conflicts,
        actions=tuple(validated_actions),
        evidence_status=overall_status,
        warning=overall_warning,
    )


async def _fetch_context(
    connection: AsyncConnection,
    case_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    case_row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT c.case_id, c.case_number, c.case_type, c.title, c.status,
                           c.source_status, c.monitoring_priority,
                           c.primary_region_code, region.full_name AS region_name,
                           c.is_simulated, c.version,
                           coalesce(impact.impact_count, 0) AS impact_count,
                           coalesce(impact.high_risk_count, 0) AS high_risk_count,
                           coalesce(impact.incident_count, 0) AS incident_count
                    FROM case_record c
                    LEFT JOIN admin_region region
                      ON region.region_code = c.primary_region_code
                    LEFT JOIN LATERAL (
                        SELECT count(1) AS impact_count,
                               count(1) FILTER (WHERE is_high_risk) AS high_risk_count,
                               count(1) FILTER (
                                   WHERE is_incident_building
                               ) AS incident_count
                        FROM case_building
                        WHERE case_id = c.case_id
                    ) impact ON true
                    WHERE c.case_id = :case_id
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if case_row is None:
        return None
    bundle = (
        (
            await connection.execute(
                text(
                    """
                    SELECT evidence_bundle_id, version, status, index_version_id,
                           query_text, created_at
                    FROM evidence_bundle
                    WHERE case_id = :case_id AND is_current
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if bundle is None:
        raise RecommendationGenerationError("EVIDENCE_BUNDLE_REQUIRED")
    rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT item.evidence_item_id, item.evidence_group, item.rank,
                           item.current_status, item.excerpt, item.locator,
                           document.document_id, document.title AS document_title,
                           document.issuing_agency, document.document_number,
                           document.published_at, document.privacy_status,
                           document.disaster_types
                    FROM evidence_item item
                    JOIN rag_chunk chunk ON chunk.chunk_id = item.chunk_id
                    JOIN rag_document document
                      ON document.document_id = chunk.document_id
                    WHERE item.evidence_bundle_id = :bundle_id
                    ORDER BY
                      CASE item.evidence_group
                        WHEN 'OFFICIAL' THEN 0
                        WHEN 'PAST_INCIDENT' THEN 1
                        ELSE 2
                      END,
                      item.rank
                    """
                ),
                {"bundle_id": bundle["evidence_bundle_id"]},
            )
        )
        .mappings()
        .all()
    )
    evidence_rows = [dict(row) for row in rows]
    if any(
        str(item["privacy_status"]) not in ALLOWED_PRIVACY_STATUSES
        for item in evidence_rows
    ):
        raise RecommendationGenerationError("EVIDENCE_PRIVACY_NOT_VERIFIED")
    return dict(case_row), dict(bundle), evidence_rows


def _build_input(
    settings: Settings,
    case_row: dict[str, Any],
    bundle: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    factual_snapshot = {
        "caseNumber": case_row["case_number"],
        "caseTitle": case_row["title"],
        "caseType": case_row["case_type"],
        "caseStatus": case_row["status"],
        "sourceStatus": case_row["source_status"],
        "monitoringPriority": case_row["monitoring_priority"],
        "regionCode": case_row["primary_region_code"],
        "regionName": case_row["region_name"],
        "isSimulated": bool(case_row["is_simulated"]),
        "caseVersion": int(case_row["version"]),
        "impactBuildingCount": int(case_row["impact_count"]),
        "highRiskBuildingCount": int(case_row["high_risk_count"]),
        "incidentBuildingCount": int(case_row["incident_count"]),
        "evidenceBundleId": str(bundle["evidence_bundle_id"]),
        "evidenceBundleVersion": int(bundle["version"]),
        "retrievalQuery": bundle["query_text"],
    }
    safe_input = {
        "caseFacts": factual_snapshot,
        "evidence": [
            {
                "evidenceItemId": str(item["evidence_item_id"]),
                "group": item["evidence_group"],
                "rank": int(item["rank"]),
                "currentStatus": item["current_status"],
                "documentTitle": item["document_title"],
                "issuingAgency": item["issuing_agency"],
                "documentNumber": item["document_number"],
                "publishedAt": (
                    item["published_at"].isoformat()
                    if item["published_at"] is not None
                    else None
                ),
                "excerpt": item["excerpt"],
                "locator": item["locator"],
            }
            for item in evidence_rows
        ],
    }
    input_sha256 = _canonical_hash(
        {
            "model": settings.upstage_chat_model,
            "promptVersion": PROMPT_VERSION,
            "input": safe_input,
        }
    )
    return factual_snapshot, json.dumps(
        safe_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ), input_sha256


def _validated_output(value: ValidatedRecommendation) -> dict[str, Any]:
    return {
        "situationSummary": value.situation_summary,
        "requiredChecks": list(value.required_checks),
        "uncertainties": list(value.uncertainties),
        "conflicts": list(value.conflicts),
        "evidenceStatus": value.evidence_status,
        "warning": value.warning,
        "actions": [
            {
                "title": action.title,
                "description": action.description,
                "dueGuidance": action.due_guidance,
                "evidenceStatus": action.evidence_status,
                "warning": action.warning,
                "citations": [
                    {
                        "evidenceItemId": str(citation.evidence_item_id),
                        "supportType": citation.support_type,
                        "quote": citation.quote,
                        "locator": citation.locator,
                    }
                    for citation in action.citations
                ],
                "checklist": list(action.checklist),
            }
            for action in value.actions
        ],
    }


async def _persist_recommendation(
    connection: AsyncConnection,
    *,
    settings: Settings,
    case_id: UUID,
    case_version: int,
    evidence_bundle_id: UUID,
    factual_snapshot: dict[str, Any],
    input_sha256: str,
    value: ValidatedRecommendation,
) -> tuple[str, UUID, int]:
    locked = (
        (
            await connection.execute(
                text(
                    """
                    SELECT c.version,
                           bundle.evidence_bundle_id
                    FROM case_record c
                    LEFT JOIN evidence_bundle bundle
                      ON bundle.case_id = c.case_id AND bundle.is_current
                    WHERE c.case_id = :case_id
                    FOR UPDATE OF c
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        locked is None
        or int(locked["version"]) != case_version
        or locked["evidence_bundle_id"] != evidence_bundle_id
    ):
        return "STALE_INPUT", UUID(int=0), 0
    existing = (
        (
            await connection.execute(
                text(
                    """
                    SELECT recommendation_id, version, input_sha256
                    FROM recommendation
                    WHERE case_id = :case_id
                      AND status IN ('DRAFT', 'READY')
                    FOR UPDATE
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None and existing["input_sha256"] == input_sha256:
        return "SKIPPED", existing["recommendation_id"], int(existing["version"])
    if existing is not None:
        await connection.execute(
            text(
                """
                UPDATE recommendation
                SET status = 'SUPERSEDED', superseded_at = CURRENT_TIMESTAMP
                WHERE recommendation_id = :recommendation_id
                """
            ),
            {"recommendation_id": existing["recommendation_id"]},
        )
    version_result = await connection.execute(
        text(
            """
            SELECT coalesce(max(version), 0) + 1
            FROM recommendation
            WHERE case_id = :case_id
            """
        ),
        {"case_id": case_id},
    )
    version = int(version_result.scalar_one())
    recommendation_id = uuid4()
    output = _validated_output(value)
    output_sha256 = _canonical_hash(output)
    await connection.execute(
        text(
            """
            INSERT INTO recommendation (
                recommendation_id, case_id, evidence_bundle_id, version,
                status, generation_mode, factual_snapshot, situation_summary,
                required_checks, uncertainties, conflicts, warning, model,
                prompt_version, generation_version, input_sha256, output_sha256
            )
            VALUES (
                :recommendation_id, :case_id, :evidence_bundle_id, :version,
                'READY', 'AI', CAST(:factual_snapshot AS jsonb), :situation_summary,
                CAST(:required_checks AS jsonb), CAST(:uncertainties AS jsonb),
                CAST(:conflicts AS jsonb), :warning, :model, :prompt_version,
                :generation_version, :input_sha256, :output_sha256
            )
            """
        ),
        {
            "recommendation_id": recommendation_id,
            "case_id": case_id,
            "evidence_bundle_id": evidence_bundle_id,
            "version": version,
            "factual_snapshot": json.dumps(
                factual_snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "situation_summary": value.situation_summary,
            "required_checks": json.dumps(
                list(value.required_checks), ensure_ascii=False
            ),
            "uncertainties": json.dumps(
                list(value.uncertainties), ensure_ascii=False
            ),
            "conflicts": json.dumps(list(value.conflicts), ensure_ascii=False),
            "warning": value.warning,
            "model": settings.upstage_chat_model,
            "prompt_version": PROMPT_VERSION,
            "generation_version": GENERATION_VERSION,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        },
    )
    direct_citations = 0
    for ordinal, action in enumerate(value.actions, start=1):
        action_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO recommendation_action (
                    recommendation_action_id, recommendation_id, ordinal,
                    title, description, due_guidance, evidence_status,
                    warning, checklist_template
                )
                VALUES (
                    :action_id, :recommendation_id, :ordinal, :title,
                    :description, :due_guidance, :evidence_status, :warning,
                    CAST(:checklist_template AS jsonb)
                )
                """
            ),
            {
                "action_id": action_id,
                "recommendation_id": recommendation_id,
                "ordinal": ordinal,
                "title": action.title,
                "description": action.description,
                "due_guidance": action.due_guidance,
                "evidence_status": action.evidence_status,
                "warning": action.warning,
                "checklist_template": json.dumps(
                    list(action.checklist), ensure_ascii=False
                ),
            },
        )
        for citation in action.citations:
            direct_citations += citation.support_type == "DIRECT"
            await connection.execute(
                text(
                    """
                    INSERT INTO evidence_citation (
                        citation_id, recommendation_action_id, evidence_item_id,
                        support_type, quote_text, locator
                    )
                    VALUES (
                        :citation_id, :action_id, :evidence_item_id,
                        :support_type, :quote_text, :locator
                    )
                    """
                ),
                {
                    "citation_id": uuid4(),
                    "action_id": action_id,
                    "evidence_item_id": citation.evidence_item_id,
                    "support_type": citation.support_type,
                    "quote_text": citation.quote,
                    "locator": citation.locator,
                },
            )
    await connection.execute(
        text(
            """
            UPDATE evidence_bundle
            SET status = :status,
                warning = :warning,
                direct_citation_count = :direct_citation_count
            WHERE evidence_bundle_id = :bundle_id
            """
        ),
        {
            "bundle_id": evidence_bundle_id,
            "status": value.evidence_status,
            "warning": value.warning,
            "direct_citation_count": direct_citations,
        },
    )
    return "SUCCESS", recommendation_id, version


async def run_case_recommendation(
    settings: Settings,
    case_id: UUID,
) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    gate = AiCostGate(settings)
    try:
        async with engine.connect() as connection:
            context = await _fetch_context(connection, case_id)
        if context is None:
            raise RecommendationGenerationError("CASE_NOT_FOUND")
        case_row, bundle, evidence_rows = context
        factual_snapshot, user_prompt, input_sha256 = _build_input(
            settings, case_row, bundle, evidence_rows
        )
        async with engine.connect() as connection:
            existing = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT recommendation_id, version
                            FROM recommendation
                            WHERE case_id = :case_id
                              AND status IN ('DRAFT', 'READY')
                              AND input_sha256 = :input_sha256
                            """
                        ),
                        {"case_id": case_id, "input_sha256": input_sha256},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if existing is not None:
            return {
                "status": "SKIPPED",
                "caseId": str(case_id),
                "recommendationId": str(existing["recommendation_id"]),
                "version": int(existing["version"]),
                "externalCall": False,
            }
        chat_result = await UpstageChatClient(settings, gate).complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            feature_name="case-recommendation-v1",
            privacy_verified=True,
            case_reference=case_id,
            response_schema=None,
        )
        value = validate_recommendation_payload(
            chat_result.payload,
            evidence_rows,
            case_title=str(case_row["title"]),
            case_type=str(case_row["case_type"]),
        )
        async with engine.begin() as connection:
            status, recommendation_id, version = await _persist_recommendation(
                connection,
                settings=settings,
                case_id=case_id,
                case_version=int(case_row["version"]),
                evidence_bundle_id=UUID(str(bundle["evidence_bundle_id"])),
                factual_snapshot=factual_snapshot,
                input_sha256=input_sha256,
                value=value,
            )
        return {
            "status": status,
            "caseId": str(case_id),
            "recommendationId": (
                str(recommendation_id) if recommendation_id.int else None
            ),
            "version": version or None,
            "evidenceStatus": value.evidence_status,
            "actionCount": len(value.actions),
            "directCitationCount": sum(
                citation.support_type == "DIRECT"
                for action in value.actions
                for citation in action.citations
            ),
            "externalCall": True,
            "inputTokens": chat_result.input_tokens,
            "cachedInputTokens": chat_result.cached_input_tokens,
            "outputTokens": chat_result.output_tokens,
            "reservationId": chat_result.reservation_id,
        }
    finally:
        await gate.close()
        await engine.dispose()
