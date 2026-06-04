# -*- coding: utf-8 -*-
"""
SHAP 위험요인 추출기.

★ 팀원의 CatBoost 모델이 나오면, 이 파일만 고치면 된다. ★
나머지(LLM/프론트)는 RiskFactor 계약만 지키면 그대로 동작한다.

지금은 모델이 없으므로 mock 데이터를 돌려준다.
"""
import os
from typing import List
from contracts import RiskFactor

USE_MOCK = os.environ.get("ESAFE_LLM_USE_MOCK", "1") == "1"

# 모델 나온 뒤 채울 것: 피처 식별자 → 한국어 표시명/단위 매핑 (160개)
FEATURE_LABELS = {
    "bd_age": ("배전반 사용연수", "년"),
    "leak_count_3m": ("최근 3개월 누전 발생", "회"),
    "use_zone": ("용도지역", None),
    "fire_history": ("전기화재 이력", "건"),
    "summer_load": ("여름철 과부하 예상", None),
}


def _mock_building_factors() -> List[RiskFactor]:
    return [
        RiskFactor(feature="bd_age", label="배전반 사용연수", value=28, unit="년", contribution=12.4),
        RiskFactor(feature="leak_count_3m", label="최근 3개월 누전 발생", value=4, unit="회", contribution=8.1),
        RiskFactor(feature="summer_load", label="여름철 과부하 예상", value="높음", contribution=3.2),
        RiskFactor(feature="use_zone", label="용도지역(공업)", value="공업", contribution=2.1),
    ]


def _mock_region_factors() -> List[RiskFactor]:
    return [
        RiskFactor(feature="industrial_load", label="산업용 전력 사용량 증가", value="상승", contribution=9.7),
        RiskFactor(feature="aged_switchboard_ratio", label="노후 배전 설비 비율", value="높음", contribution=7.3),
        RiskFactor(feature="overload_pattern_2w", label="최근 2주 과부하 패턴 반복", value=11, unit="회", contribution=5.5),
    ]


# --- 아래 두 함수가 LLM 레이어가 호출하는 진짜 진입점 ---

def building_factors(building_id: str, top_k: int = 4) -> List[RiskFactor]:
    """건물 1건의 상위 위험요인. (모델 연결 후: SHAP 계산 → 상위 top_k 반환)"""
    if USE_MOCK:
        return _mock_building_factors()[:top_k]
    raise NotImplementedError(
        "CatBoost 모델 연결 필요. 아래 _real 예시 참고 후 ESAFE_LLM_USE_MOCK=0 설정"
    )


def region_factors(region_name: str, top_k: int = 3) -> List[RiskFactor]:
    """지역 집계 위험요인. (모델 연결 후: 구역 내 건물 SHAP 평균 → 상위 top_k)"""
    if USE_MOCK:
        return _mock_region_factors()[:top_k]
    raise NotImplementedError("CatBoost 모델 연결 필요.")


# =========================================================================
# 팀원 모델 연결 시 참고용 예시 (지금은 실행되지 않음)
# =========================================================================
def _real_building_factors_example(model, feature_row, top_k=4) -> List[RiskFactor]:
    """
    feature_row: 이 건물의 160개 피처가 든 pandas 1행 DataFrame.
    model: 학습된 CatBoostRegressor.
    """
    from catboost import Pool  # noqa
    pool = Pool(feature_row)
    sv = model.get_feature_importance(pool, type="ShapValues")  # shape (1, n+1)
    contribs = sv[0][:-1]                # 마지막은 base_value
    names = feature_row.columns.tolist()
    ranked = sorted(zip(names, contribs, feature_row.iloc[0].tolist()),
                    key=lambda x: abs(x[1]), reverse=True)[:top_k]
    out = []
    for name, contrib, val in ranked:
        label, unit = FEATURE_LABELS.get(name, (name, None))
        out.append(RiskFactor(feature=name, label=label, value=val, unit=unit,
                              contribution=float(contrib)))
    return out
