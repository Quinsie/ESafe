# -*- coding: utf-8 -*-
"""
기상특보 기반 위험도 배수 적용 프로그램

- 기존 전기안전관리 위험도 분석 결과에 기상특보 배수를 적용
- 사업소/지역별 분석 결과 활용
- 매일 실행하여 당일 기상특보 반영
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import pandas as pd
import geopandas as gpd
from difflib import SequenceMatcher

class WeatherRiskMultiplier:
    """기상특보 기반 위험도 배수 적용 클래스"""

    def __init__(self, base_path: str = None):
        if base_path is None:
            base_path = str(Path(__file__).resolve().parent)

        self.base_path = Path(base_path)
        self.weather_path = self.base_path / "기상특보"
        self.branch_result_path = self.base_path / "사업소별 분석결과"
        self.region_result_path = self.base_path / "지역별 분석결과"
        self.branch_mapping_file = self.base_path / "전국 사업소 일람표.txt"

        # 사업소 매핑 로드
        self.branch_mapping = {}
        self.branch_to_hq = {}
        self._load_branch_mapping()

        # 특보 배수 정의 (특보종류: {예비: 배수, 주의: 배수, 경보: 배수})
        # 예비 = 주의와 동일한 배율 적용
        self.weather_multipliers = {
            '호우': {'예비': 1.5, '주의': 1.5, '경보': 2.0},
            '태풍': {'예비': 1.5, '주의': 1.5, '경보': 2.0},
            '강풍': {'예비': 1.2, '주의': 1.2, '경보': 1.8},
            '한파': {'예비': 1.2, '주의': 1.2, '경보': 1.8},
            '폭염': {'예비': 1.2, '주의': 1.2, '경보': 1.8},
            '건조': {'예비': 1.2, '주의': 1.2, '경보': 1.8},
            '대설': {'예비': 1.0, '주의': 1.0, '경보': 1.5},
            '폭풍해일': {'예비': 1.0, '주의': 1.0, '경보': 1.5},
            # 배수 미적용
            '황사': {'예비': 1.0, '주의': 1.0, '경보': 1.0},
            '안개': {'예비': 1.0, '주의': 1.0, '경보': 1.0},
            '풍랑': {'예비': 1.0, '주의': 1.0, '경보': 1.0},
        }

        # 광역지자체 목록
        self.region_names = {'서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
                            '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'}

        # 기상특보 지역명 → 시군구 매핑 (특보구역명과 실제 행정구역 매칭)
        self.weather_region_mapping = self._build_weather_region_mapping()

    def _load_branch_mapping(self):
        """사업소 매핑 파일 로드"""
        if not self.branch_mapping_file.exists():
            print(f"사업소 매핑 파일이 없습니다: {self.branch_mapping_file}")
            return

        hq_keywords = {
            '서울본부': ['서울'],
            '부산울산본부': ['부산울산', '부산', '울산'],
            '대구경북본부': ['대구경북', '대구', '경북', '구미칠곡', '경주'],
            '인천본부': ['인천', '부천김포'],
            '광주전남본부': ['광주전남', '전남', '여수'],
            '대전세종충남본부': ['대전세종충남', '충남', '천안아산', '서산태안'],
            '경기본부': ['경기본부', '안산시흥', '평택안성', '이천여주', '용인'],
            '경기북부본부': ['경기북부', '고양파주', '경기북동부'],
            '강원본부': ['강원', '원주횡성'],
            '충북본부': ['충북', '충주음성', '제천단양', '영동옥천'],
            '전북본부': ['전북', '익산', '군산', '남원순창'],
            '경남본부': ['경남', '김해양산', '밀양창녕'],
            '제주본부': ['제주'],
        }

        try:
            with open(self.branch_mapping_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    first_space = line.find(' ')
                    if first_space == -1:
                        continue

                    branch_name = line[:first_space].strip()
                    districts_str = line[first_space:].strip()
                    districts = [d.strip() for d in districts_str.split(',') if d.strip()]

                    if districts:
                        self.branch_mapping[branch_name] = districts

                        # 본부 매핑
                        for hq, keywords in hq_keywords.items():
                            for kw in keywords:
                                if branch_name.startswith(kw):
                                    self.branch_to_hq[branch_name] = hq
                                    break
                            if branch_name in self.branch_to_hq:
                                break

            print(f"사업소 매핑 로드 완료: {len(self.branch_mapping)}개 사업소")
        except Exception as e:
            print(f"사업소 매핑 로드 실패: {e}")

    def _build_weather_region_mapping(self) -> dict:
        """기상특보 지역명 → 행정구역 매핑"""
        # 기상청 특보구역명과 실제 행정구역명 매핑
        mapping = {
            # 서울
            '서울동남권': ['강남구', '서초구', '송파구', '강동구'],
            '서울동북권': ['동대문구', '성동구', '광진구', '중랑구', '성북구', '강북구', '도봉구', '노원구'],
            '서울서남권': ['영등포구', '구로구', '금천구', '동작구', '관악구'],
            '서울서북권': ['마포구', '서대문구', '은평구', '용산구', '종로구', '중구'],
            # 부산
            '부산동부': ['해운대구', '수영구', '남구', '동래구', '연제구', '금정구', '기장군'],
            '부산중부': ['중구', '동구', '부산진구', '북구'],
            '부산서부': ['서구', '사하구', '사상구', '강서구', '영도구'],
            # 울산
            '울산동부': ['동구', '북구', '울주군'],
            '울산서부': ['중구', '남구'],
            # 기타 (평지, 산지 등 접미사 제거)
        }
        return mapping

    def _normalize_region_name(self, name: str) -> str:
        """기상특보 지역명 정규화 (평지, 산지 등 제거)"""
        suffixes = ['평지', '산지', '안쪽', '바깥', '먼바다', '앞바다', '전해상']
        result = name
        for suffix in suffixes:
            if result.endswith(suffix):
                result = result[:-len(suffix)]
        return result.strip()

    def get_today_weather_file(self) -> tuple:
        """당일 기상특보 파일 경로 반환"""
        today = datetime.now().strftime('%Y%m%d')
        summary_file = self.weather_path / f"기상특보요약_{today}.csv"
        detail_file = self.weather_path / f"기상특보현황_{today}.csv"
        return summary_file, detail_file

    def load_weather_alerts(self) -> pd.DataFrame:
        """당일 기상특보 데이터 로드"""
        _, detail_file = self.get_today_weather_file()

        if not detail_file.exists():
            print(f"당일 기상특보 파일이 없습니다: {detail_file}")
            # 가장 최근 파일 찾기
            files = list(self.weather_path.glob("기상특보현황_*.csv"))
            if files:
                detail_file = max(files, key=lambda x: x.stem.split('_')[-1])
                print(f"최근 파일 사용: {detail_file.name}")
            else:
                return pd.DataFrame()

        try:
            df = pd.read_csv(detail_file, encoding='utf-8-sig')
            print(f"기상특보 로드: {len(df)}건")
            return df
        except Exception as e:
            print(f"기상특보 로드 실패: {e}")
            return pd.DataFrame()

    def get_alerts_for_region(self, weather_df: pd.DataFrame, region_name: str,
                              district_name: str = None) -> list:
        """특정 지역에 해당하는 기상특보 조회

        Returns:
            [(특보종류, 특보수준), ...] 리스트
        """
        if weather_df.empty:
            return []

        alerts = []

        # 검색할 지역명 목록 생성
        search_names = []
        if district_name:
            search_names.append(district_name)
            # 시군구에서 시/군 추출
            if ' ' in district_name:
                search_names.append(district_name.split()[0])
        search_names.append(region_name)

        # 기상특보 지역명 매핑 확인
        for search_name in search_names:
            # 직접 매칭
            matched = weather_df[
                weather_df['특보구역명'].str.contains(search_name, na=False, regex=False)
            ]

            for _, row in matched.iterrows():
                alert_type = row['특보종류']
                alert_level = row['특보수준']
                if (alert_type, alert_level) not in alerts:
                    alerts.append((alert_type, alert_level))

            # 정규화된 이름으로 매칭
            for _, row in weather_df.iterrows():
                normalized = self._normalize_region_name(row['특보구역명'])
                if search_name in normalized or normalized in search_name:
                    alert_type = row['특보종류']
                    alert_level = row['특보수준']
                    if (alert_type, alert_level) not in alerts:
                        alerts.append((alert_type, alert_level))

            # 광역 매핑 확인 (서울동북권 → 개별 구)
            for weather_region, districts in self.weather_region_mapping.items():
                if search_name in districts:
                    matched = weather_df[weather_df['특보구역명'] == weather_region]
                    for _, row in matched.iterrows():
                        alert_type = row['특보종류']
                        alert_level = row['특보수준']
                        if (alert_type, alert_level) not in alerts:
                            alerts.append((alert_type, alert_level))

        return alerts

    def calculate_multiplier(self, alerts: list) -> tuple:
        """특보 목록으로 최종 배수 계산

        Args:
            alerts: [(특보종류, 특보수준), ...] 리스트

        Returns:
            (최종배수, 적용특보문자열)
        """
        if not alerts:
            return 1.0, ""

        # 태풍+강풍 중복 시 태풍만 적용
        has_typhoon = any(a[0] == '태풍' for a in alerts)
        if has_typhoon:
            alerts = [(t, l) for t, l in alerts if t != '강풍']

        multiplier = 1.0
        applied_alerts = []

        for alert_type, alert_level in alerts:
            if alert_type in self.weather_multipliers:
                m = self.weather_multipliers[alert_type].get(alert_level, 1.0)
                if m > 1.0:  # 배수가 적용되는 경우만
                    multiplier *= m
                    applied_alerts.append(f"{alert_type}{alert_level}")

        applied_str = ", ".join(applied_alerts) if applied_alerts else ""
        return multiplier, applied_str

    def find_base_data(self, search_type: str, search_query: str,
                       min_age: int = 0, max_age: int = 100) -> list:
        """기본 분석 데이터 파일 찾기

        Args:
            search_type: 'branch' 또는 'region'
            search_query: 사업소명 또는 지역명
            min_age, max_age: 건물 연령 범위

        Returns:
            [(shp_path, region, district), ...] 리스트
        """
        results = []

        if search_type == 'branch':
            # 사업소별 분석결과에서 찾기
            if search_query in self.branch_mapping:
                # 개별 사업소
                hq = self.branch_to_hq.get(search_query)
                if hq:
                    folder = self.branch_result_path / hq / search_query
                    if folder.exists():
                        # 0~100세 기본 데이터 찾기
                        for shp in folder.glob("*.shp"):
                            # 연령 필터가 없는 파일 또는 요청한 연령 범위 파일
                            if self._match_age_filter(shp.name, min_age, max_age):
                                results.append((shp, None, None))
            elif '본부' in search_query:
                # 본부 전체
                folder = self.branch_result_path / search_query
                if folder.exists():
                    for shp in folder.glob("*.shp"):
                        if self._match_age_filter(shp.name, min_age, max_age):
                            results.append((shp, None, None))
                    # 하위 사업소도 포함
                    for sub_folder in folder.iterdir():
                        if sub_folder.is_dir():
                            for shp in sub_folder.glob("*.shp"):
                                if self._match_age_filter(shp.name, min_age, max_age):
                                    results.append((shp, None, None))

        else:  # region
            # 지역별 분석결과에서 찾기
            if search_query in self.region_names:
                # 광역지자체
                folder = self.region_result_path / search_query
                if folder.exists():
                    for shp in folder.glob("*.shp"):
                        if self._match_age_filter(shp.name, min_age, max_age):
                            results.append((shp, search_query, None))
                    # 하위 시군구도 포함
                    for sub_folder in folder.iterdir():
                        if sub_folder.is_dir():
                            for shp in sub_folder.glob("*.shp"):
                                if self._match_age_filter(shp.name, min_age, max_age):
                                    results.append((shp, search_query, sub_folder.name))
            else:
                # 시군구로 검색
                for region_folder in self.region_result_path.iterdir():
                    if region_folder.is_dir():
                        district_folder = region_folder / search_query
                        if district_folder.exists():
                            for shp in district_folder.glob("*.shp"):
                                if self._match_age_filter(shp.name, min_age, max_age):
                                    results.append((shp, region_folder.name, search_query))

        return results

    def _match_age_filter(self, filename: str, min_age: int, max_age: int) -> bool:
        """파일명에서 연령 필터 매칭 확인"""
        # 기상적용 파일은 제외 (원본만 처리)
        if '_기상적용_' in filename:
            return False

        # 기본값 (0~100세)인 경우 연령 표시 없는 파일 찾기
        if min_age == 0 and max_age == 100:
            return '년이상' not in filename and '년이하' not in filename

        # 특정 연령 필터가 있는 경우
        if min_age > 0:
            if f'{min_age}년이상' in filename:
                return True

        return False

    def run_base_analyzer(self, search_type: str, search_query: str,
                          min_age: int = 0, max_age: int = 100):
        """기본 분석 프로그램 실행"""
        print(f"\n기본 위험도 분석 데이터가 없습니다. 분석을 먼저 수행합니다...")

        analyzer_path = self.base_path / "building_multi_risk_analyzer.py"
        if not analyzer_path.exists():
            print(f"분석 프로그램을 찾을 수 없습니다: {analyzer_path}")
            return False

        # 자동 분석 실행을 위한 입력값 준비
        inputs = []
        inputs.append(search_query)  # 1단계: 지역/사업소

        if search_type == 'region' and search_query not in self.region_names:
            # 시군구인 경우 광역지자체 먼저 필요할 수 있음
            pass

        inputs.append("")  # 2단계: 구/군 (전체)

        if min_age > 0:
            inputs.append(str(min_age))  # 3단계: 최소 연령
        else:
            inputs.append("")

        if max_age < 100:
            inputs.append(str(max_age))
        else:
            inputs.append("")

        inputs.append("y")  # 홍수 분석
        inputs.append("y")  # 산사태 분석
        inputs.append("1")  # 통합 저장
        inputs.append("n")  # 추가 분석 안함

        input_str = "\n".join(inputs) + "\n"

        try:
            python_exe = os.getenv("PYTHON_EXE") or sys.executable or "python"
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            result = subprocess.run(
                [python_exe, "-X", "utf8", str(analyzer_path)],
                input=input_str,
                capture_output=True,
                text=True,
                encoding='utf-8',
                env=env,
                cwd=str(self.base_path)
            )

            if result.returncode == 0:
                print("기본 분석 완료!")
                return True
            else:
                print(f"분석 실패: {result.stderr[:500] if result.stderr else 'Unknown error'}")
                return False

        except Exception as e:
            print(f"분석 프로그램 실행 실패: {e}")
            return False

    def ensure_crs_5186(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """좌표계를 EPSG:5186으로 확인/변환

        Args:
            gdf: 입력 GeoDataFrame

        Returns:
            EPSG:5186 좌표계의 GeoDataFrame
        """
        if gdf.crs is None:
            print("  좌표계 정보 없음 → EPSG:5186 설정")
            gdf = gdf.set_crs(epsg=5186)
        elif gdf.crs.to_epsg() != 5186:
            original_crs = gdf.crs
            print(f"  좌표계 변환: {original_crs} → EPSG:5186")
            gdf = gdf.to_crs(epsg=5186)
        else:
            print("  좌표계 확인: EPSG:5186 (정상)")

        return gdf

    def update_coordinates(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """좌표 컬럼 재계산 (EPSG:5186 기준)"""
        if '중심점X' in gdf.columns:
            gdf['중심점X'] = gdf.geometry.centroid.x
        if '중심점Y' in gdf.columns:
            gdf['중심점Y'] = gdf.geometry.centroid.y
        if '경도' in gdf.columns:
            gdf['경도'] = gdf.geometry.centroid.x
        if '위도' in gdf.columns:
            gdf['위도'] = gdf.geometry.centroid.y
        return gdf

    def apply_weather_multiplier(self, gdf: gpd.GeoDataFrame,
                                  weather_df: pd.DataFrame) -> gpd.GeoDataFrame:
        """기상특보 배수 적용 (벡터 연산)

        Args:
            gdf: 기본 분석 결과 GeoDataFrame
            weather_df: 기상특보 데이터

        Returns:
            배수가 적용된 GeoDataFrame (EPSG:5186)
        """
        # 좌표계 확인 및 변환
        result = self.ensure_crs_5186(gdf.copy())

        # 새 컬럼 초기화
        result['기상배수'] = 1.0
        result['적용특보'] = ""

        # 지역/구군별로 그룹화하여 한 번만 특보 조회 (성능 최적화)
        region_col = '지역' if '지역' in result.columns else None
        district_col = '구군' if '구군' in result.columns else None

        if region_col or district_col:
            # 유니크한 지역/구군 조합 추출
            if region_col and district_col:
                unique_areas = result[[region_col, district_col]].drop_duplicates()
            elif region_col:
                unique_areas = result[[region_col]].drop_duplicates()
                unique_areas[district_col] = ''
            else:
                unique_areas = result[[district_col]].drop_duplicates()
                unique_areas[region_col] = ''

            print(f"  지역 그룹: {len(unique_areas)}개")

            # 각 지역별 배수 계산 (캐시)
            area_multipliers = {}
            for _, area_row in unique_areas.iterrows():
                region = area_row.get(region_col, '') if region_col else ''
                district = area_row.get(district_col, '') if district_col else ''
                key = (region, district)

                alerts = self.get_alerts_for_region(weather_df, region, district)
                multiplier, applied_str = self.calculate_multiplier(alerts)
                area_multipliers[key] = (multiplier, applied_str)

                if multiplier > 1.0:
                    print(f"    {region} {district}: {applied_str} → {multiplier:.2f}배")

            # 벡터 연산으로 일괄 적용
            def get_multiplier(row):
                key = (row.get(region_col, ''), row.get(district_col, ''))
                return area_multipliers.get(key, (1.0, ''))[0]

            def get_alerts_str(row):
                key = (row.get(region_col, ''), row.get(district_col, ''))
                return area_multipliers.get(key, (1.0, ''))[1]

            result['기상배수'] = result.apply(get_multiplier, axis=1)
            result['적용특보'] = result.apply(get_alerts_str, axis=1)

        # 기상위험점수 = 종합점수 × 배수 (벡터 연산)
        if '종합점수' in result.columns:
            result['기상위험점수'] = (result['종합점수'] * result['기상배수']).round(2)
        else:
            result['기상위험점수'] = 0

        return result

    def save_results(self, gdf: gpd.GeoDataFrame, output_path: Path):
        """결과 저장 (EPSG:5186 좌표계)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 최종 좌표계 확인 및 변환
        gdf_5186 = self.ensure_crs_5186(gdf.copy())

        # 좌표 컬럼 재계산 (EPSG:5186 기준)
        gdf_5186 = self.update_coordinates(gdf_5186)

        print(f"  최종 좌표계: EPSG:5186")

        try:
            gdf_5186.to_file(output_path, encoding='cp949')
        except:
            gdf_5186.to_file(output_path, encoding='utf-8')

        # CPG 파일 생성
        cpg_path = output_path.with_suffix('.cpg')
        with open(cpg_path, 'w') as f:
            f.write('CP949')

        # CSV도 저장
        csv_path = output_path.with_suffix('.csv')
        cols = [c for c in gdf_5186.columns if c != 'geometry']
        gdf_5186[cols].to_csv(csv_path, index=False, encoding='utf-8-sig')

        print(f"결과 저장: {output_path}")
        print(f"CSV 저장: {csv_path}")

        return output_path


