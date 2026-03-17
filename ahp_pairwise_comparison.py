# -*- coding: utf-8 -*-
"""
AHP 기반 복합 위험 지수 모델 - 쌍대비교 및 가중치 산출
================================================================

전기안전관리 위험도 평가 항목:
  C1. 건물노후도      (1~10점)
  C2. 홍수위험        (1~10점)
  C3. 산사태근접      (1~10점)
  C4. 용도지역        (0~10점)
  C5. 전기화재이력    (0~10점)
  C6. 기상특보        (0~10점)
  C7. 전기설비점검현황 (0~10점) - 미점검/지적사항 기반

Saaty 척도:
  1 = 동등, 3 = 약간 중요, 5 = 중요, 7 = 매우 중요, 9 = 극히 중요
  2,4,6,8 = 중간값,  역수 = 반대 방향

사용법:
  1. 이 스크립트 실행
  2. 쌍대비교 행렬 확인/수정
  3. 가중치 및 일관성 비율(CR) 확인
  4. CR < 0.10 이면 일관성 충족
"""

import numpy as np
import sys


# =========================================================================
# 평가 항목 정의
# =========================================================================
criteria = [
    'C1.건물노후도',
    'C2.홍수위험',
    'C3.산사태근접',
    'C4.용도지역',
    'C5.전기화재이력',
    'C6.기상특보',
    'C7.설비점검',
]

n = len(criteria)

# =========================================================================
# 쌍대비교 행렬 (Pairwise Comparison Matrix)
# =========================================================================
# ★★★ 아래 행렬을 전문가 판단에 맞게 수정하세요 ★★★
#
# 읽는 법: matrix[i][j] = "i번 항목이 j번 항목보다 몇 배 중요한가"
#   예) matrix[0][4] = 1/3 → 건물노후도는 전기화재이력보다 1/3배 중요 (화재가 3배 중요)
#
# 대각선 = 1 (자기 자신과 비교)
# matrix[j][i] = 1 / matrix[i][j] (역수 관계 자동 계산)
#
#                  C1노후  C2홍수  C3산사태  C4용도  C5화재  C6기상  C7점검
# fmt: off
matrix_upper = [
    # C1.건물노후도 vs ...
    [  1,      3,      3,       5,     1/3,    3,     1/2  ],
    # C2.홍수위험 vs ...
    [  None,   1,      1,       3,     1/5,    1,     1/4  ],
    # C3.산사태근접 vs ...
    [  None,   None,   1,       3,     1/5,    1,     1/4  ],
    # C4.용도지역 vs ...
    [  None,   None,   None,    1,     1/7,    1/3,   1/5  ],
    # C5.전기화재이력 vs ...
    [  None,   None,   None,    None,  1,      5,     2    ],
    # C6.기상특보 vs ...
    [  None,   None,   None,    None,  None,   1,     1/4  ],
    # C7.전기설비점검현황 vs ...
    [  None,   None,   None,    None,  None,   None,  1    ],
]
# fmt: on

# =========================================================================
# 위 행렬의 의미 (초기 설정 근거)
# =========================================================================
"""
쌍대비교 초기값 설정 근거 (전기안전관리 관점):

[가장 중요] C5.전기화재이력
  - 전기안전 가장 직접적인 지표, 과거 화재 발생 = 재발 위험 높음
  - 설비점검보다 약간 중요 (2배): 실제 사고 이력 > 점검 결과
  - 나머지 항목보다 크게 중요 (3~7배)

[매우 중요] C7.전기설비점검현황
  - 전기설비 상태의 직접 지표 (미점검, 지적사항, 불량 등)
  - 전기화재이력 다음으로 중요: 설비 상태 = 사고 예방의 핵심
  - 건물노후도보다 약간 중요 (2배): 같은 노후 건물이라도 점검 상태가 다름
  - 홍수/산사태/기상보다 중요 (4배): 전기안전 직접 관련
  - 용도지역보다 매우 중요 (5배)

[중요] C1.건물노후도
  - 노후 건물 = 전기설비 노후 → 사고 위험 직결
  - 홍수/산사태보다 중요 (3배), 용도지역보다 중요 (5배)
  - 전기화재이력보다는 덜 중요 (1/3배)
  - 설비점검보다 약간 덜 중요 (1/2배)

[보통] C2.홍수위험, C3.산사태근접
  - 자연재해 위험으로 서로 동등 (1배)
  - 용도지역보다 중요 (3배)
  - 전기화재이력보다 덜 중요 (1/5배)
  - 설비점검보다 덜 중요 (1/4배)

[보통] C6.기상특보
  - 일시적 위험 가중 요소
  - 홍수/산사태와 동등 (1배)
  - 전기화재이력보다 덜 중요 (1/5배)
  - 설비점검보다 덜 중요 (1/4배)

[낮음] C4.용도지역
  - 간접적 위험 지표 (용도별 전기 사용량 차이)
  - 전기화재이력보다 훨씬 덜 중요 (1/7배)
  - 설비점검보다 훨씬 덜 중요 (1/5배)
"""


