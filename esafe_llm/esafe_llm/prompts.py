# -*- coding: utf-8 -*-
"""
프롬프트 조립.

핵심 원칙: LLM은 '주어진 SHAP 숫자만' 근거로 쓰고, 없는 사실을 지어내지 않는다.
(공공기관 신뢰성 + hallucination 방지)
"""
from contracts import BuildingExplainRequest, RegionBriefingRequest

SIMILAR_SYSTEM_PROMPT = (
    "당신은 전기재해 대응을 돕는 한국어 보조원이다. "
    "아래에 주어진 '현재 건물 상태'와 '검색된 과거 사례'만 근거로 사용하고, "
    "사례에 없는 사실을 지어내지 마라. 간결한 관리자용 어조로 작성한다."
)

SYSTEM_PROMPT = (
    "당신은 전기재해 위험도 분석 결과를 설명하는 한국어 보조원이다. "
    "반드시 아래에 주어진 수치적 근거(SHAP 기여도)만 사용하고, "
    "근거에 없는 원인·수치·사례를 절대 지어내지 마라. "
    "전문 용어는 풀어쓰되 간결하게, 행정/관리자용 어조로 작성한다."
)


def _factor_lines(factors) -> str:
    lines = []
    for f in factors:
        sign = "+" if f.contribution >= 0 else ""
        if f.value is not None:
            val = f"{f.value}{f.unit or ''}"
            lines.append(
                f"- {f.label}: 실제값 {val} → 위험도 {sign}{f.contribution:.1f} 기여 (위험 {f.direction})"
            )
        else:
            lines.append(
                f"- {f.label}: 위험도 {sign}{f.contribution:.1f} 기여 (위험 {f.direction})"
            )
    return "\n".join(lines) if lines else "- (제공된 위험 요인 없음)"


def build_building_prompt(req: BuildingExplainRequest) -> str:
    head = f"예측 위험도: {req.predicted_score:.0f}점"
    if req.grade:
        head += f" ({req.grade})"
    if req.address:
        head = f"건물: {req.address}\n" + head
    return (
        f"{head}\n\n"
        f"모델이 이 건물을 그렇게 판단한 정량적 근거(SHAP):\n"
        f"{_factor_lines(req.factors)}\n\n"
        "위 근거만 사용하여 다음 형식으로 작성하라.\n"
        "주요 위험 원인: 기여도 큰 순으로 번호 매겨 1~3개.\n"
        "AI 분석 요약: 3~4문장의 자연스러운 한국어 설명."
    )


def build_region_prompt(req: RegionBriefingRequest) -> str:
    parts = [f"지역: {req.region_name}"]
    if req.building_count is not None:
        parts.append(f"대상 건물 수: {req.building_count}건")
    if req.avg_score is not None:
        parts.append(f"평균 위험도: {req.avg_score:.0f}점")
    if req.grade_distribution:
        dist = ", ".join(f"{k} {v}건" for k, v in req.grade_distribution.items())
        parts.append(f"등급 분포: {dist}")
    if req.notes:
        parts.append(f"추가 관측: {req.notes}")
    head = "\n".join(parts)
    return (
        f"{head}\n\n"
        f"이 지역 건물들에서 공통적으로 위험을 끌어올린 요인(SHAP 집계):\n"
        f"{_factor_lines(req.top_factors)}\n\n"
        "위 근거만 사용하여, 지역 단위 상황요약 브리핑을 4~6문장의 한국어로 작성하라. "
        "관리자가 한눈에 의사결정할 수 있도록 핵심 위험 요인과 그 영향을 중심으로 서술한다."
    )


def build_similar_prompt(query_text: str, case: dict) -> str:
    return (
        f"현재 건물 상태: {query_text}\n\n"
        "가장 유사한 과거 사례:\n"
        f"- 제목: {case.get('title', '-')}\n"
        f"- 원인: {case.get('cause', '-')}\n"
        f"- 대응: {case.get('response', '-')}\n"
        f"- 피해: {case.get('damage', '-')}\n"
        f"- 예방: {case.get('prevention', '-')}\n\n"
        "위 내용만 사용하여, '현재 상태는 ~사례와 유사합니다'로 시작하는 "
        "2~3문장의 한국어 요약을 작성하라. 어떤 점이 유사한지와 권장 대응 방향을 포함한다."
    )