def interactive_mode():
    """대화형 모드"""
    print("=" * 70)
    print("기상특보 기반 위험도 배수 적용 프로그램")
    print("=" * 70)

    multiplier = WeatherRiskMultiplier()

    # 1. 검색 유형 선택
    print("\n[1단계] 검색 유형 선택")
    print("-" * 70)
    print("  1. 사업소 (담당 전체 지역)")
    print("  2. 지역 (광역지자체 또는 시군구)")

    while True:
        choice = input("\n선택 (1 또는 2): ").strip()
        if choice in ['1', '2']:
            break
        print("  1 또는 2를 입력해주세요.")

    search_type = 'branch' if choice == '1' else 'region'

    # 2. 검색어 입력
    print("\n[2단계] 검색어 입력")
    print("-" * 70)

    if search_type == 'branch':
        print("  예시: 서울본부직할, 서울동부지사, 서울본부 (전체)")
        print(f"  등록된 사업소: {len(multiplier.branch_mapping)}개")
    else:
        print("  예시: 서울, 경기, 전주시 완산구")

    search_query = input("\n검색어 입력: ").strip()

    if not search_query:
        print("검색어가 입력되지 않았습니다.")
        return

    # 3. 연령 필터
    print("\n[3단계] 건물 연령 필터")
    print("-" * 70)
    print("  기본값: 0~100세 전체")

    min_age_input = input("최소 연령 (기본 0, Enter로 건너뛰기): ").strip()
    min_age = int(min_age_input) if min_age_input.isdigit() else 0

    max_age_input = input("최대 연령 (기본 100, Enter로 건너뛰기): ").strip()
    max_age = int(max_age_input) if max_age_input.isdigit() else 100

    print(f"\n연령 범위: {min_age}~{max_age}세")

    # 4. 기본 데이터 확인
    print("\n[4단계] 기본 분석 데이터 확인")
    print("-" * 70)

    base_files = multiplier.find_base_data(search_type, search_query, min_age, max_age)

    if not base_files:
        print(f"'{search_query}'에 대한 기본 분석 데이터가 없습니다.")

        run_choice = input("\n기본 분석을 먼저 수행하시겠습니까? (y/n): ").strip().lower()
        if run_choice != 'y':
            print("프로그램을 종료합니다.")
            return

        # 기본 분석 실행
        success = multiplier.run_base_analyzer(search_type, search_query, min_age, max_age)
        if not success:
            print("기본 분석 실행에 실패했습니다.")
            return

        # 다시 찾기
        base_files = multiplier.find_base_data(search_type, search_query, min_age, max_age)
        if not base_files:
            print("분석 후에도 데이터를 찾을 수 없습니다.")
            return

    print(f"기본 데이터 발견: {len(base_files)}개 파일")
    for shp_path, _, _ in base_files:
        print(f"  - {shp_path.name}")

    # 5. 기상특보 로드
    print("\n[5단계] 기상특보 데이터 로드")
    print("-" * 70)

    weather_df = multiplier.load_weather_alerts()

    if weather_df.empty:
        print("기상특보 데이터가 없습니다. 배수 1.0으로 진행합니다.")
    else:
        # 발효 중인 특보 요약
        alert_summary = weather_df.groupby(['특보종류', '특보수준']).size()
        print("\n현재 발효 중인 특보:")
        for (alert_type, level), count in alert_summary.items():
            mult = multiplier.weather_multipliers.get(alert_type, {}).get(level, 1.0)
            print(f"  - {alert_type} {level}: {count}건 (배수: {mult})")

    # 6. 배수 적용 및 저장
    print("\n[6단계] 기상특보 배수 적용")
    print("=" * 70)

    all_results = []

    for shp_path, region, district in base_files:
        print(f"\n처리 중: {shp_path.name}")

        try:
            gdf = gpd.read_file(shp_path, encoding='cp949')
        except:
            try:
                gdf = gpd.read_file(shp_path, encoding='utf-8')
            except Exception as e:
                print(f"  파일 로드 실패: {e}")
                continue

        print(f"  건물 수: {len(gdf):,}개")

        # 배수 적용
        result_gdf = multiplier.apply_weather_multiplier(gdf, weather_df)

        # 통계 출력
        avg_mult = result_gdf['기상배수'].mean()
        affected = (result_gdf['기상배수'] > 1.0).sum()
        print(f"  평균 배수: {avg_mult:.3f}")
        print(f"  특보 영향 건물: {affected:,}개 ({affected/len(result_gdf)*100:.1f}%)")

        # 저장 경로 생성
        today = datetime.now().strftime('%Y%m%d')
        output_name = shp_path.stem + f"_기상적용_{today}.shp"
        output_path = shp_path.parent / output_name

        multiplier.save_results(result_gdf, output_path)
        all_results.append((result_gdf, output_path))

    # 7. 최종 요약
    print("\n" + "=" * 70)
    print("처리 완료")
    print("=" * 70)
    print(f"처리된 파일: {len(all_results)}개")

    total_buildings = sum(len(r[0]) for r in all_results)
    total_affected = sum((r[0]['기상배수'] > 1.0).sum() for r in all_results)

    print(f"총 건물 수: {total_buildings:,}개")
    print(f"특보 영향 건물: {total_affected:,}개 ({total_affected/total_buildings*100:.1f}%)")

    # 적용된 특보 종류 출력
    if all_results:
        all_alerts = set()
        for gdf, _ in all_results:
            for alert_str in gdf['적용특보'].dropna():
                if alert_str:
                    all_alerts.update(alert_str.split(', '))

        if all_alerts:
            print(f"\n적용된 특보: {', '.join(sorted(all_alerts))}")

    print("\n프로그램을 종료합니다.")


if __name__ == "__main__":
    try:
        interactive_mode()
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