def build_full_matrix(upper):
    """상삼각 행렬로부터 전체 쌍대비교 행렬 생성 (역수 자동 계산)"""
    mat = np.ones((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            val = upper[i][j]
            if val is None or val <= 0:
                print(f"오류: matrix[{i}][{j}] 값이 유효하지 않습니다: {val}")
                sys.exit(1)
            mat[i][j] = val
            mat[j][i] = 1.0 / val
    return mat


def calculate_ahp_weights(matrix):
    """AHP 가중치 계산 (고유벡터법)"""
    # 각 열의 합 계산
    col_sums = matrix.sum(axis=0)

    # 정규화 (각 원소를 열합으로 나눔)
    normalized = matrix / col_sums

    # 행 평균 = 가중치 (우선순위 벡터)
    weights = normalized.mean(axis=1)

    return weights


def calculate_consistency(matrix, weights):
    """일관성 비율(CR) 계산"""
    # RI (Random Index) - Saaty 기준
    ri_table = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24,
                7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

    # λmax 계산
    weighted_sum = matrix @ weights
    lambda_values = weighted_sum / weights
    lambda_max = lambda_values.mean()

    # CI (Consistency Index)
    ci = (lambda_max - n) / (n - 1)

    # CR (Consistency Ratio)
    ri = ri_table.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0

    return lambda_max, ci, cr


def print_matrix(matrix, title="쌍대비교 행렬"):
    """행렬 출력"""
    print(f"\n{'=' * 90}")
    print(f"  {title}")
    print(f"{'=' * 90}")

    # 헤더 (축약)
    short_names = ['노후도', '홍수', '산사태', '용도', '화재', '기상', '점검']
    header = f"{'':>14}" + "".join(f"{name:>10}" for name in short_names)
    print(header)
    print("-" * 90)

    for i in range(n):
        row_str = f"{criteria[i]:>14}"
        for j in range(n):
            val = matrix[i][j]
            if val >= 1:
                row_str += f"{val:>10.1f}"
            else:
                # 분수 표현
                inv = 1.0 / val
                row_str += f"{'1/'+str(int(inv)) if inv == int(inv) else f'{val:.2f}':>10}"
        print(row_str)


def print_results(weights, lambda_max, ci, cr):
    """결과 출력"""
    print(f"\n{'=' * 90}")
    print("  AHP 가중치 산출 결과")
    print(f"{'=' * 90}")

    print(f"\n{'항목':<20} {'가중치':>10} {'백분율':>10} {'순위':>6}")
    print("-" * 50)

    # 순위 계산
    ranks = n - weights.argsort().argsort()

    for i in range(n):
        pct = weights[i] * 100
        bar = '█' * int(pct / 2)
        print(f"{criteria[i]:<20} {weights[i]:>10.4f} {pct:>9.1f}% {int(ranks[i]):>5}  {bar}")

    print(f"\n{'─' * 50}")
    print(f"{'합계':<20} {weights.sum():>10.4f} {weights.sum()*100:>9.1f}%")

    print(f"\n{'=' * 90}")
    print("  일관성 검증")
    print(f"{'=' * 90}")
    print(f"\n  λmax = {lambda_max:.4f}")
    print(f"  CI (일관성 지수) = {ci:.4f}")
    print(f"  CR (일관성 비율) = {cr:.4f}")

    if cr < 0.10:
        print(f"\n  ✓ CR = {cr:.4f} < 0.10 → 일관성 충족 (합격)")
    else:
        print(f"\n  ✗ CR = {cr:.4f} ≥ 0.10 → 일관성 미충족 (쌍대비교 재검토 필요)")


def print_weighted_score_formula(weights):
    """최종 가중 점수 산출 공식 출력"""
    short_names = ['노후점수', '홍수점수', '산사태점수', '용도점수', '화재점수', '기상점수', '점검점수']

    print(f"\n{'=' * 90}")
    print("  최종 가중 종합점수 산출 공식")
    print(f"{'=' * 90}")

    parts = []
    for i in range(n):
        parts.append(f"{weights[i]:.4f} × {short_names[i]}")

    formula = "\n    종합점수 = " + "\n               + ".join(parts)
    print(formula)

    # 최대/최소 점수 계산
    max_scores = [10, 10, 10, 10, 10, 10, 10]  # 각 항목 최대
    min_scores = [1, 1, 1, 0, 0, 0, 0]          # 각 항목 최소

    max_total = sum(w * s for w, s in zip(weights, max_scores))
    min_total = sum(w * s for w, s in zip(weights, min_scores))

    print(f"\n  • 이론상 최소 점수: {min_total:.2f}점")
    print(f"  • 이론상 최대 점수: {max_total:.2f}점")

    # 등급 기준 제안
    score_range = max_total - min_total
    step = score_range / 5

    print(f"\n  [등급 기준 제안 (5등분)]")
    grades = ['A (안전)', 'B (관심)', 'C (주의)', 'D (경고)', 'E (위험)']
    for i, grade in enumerate(grades):
        low = min_total + step * i
        high = min_total + step * (i + 1)
        if i == len(grades) - 1:
            print(f"    {grade}: {low:.2f} ~ {high:.2f}")
        else:
            print(f"    {grade}: {low:.2f} ~ {high:.2f} 미만")


def interactive_edit():
    """대화형 쌍대비교 수정"""
    short_names = ['노후도', '홍수', '산사태', '용도', '화재', '기상', '점검']

    print(f"\n{'=' * 90}")
    print("  쌍대비교 값 수정 (Saaty 척도: 1=동등, 3=약간중요, 5=중요, 7=매우중요, 9=극히중요)")
    print(f"{'=' * 90}")

    modified = False

    for i in range(n):
        for j in range(i + 1, n):
            current = matrix_upper[i][j]
            if current >= 1:
                display = f"{current:.0f}" if current == int(current) else f"{current:.1f}"
            else:
                inv = 1.0 / current
                display = f"1/{inv:.0f}" if inv == int(inv) else f"{current:.2f}"

            prompt = (f"  {short_names[i]} vs {short_names[j]} "
                      f"(현재: {display}, Enter=유지): ")
            user_input = input(prompt).strip()

            if user_input:
                try:
                    if '/' in user_input:
                        # 분수 입력 (예: 1/3)
                        parts = user_input.split('/')
                        val = float(parts[0]) / float(parts[1])
                    else:
                        val = float(user_input)

                    if val <= 0:
                        print("    ⚠️ 0보다 큰 값을 입력해주세요. 기존값 유지.")
                    else:
                        matrix_upper[i][j] = val
                        modified = True
                except ValueError:
                    print("    ⚠️ 숫자를 입력해주세요. 기존값 유지.")

    return modified


# =========================================================================
# 메인 실행
# =========================================================================
if __name__ == "__main__":
    print("=" * 90)
    print("       AHP 기반 복합 위험 지수 모델 - 쌍대비교 및 가중치 산출")
    print("=" * 90)
    print(f"\n평가 항목 ({n}개):")
    for c in criteria:
        print(f"  • {c}")

    while True:
        # 1. 전체 행렬 생성
        matrix = build_full_matrix(matrix_upper)

        # 2. 행렬 출력
        print_matrix(matrix)

        # 3. 가중치 계산
        weights = calculate_ahp_weights(matrix)

        # 4. 일관성 검증
        lambda_max, ci, cr = calculate_consistency(matrix, weights)

        # 5. 결과 출력
        print_results(weights, lambda_max, ci, cr)

        # 6. 가중 점수 공식
        print_weighted_score_formula(weights)

        # 7. 수정 여부
        print(f"\n{'=' * 90}")
        print("\n다음 작업을 선택하세요:")
        print("  1. 쌍대비교 값 수정")
        print("  2. 현재 결과로 확정 (종료)")

        while True:
            choice = input("\n선택 (1 또는 2): ").strip()
            if choice in ['1', '2']:
                break
            print("  ⚠️ 1 또는 2를 입력해주세요.")

        if choice == '2':
            print("\n" + "=" * 90)
            print("  AHP 가중치가 확정되었습니다.")
            print("  building_multi_risk_analyzer.py에 가중치를 적용하려면")
            print("  위 가중치 값을 코드에 반영해주세요.")
            print("=" * 90)
            input("\n종료하려면 Enter 키를 누르세요...")
            break
        else:
            interactive_edit()
            print("\n수정된 값으로 재계산합니다...\n")
