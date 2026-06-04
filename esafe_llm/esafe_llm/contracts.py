# -*- coding: utf-8 -*-
"""
데이터 계약(contract) 정의.

이 파일이 'CatBoost+SHAP 레이어'와 'LLM 레이어' 사이의 약속이다.
팀원 모델이 어떻게 생겼든, 최종적으로 SHAP 결과를 아래 RiskFactor 모양으로만
변환해주면 LLM/프론트 코드는 한 줄도 바꿀 필요가 없다.
"""
from typing import List, Optional, Union
from pydantic import BaseModel, Field


class RiskFactor(BaseModel):
    """SHAP으로 뽑은 위험 요인 1개. (모델 → LLM 으로 넘어가는 최소 단위)"""
    feature: str = Field(..., description="피처 식별자 예: bd_age, leak_count_3m")
    label: str = Field(..., description="사람이 읽는 한국어 표시명 예: 배전반 사용연수")
    value: Union[float, int, str, None] = Field(None, description="해당 건물의 실제 피처값 예: 28")
    unit: Optional[str] = Field(None, description="단위 예: 년, 회")
    contribution: float = Field(..., description="SHAP 기여도. +면 위험 상승, -면 하락")

    @property
    def direction(self) -> str:
        return "증가" if self.contribution >= 0 else "감소"


class BuildingExplainRequest(BaseModel):
    """기능 1: 개별 건물 위험원인 설명 요청."""
    building_id: Optional[str] = None
    address: Optional[str] = None
    predicted_score: float = Field(..., description="CatBoost 회귀 예측 위험 점수")
    grade: Optional[str] = Field(None, description="등급명 예: 고위험")
    factors: List[RiskFactor] = Field(default_factory=list, description="SHAP 상위 요인들")


class RegionBriefingRequest(BaseModel):
    """기능 3: 지역 단위 상황요약 브리핑 요청."""
    region_name: str = Field(..., description="예: 광주광역시 북구")
    building_count: Optional[int] = None
    avg_score: Optional[float] = None
    grade_distribution: Optional[dict] = Field(
        None, description='등급별 건물 수 예: {"위험":120,"경고":340,...}'
    )
    top_factors: List[RiskFactor] = Field(
        default_factory=list, description="지역 내 건물들의 SHAP을 집계한 공통 위험 요인"
    )
    notes: Optional[str] = Field(None, description="추가 맥락 예: 최근 2주 과부하 패턴 관측")


class LlmResponse(BaseModel):
    text: str
    model: str
    used_mock: bool = False


class SimilarCaseRequest(BaseModel):
    """기능 2: 유사 사고 사례 추천 요청."""
    query_text: Optional[str] = Field(None, description="직접 질의 텍스트(있으면 우선 사용)")
    address: Optional[str] = None
    grade: Optional[str] = None
    factors: List[RiskFactor] = Field(default_factory=list, description="현재 건물의 위험 요인")
    top_k: int = 3


class CaseHit(BaseModel):
    """검색된 사례 1건 (+유사도 점수)."""
    id: str
    title: str
    year: Optional[int] = None
    building_type: Optional[str] = None
    cause: Optional[str] = None
    response: Optional[str] = None
    damage: Optional[str] = None
    prevention: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    score: float = Field(..., description="코사인 유사도 0~1")


class SimilarCaseResponse(BaseModel):
    cases: List[CaseHit]
    summary: str = Field(..., description="LLM이 생성한 유사성 요약")
    model: str
    embed_model: str
