"""
건물 노후위험도 × 홍수위험 × 산사태근접위험 × 전기화재이력 통합 분석 프로그램
================================================================
목적: 건물연령(A25 연령컬럼 기반) + 홍수위험 + 산사태근접위험 + 용도지역 + 전기화재이력을
      결합하여 종합 위험등급을 산출하고 필터링된 결과를 SHP로 출력

위험도 점수 체계 (단순 합산):
- 노후위험도: 0~5년(1점), 5~10년(2점), 10~20년(4점), 20~30년(6점), 30~50년(8점), 50년+(10점)
- 홍수위험: 구역 외(1점), 구역 내(10점)
- 산사태근접: 400m+(1점), 300~400m(2점), 200~300m(4점), 100~200m(6점), 50~100m(8점), 50m미만(10점)
- 전기화재이력: 5m이내(10점), 10m이내(8점), 20m이내(6점)
- 용도지역: CSV 코드표 기반 점수

기능:
- A25(건물연령) 컬럼 사용 (작년 기준이므로 +1 적용)
- 모든 위험요소 점수를 단순 합산하여 종합점수 산출
- 사용자 입력: 지역 선택, 연령 필터링
- cp949 인코딩 지원 (한국 SHP 파일)

사용법:
    python building_multi_risk_analyzer.py

필요 라이브러리:
    pip install geopandas shapely fiona pyproj rtree pandas numpy rasterio scipy
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import warnings
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
warnings.filterwarnings('ignore')

# 타임아웃 오류 로깅 설정
logging.basicConfig(
    filename='analysis_timeout_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 분석 단계별 타임아웃 (초)
ANALYSIS_TIMEOUT = 1200  # 20분

try:
    import geopandas as gpd
    import pandas as pd
    from shapely.strtree import STRtree
    from shapely.geometry import shape, mapping, box
    from shapely.ops import unary_union
    import numpy as np
except ImportError as e:
    print(f"필요한 라이브러리가 없습니다: {e}")
    print("다음 명령어로 설치해주세요:")
    print("pip install geopandas shapely fiona pyproj rtree pandas numpy")
    sys.exit(1)

# 래스터 처리용 (산사태 분석)
try:
    import rasterio
    from rasterio.features import shapes
    from scipy.ndimage import distance_transform_edt
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False
    print("경고: rasterio/scipy 미설치 - 산사태 분석 기능 제한됨")
    print("설치: pip install rasterio scipy")


class BuildingMultiRiskAnalyzer:
    """건물 노후위험도 × 홍수위험 × 산사태근접위험 통합 분석 클래스"""

    # 노후위험도 등급 기준 (연령 범위, 등급명, 점수)
    AGE_RISK_LEVELS = [
        (0, 5, '신축', 1),
        (5, 10, '양호', 2),
        (10, 20, '보통', 4),
        (20, 30, '주의', 6),
        (30, 50, '노후', 8),
        (50, 100, '고령', 10),
        (100, 999, '초고령', 10)
    ]

    # 홍수위험 등급 기준 (구역 외 1점, 구역 내 10점)
    FLOOD_RISK_LEVELS = [
        (0, 0.01, '구역외', 1),     # 홍수위험구역 외
        (0.01, 100, '구역내', 10),   # 홍수위험구역 내
    ]

    # 산사태 근접위험 등급 기준 (거리(m), 등급명, 점수)
    LANDSLIDE_PROXIMITY_LEVELS = [
        (0, 50, '매우위험', 10),     # 50m 미만
        (50, 100, '위험', 8),        # 50~100m
        (100, 200, '주의', 6),       # 100~200m
        (200, 300, '관심', 4),       # 200~300m
        (300, 400, '경계', 2),       # 300~400m
        (400, 500, '안전', 1),       # 400~500m
        (500, 99999, '안전', 0)      # 500m 이상
    ]

    # 종합위험등급 기준 (점수 합계) - 모든 위험요소 단순 합산
    # 노후(1~10) + 홍수(1~10) + 산사태(0~10) + 용도지역 + 전기화재(0~10)
    COMBINED_RISK_LEVELS = [
        (0, 10, '안전', 'A'),
        (10, 20, '관심', 'B'),
        (20, 30, '주의', 'C'),
        (30, 40, '경고', 'D'),
        (40, 999, '위험', 'E')
    ]

    def __init__(self, base_path: str):
        """
        Args:
            base_path: 데이터 기본 경로
        """
        self.base_path = Path(base_path)
        self.building_path = self.base_path / "건물연령"
        self.flood_path = self.base_path / "홍수위험"
        self.flood_trace_shp = self.base_path / "침수흔적도" / "위선" / "TFF_FLDWTL_LN.shp"
        self.landslide_path = self.base_path / "산사태위험"
        self.output_path = self.base_path / "분석결과"
        self.current_year = datetime.now().year

        # 출력 폴더 생성
        self.output_path.mkdir(parents=True, exist_ok=True)

        # 지역 매핑 정보
        self.region_mapping = self._build_region_mapping()

        # 산사태 위험지역 캐시 (래스터→벡터 변환 결과)
        self._landslide_cache = {}

        # 시도코드 → 지역폴더명 매핑
        self.sido_to_region = {
            '11': '서울',
            '26': '부산',
            '27': '대구',
            '28': '인천',
            '29': '광주',
            '30': '대전',
            '31': '울산',
            '36': '세종',
            '41': '경기',
            '42': '강원',
            '43': '충북',
            '44': '충남',
            '45': '전북',
            '46': '전남',
            '47': '경북',
            '48': '경남',
            '50': '제주',
            '52': '전북',  # 전북 특별자치도 (신규 코드)
        }

        # 사업소 매핑 정보 (사업소명 → (광역지자체, 담당지역 리스트))
        # 담당지역 리스트가 None이면 해당 광역지자체 전체
        self.branch_mapping = {}

        # 사업소명에서 광역지자체 추출을 위한 매핑
        self.branch_region_keywords = {
            '서울': '서울',
            '부산': '부산', '울산': '울산',
            '대구': '대구', '경북': '경북', '구미': '경북', '칠곡': '경북', '경주': '경북',
            '인천': '인천', '부천': '경기', '김포': '경기',
            '광주': '광주', '전남': '전남', '여수': '전남',
            '대전': '대전', '세종': '세종', '충남': '충남', '천안': '충남', '아산': '충남',
            '서산': '충남', '태안': '충남',
            '경기': '경기', '수원': '경기', '화성': '경기', '안산': '경기', '시흥': '경기',
            '평택': '경기', '안성': '경기', '이천': '경기', '여주': '경기', '용인': '경기',
            '고양': '경기', '파주': '경기',
            '강원': '강원', '원주': '강원', '횡성': '강원',
            '충북': '충북', '충주': '충북', '제천': '제천', '단양': '충북', '영동': '충북', '옥천': '충북',
            '전북': '전북', '익산': '전북', '군산': '전북', '남원': '전북', '순창': '전북',
            '경남': '경남', '김해': '경남', '양산': '경남', '밀양': '경남', '창녕': '경남',
            '제주': '제주',
        }

        # 외부 사업소 매핑 파일 로드
        self._load_branch_mapping_file()

        # 지사→본부 매핑 (save_results에서 사용)
        self.branch_to_hq = self._build_branch_to_hq_mapping()

    def _build_branch_to_hq_mapping(self) -> dict:
        """지사/직할명 → 본부명 매핑 생성"""
        mapping = {}
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
        for branch_name in self.branch_mapping.keys():
            for hq, keywords in hq_keywords.items():
                for kw in keywords:
                    if branch_name.startswith(kw):
                        mapping[branch_name] = hq
                        break
                if branch_name in mapping:
                    break
        return mapping

    def _run_with_timeout(self, func, args=(), kwargs=None, task_name="작업", timeout=ANALYSIS_TIMEOUT):
        """
        타임아웃이 적용된 함수 실행

        Args:
            func: 실행할 함수
            args: 함수 인자 (튜플)
            kwargs: 함수 키워드 인자 (딕셔너리)
            task_name: 작업명 (로그용)
            timeout: 타임아웃 시간(초), 기본 5분

        Returns:
            (성공여부, 결과 또는 None)
        """
        if kwargs is None:
            kwargs = {}

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                result = future.result(timeout=timeout)
                return True, result
            except FuturesTimeoutError:
                error_msg = f"[타임아웃] '{task_name}' 작업이 {timeout//60}분을 초과하여 중단되었습니다."
                print(f"\n  ⚠️ {error_msg}")
                logging.error(f"{task_name} | 타임아웃 ({timeout}초 초과) | args: {args}")
                return False, None
            except Exception as e:
                error_msg = f"[오류] '{task_name}' 작업 중 오류 발생: {e}"
                print(f"\n  ⚠️ {error_msg}")
                logging.error(f"{task_name} | 오류: {e} | args: {args}")
                return False, None

    def _get_output_directory(self, search_query: str, region_name: str = None,
                               district_name: str = None) -> Path:
        """입력값에 따른 저장 경로 결정

        Args:
            search_query: 원래 사용자 입력값
            region_name: 광역지자체명 (예: '경기')
            district_name: 구/군명 (예: '안산시 단원구')

        Returns:
            저장할 디렉토리 Path
        """
        # 1. 직할/지사인 경우 → 사업소별 분석결과/본부/직할지사/
        if search_query in self.branch_mapping:
            hq = self.branch_to_hq.get(search_query)
            if hq:
                return self.base_path / "사업소별 분석결과" / hq / search_query

        # 2. 본부명인 경우 → 사업소별 분석결과/본부/
        if '본부' in search_query and '직할' not in search_query and '지사' not in search_query:
            return self.base_path / "사업소별 분석결과" / search_query

        # 3. 시군구가 지정된 경우 → 지역별 분석결과/시도/시군구/
        # (광역지자체 체크보다 먼저 확인하여 구/군 지정 시 해당 폴더에 저장)
        if region_name and district_name:
            return self.base_path / "지역별 분석결과" / region_name / district_name

        # 4. 광역지자체명인 경우 → 지역별 분석결과/시도/
        region_names = {'서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
                       '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'}
        if search_query in region_names:
            return self.base_path / "지역별 분석결과" / search_query

        # 5. 기본값: 분석결과 폴더
        return self.output_path

    def _load_branch_mapping_file(self):
        """외부 사업소 매핑 파일 로드 (전국 사업소 일람표.txt)

        파일 형식 (각 줄):
            사업소명 지역1, 지역2, 지역3

        예시:
            서울본부직할 마포구, 은평구, 서대문구, 용산구, 종로구, 중구
            충북본부직할 청주시, 보은군, 괴산군, 진천군, 증평군

        Note:
            담당지역만 저장하고, 광역지자체는 get_branch_info에서 동적으로 추출
        """
        mapping_file = self.base_path / "전국 사업소 일람표.txt"

        if not mapping_file.exists():
            # 대체 파일명 시도
            mapping_file = self.base_path / "branch_mapping.txt"
            if not mapping_file.exists():
                return

        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):  # 빈 줄이나 주석 무시
                        continue

                    # 첫 번째 공백으로 사업소명과 담당지역 분리
                    first_space = line.find(' ')
                    if first_space == -1:
                        continue

                    branch_name = line[:first_space].strip()
                    districts_str = line[first_space:].strip()

                    # 담당지역 파싱 (쉼표 구분)
                    districts = [d.strip() for d in districts_str.split(',') if d.strip()]

                    if not districts:
                        continue

                    # 담당지역만 저장 (광역지자체는 나중에 동적 추출)
                    self.branch_mapping[branch_name] = districts

            print(f"사업소 매핑 파일 로드 완료: {len(self.branch_mapping)}개 사업소")
        except Exception as e:
            print(f"사업소 매핑 파일 로드 실패: {e}")

    def _extract_region_from_branch_name(self, branch_name: str) -> str:
        """사업소명에서 광역지자체 추출

        예: '충북본부직할' → '충북'
            '서울동부지사' → '서울'
            '대구경북본부직할' → '대구' (첫 번째 매칭)
        """
        # 사업소명에서 키워드 매칭
        for keyword, region in self.branch_region_keywords.items():
            if keyword in branch_name:
                return region

        return None

    def _build_district_to_region_map(self) -> dict:
        """구/군명 → 광역지자체 역매핑 생성"""
        district_to_region = {}
        for region_name, region_info in self.region_mapping.items():
            for district_name in region_info['districts'].keys():
                district_to_region[district_name] = region_name
                # '청주시 상당구' → '청주시'도 매핑 (부분 이름)
                if ' ' in district_name:
                    city_name = district_name.split(' ')[0]
                    if city_name not in district_to_region:
                        district_to_region[city_name] = region_name
        return district_to_region

    def find_region_for_district(self, district_name: str) -> str:
        """구/군명으로 광역지자체 찾기

        Args:
            district_name: 구/군명 (예: '청주시', '마포구', '전주시 완산구')

        Returns:
            광역지자체명 또는 None
        """
        district_to_region = self._build_district_to_region_map()

        # 1. 정확히 일치
        if district_name in district_to_region:
            return district_to_region[district_name]

        # 2. 부분 매칭 (예: '청주시' → '충북')
        for dist, region in district_to_region.items():
            if dist.startswith(district_name) or district_name.startswith(dist):
                return region

        return None

    def get_branch_info(self, branch_name: str) -> dict:
        """사업소명으로 광역지자체별 구/군 리스트 조회

        Args:
            branch_name: 사업소명 (예: '서울본부직할', '충북본부직할', '대구경북본부직할')
                        또는 본부명 (예: '서울본부', '경기본부', '경기북부본부')
                        → 본부명만 입력하면 해당 본부의 직할+모든지사 전체 조회

        Returns:
            {광역지자체: [실제 폴더에 매칭되는 구/군 리스트], ...} 또는 None
            예: {'대구': ['중구', '동구', ...], '경북': ['군위군', '경산시', ...]}

        Note:
            담당지역이 '청주시'처럼 시 단위로만 되어 있으면,
            실제 폴더에서 '청주시 상당구', '청주시 서원구' 등을 찾아서 확장함
        """
        # 본부명으로 입력한 경우 (예: '서울본부' → 서울 관련 모든 사업소 합침)
        raw_districts = self._get_districts_for_branch(branch_name)
        if not raw_districts:
            return None

        # 사업소명에서 가능한 광역지자체 힌트 추출
        region_hints = self._extract_regions_from_branch_name(branch_name)

        # 담당지역을 광역지자체별로 그룹화
        region_districts = {}

        for district in raw_districts:
            # 각 담당지역이 어느 광역지자체에 속하는지 찾기 (힌트 활용)
            region = self._find_region_for_raw_district(district, region_hints)

            if region:
                if region not in region_districts:
                    region_districts[region] = []
                region_districts[region].append(district)

        if not region_districts:
            return None

        # 각 광역지자체별로 담당지역을 실제 폴더명으로 확장
        result = {}
        for region, districts in region_districts.items():
            expanded = self._expand_districts_to_folders(region, districts)
            if expanded:
                result[region] = expanded

        return result if result else None

    def _get_districts_for_branch(self, branch_name: str) -> list:
        """사업소명 또는 본부명으로 담당지역 리스트 조회

        Args:
            branch_name: 사업소명 또는 본부명
                - 정확한 사업소명: '서울본부직할', '서울동부지사' 등
                - 본부명: '서울본부', '경기본부', '경기북부본부' 등

        Returns:
            담당지역 리스트 (모든 관련 사업소 합침)

        Examples:
            '서울본부직할' → ['마포구', '은평구', ...] (직할만)
            '서울본부' → ['마포구', ..., '동대문구', ..., '영등포구', ...] (직할+모든지사)
            '경기북부본부' → 경기북부본부직할 + 고양파주지사 + 경기북동부지사 전체
        """
        # 1. 정확히 일치하는 사업소가 있으면 그것만 반환
        if branch_name in self.branch_mapping:
            return self.branch_mapping[branch_name]

        # 2. 본부명으로 입력한 경우 (직할/지사 없이)
        #    해당 본부의 직할 + 관련 지사 모두 합침
        if '본부' in branch_name and '직할' not in branch_name and '지사' not in branch_name:
            return self._get_all_districts_for_headquarter(branch_name)

        # 3. 광역지자체명은 사업소로 인식하지 않음
        #    (예: '전북', '서울' 등은 광역지자체로 처리되어야 함)
        region_names = {'서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
                       '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'}
        if branch_name in region_names:
            return None

        # 4. 부분 매칭 시도 (오타 등) - 광역지자체명이 아닌 경우만
        for registered_name in self.branch_mapping.keys():
            if branch_name in registered_name or registered_name in branch_name:
                return self.branch_mapping[registered_name]

        return None

    def _get_all_districts_for_headquarter(self, hq_name: str) -> list:
        """본부명으로 해당 본부의 모든 사업소(직할+지사) 담당지역 합침

        Args:
            hq_name: 본부명 (예: '서울본부', '경기본부', '경기북부본부')

        Returns:
            해당 본부의 모든 담당지역 리스트

        Logic:
            1. 본부명에서 핵심 키워드 추출 (예: '서울본부' → '서울')
            2. 해당 키워드로 시작하는 모든 사업소 찾기
            3. 모든 담당지역 합침 (중복 제거)
        """
        all_districts = []
        matched_branches = []

        # 본부명에서 핵심 키워드 추출
        # '서울본부' → '서울', '경기북부본부' → '경기북부', '대구경북본부' → '대구경북'
        hq_keyword = hq_name.replace('본부', '')

        # 해당 키워드로 시작하는 모든 사업소 찾기
        for registered_name, districts in self.branch_mapping.items():
            # 직할 체크: '서울본부직할'은 '서울'로 시작
            # 지사 체크: '서울동부지사'도 '서울'로 시작
            if registered_name.startswith(hq_keyword):
                matched_branches.append(registered_name)
                all_districts.extend(districts)

        if matched_branches:
            # 중복 제거 (순서 유지)
            seen = set()
            unique_districts = []
            for d in all_districts:
                if d not in seen:
                    seen.add(d)
                    unique_districts.append(d)

            print(f"\n  [본부 전체 조회] {hq_name}")
            print(f"    포함 사업소: {', '.join(matched_branches)}")
            print(f"    담당지역 수: {len(unique_districts)}개")

            return unique_districts

        return None

    def _extract_regions_from_branch_name(self, branch_name: str) -> list:
        """사업소명에서 가능한 모든 광역지자체 추출

        예: '대구경북본부직할' → ['대구', '경북']
            '서울본부직할' → ['서울']
            '부산울산본부직할' → ['부산', '울산']
        """
        regions = []
        for keyword, region in self.branch_region_keywords.items():
            if keyword in branch_name and region in self.region_mapping:
                if region not in regions:
                    regions.append(region)
        return regions

    def _find_region_for_raw_district(self, district_name: str, region_hints: list = None) -> str:
        """원본 담당지역명으로 광역지자체 찾기

        Args:
            district_name: 담당지역명 (예: '청주시', '마포구', '울산시')
            region_hints: 사업소명에서 추출한 광역지자체 힌트 리스트

        Returns:
            광역지자체명 또는 None

        Note:
            동명이인 문제 해결을 위해 region_hints를 우선 검색
            예: '서울본부직할'의 '중구'는 서울의 중구로 매칭
        """
        # 0. 특수 케이스: '울산시' → '울산', '광주시' → '광주' 등 (광역시 전체)
        special_mappings = {
            '울산시': '울산',
            '광주시': '광주',
            '대전시': '대전',
            '세종시': '세종',
            '부산시': '부산',
            '대구시': '대구',
            '인천시': '인천',
        }
        if district_name in special_mappings:
            mapped_region = special_mappings[district_name]
            # 힌트가 있으면 힌트 내에 있는 경우만 반환
            if region_hints and mapped_region in region_hints:
                return mapped_region
            # 힌트가 없으면 그냥 반환
            if not region_hints:
                return mapped_region
            # 힌트가 있는데 매핑된 지역이 힌트에 없으면 힌트 중 첫 번째로
            return region_hints[0] if region_hints else mapped_region

        # 1. 힌트가 있으면 힌트 광역지자체에서 먼저 검색
        if region_hints:
            for region_name in region_hints:
                if region_name not in self.region_mapping:
                    continue
                folder_names = list(self.region_mapping[region_name]['districts'].keys())

                # 정확히 일치
                if district_name in folder_names:
                    return region_name

                # 부분 매칭 (예: '청주시' → '청주시 상당구')
                for folder in folder_names:
                    if folder.startswith(district_name):
                        return region_name

        # 2. 힌트에서 못 찾으면 전체에서 검색 (단, 시/군 단위만)
        # '구' 단위 동명이인(중구, 동구 등)은 힌트 없이는 찾지 않음
        is_gu = district_name.endswith('구') and not district_name.endswith('시구')

        if not is_gu:  # 시/군 단위인 경우만 전체 검색
            for region_name, region_info in self.region_mapping.items():
                folder_names = list(region_info['districts'].keys())

                # 정확히 일치
                if district_name in folder_names:
                    return region_name

                # 부분 매칭 (예: '청주시' → '청주시 상당구')
                for folder in folder_names:
                    if folder.startswith(district_name):
                        return region_name

        # 3. 그래도 못 찾으면 키워드 매핑으로 추론 (시/군 이름에서)
        for keyword, region in self.branch_region_keywords.items():
            if keyword in district_name:
                if region in self.region_mapping:
                    return region

        return None

    def _expand_districts_to_folders(self, region_name: str, raw_districts: list) -> list:
        """담당지역 리스트를 실제 폴더명으로 확장

        예: ['청주시', '보은군'] → ['청주시 상당구', '청주시 서원구', ..., '보은군']
            ['울산시'] → 울산 전체 폴더
            ['광주시'] → 광주 전체 폴더

        Args:
            region_name: 광역지자체명
            raw_districts: 원본 담당지역 리스트 (사업소 일람표 기준)

        Returns:
            실제 폴더명으로 확장된 구/군 리스트
        """
        if region_name not in self.region_mapping:
            return raw_districts

        valid_folders = list(self.region_mapping[region_name]['districts'].keys())
        expanded = []

        # 광역시 전체를 의미하는 특수 키워드
        metro_city_keywords = {
            '울산시': '울산',
            '광주시': '광주',
            '대전시': '대전',
            '세종시': '세종',
            '부산시': '부산',
            '대구시': '대구',
            '인천시': '인천',
        }

        for district in raw_districts:
            # 0. 광역시 전체인 경우 (예: '울산시' → 울산 전체)
            if district in metro_city_keywords:
                target_region = metro_city_keywords[district]
                if target_region == region_name:
                    # 해당 광역시의 모든 폴더 추가
                    expanded.extend(valid_folders)
                    continue

            # 1. 정확히 일치하는 폴더가 있는지 확인
            if district in valid_folders:
                expanded.append(district)
                continue

            # 2. '시' 단위 입력 → 해당 시의 모든 구 찾기 (예: '청주시' → '청주시 상당구', ...)
            matching_folders = [f for f in valid_folders if f.startswith(district)]
            if matching_folders:
                expanded.extend(matching_folders)
                continue

            # 3. '시' 없이 입력된 경우 (예: '전주' → '전주시 완산구', '전주시 덕진구')
            if not district.endswith('시') and not district.endswith('군') and not district.endswith('구'):
                # '시'를 붙여서 다시 검색
                district_with_si = district + '시'
                matching_folders = [f for f in valid_folders if f.startswith(district_with_si)]
                if matching_folders:
                    expanded.extend(matching_folders)
                    continue

            # 4. 부분 매칭 시도 (예: '성남' → '성남시', '성남시 수정구' 등)
            partial_matches = [f for f in valid_folders if district in f]
            if partial_matches:
                expanded.extend(partial_matches)

        # 중복 제거 (순서 유지)
        seen = set()
        unique_expanded = []
        for d in expanded:
            if d not in seen:
                seen.add(d)
                unique_expanded.append(d)

        return unique_expanded if unique_expanded else None

    def find_districts_by_city(self, region_name: str, city_name: str) -> list:
        """특정 시(city)에 속하는 모든 구/군 찾기

        Args:
            region_name: 광역지자체명 (예: '충북')
            city_name: 시명 (예: '청주시')

        Returns:
            해당 시의 구/군 리스트 (예: ['청주시 상당구', '청주시 서원구', ...])
        """
        if region_name not in self.region_mapping:
            return []

        districts = self.region_mapping[region_name]['districts'].keys()
        matching = [d for d in districts if d.startswith(city_name)]
        return matching

    def _build_region_mapping(self) -> dict:
        """지역 폴더 구조를 스캔하여 매핑 정보 생성"""
        mapping = {}

        if not self.building_path.exists():
            return mapping

        for region_folder in self.building_path.iterdir():
            if region_folder.is_dir():
                region_name = region_folder.name  # 서울, 부산, 전북 등
                mapping[region_name] = {
                    'path': region_folder,
                    'districts': {}
                }

                for district_folder in region_folder.iterdir():
                    if district_folder.is_dir():
                        district_name = district_folder.name  # 종로구, 전주시 완산구 등
                        shp_files = list(district_folder.glob("*.shp"))
                        if shp_files:
                            # 지역코드 추출
                            region_code = self._get_region_code(shp_files[0].name)
                            mapping[region_name]['districts'][district_name] = {
                                'path': district_folder,
                                'code': region_code,
                                'building_shp': shp_files[0]
                            }

        return mapping

    def _get_region_code(self, filename: str) -> str:
        """파일명에서 5자리 지역코드 추출"""
        parts = filename.replace('.shp', '').split('_')
        for part in parts:
            if part.isdigit() and len(part) == 5:
                return part
        return None

    def _get_sido_code(self, region_code: str) -> str:
        """5자리 지역코드에서 2자리 시도코드 추출 (52111 → 52)"""
        if region_code and len(region_code) >= 2:
            return region_code[:2]
        return None

    def _read_shp_with_encoding(self, shp_path: Path, encodings=['cp949', 'euc-kr', 'utf-8']) -> gpd.GeoDataFrame:
        """여러 인코딩을 시도하여 SHP 파일 읽기"""
        for encoding in encodings:
            try:
                gdf = gpd.read_file(shp_path, encoding=encoding)
                return gdf
            except Exception:
                continue

        # 마지막으로 인코딩 없이 시도
        return gpd.read_file(shp_path)

    def _save_shp_with_encoding(self, gdf: gpd.GeoDataFrame, output_path: Path, encoding='cp949'):
        """cp949 인코딩으로 SHP 파일 저장"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            gdf.to_file(output_path, encoding=encoding)
        except Exception:
            # cp949 실패시 utf-8로 저장
            gdf.to_file(output_path, encoding='utf-8')

        # cpg 파일 생성 (인코딩 명시)
        cpg_path = output_path.with_suffix('.cpg')
        with open(cpg_path, 'w') as f:
            f.write(encoding.upper())

    # =========================================================================
    # 산사태 위험지역 근접 분석 (핵심 추가 기능)
    # =========================================================================

    def find_landslide_tif(self, region_code: str) -> Path:
        """시도코드에 해당하는 산사태위험지도 TIF 파일 찾기

        폴더 구조: 산사태위험/전북/52.tif
        """
        sido_code = self._get_sido_code(region_code)

        if not sido_code:
            return None

        # 시도코드로 지역 폴더명 조회
        region_folder_name = self.sido_to_region.get(sido_code)

        if region_folder_name:
            # 지역 폴더 내에서 TIF 파일 검색 (예: 산사태위험/전북/52.tif)
            region_folder = self.landslide_path / region_folder_name

            if region_folder.exists():
                # 파일명 패턴: {시도코드}.tif (예: 52.tif)
                possible_names = [
                    f"{sido_code}.tif",
                    f"{sido_code}_tif.tif",
                    f"산사태위험지도_{sido_code}.tif"
                ]

                for pattern in possible_names:
                    tif_path = region_folder / pattern
                    if tif_path.exists():
                        return tif_path

                # 폴더 내 모든 TIF 파일 검색
                for tif_file in region_folder.glob("*.tif"):
                    if sido_code in tif_file.name:
                        return tif_file

        # 기존 방식 (하위 호환성): 루트 폴더에서 직접 검색
        possible_names = [
            f"{sido_code}.tif",
            f"{sido_code}_tif.tif",
            f"산사태위험지도_{sido_code}.tif"
        ]

        for pattern in possible_names:
            tif_path = self.landslide_path / pattern
            if tif_path.exists():
                return tif_path

        # 전체 하위 폴더 재귀 검색
        if self.landslide_path.exists():
            for tif_file in self.landslide_path.rglob("*.tif"):
                if sido_code in tif_file.name:
                    return tif_file

        return None

    def extract_landslide_risk_boundary(self, tif_path: Path, 
                                         risk_levels: list = [1, 2],
                                         simplify_tolerance: float = 20.0) -> gpd.GeoDataFrame:
        """
        산사태 위험지도 래스터에서 위험지역 경계 추출
        
        Args:
            tif_path: 산사태위험지도 TIF 파일 경로
            risk_levels: 추출할 위험등급 (1=매우위험, 2=위험)
            simplify_tolerance: 폴리곤 단순화 허용오차 (m)
            
        Returns:
            위험지역 경계 GeoDataFrame
        """
        if not RASTERIO_AVAILABLE:
            print("  rasterio 미설치로 산사태 분석 불가")
            return None
            
        # 캐시 확인
        cache_key = str(tif_path)
        if cache_key in self._landslide_cache:
            print("  산사태 위험지역 경계 (캐시 사용)")
            return self._landslide_cache[cache_key]
            
        print(f"  산사태 위험지도 로딩: {tif_path.name}")
        
        with rasterio.open(tif_path) as src:
            data = src.read(1)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
            
            print(f"    래스터 크기: {data.shape[1]} x {data.shape[0]} 픽셀")
            print(f"    추출 대상 등급: {risk_levels}")
            
            # 위험등급만 마스크 생성
            risk_mask = np.isin(data, risk_levels)
            pixel_count = np.sum(risk_mask)
            print(f"    위험지역 픽셀 수: {pixel_count:,}개")
            
            if pixel_count == 0:
                print("    위험지역 없음")
                return None
            
            # 래스터→벡터 변환 (위험지역만)
            print("    벡터 변환 중 (시간 소요)...")
            
            # 마스크를 정수형으로 변환 (shapes 함수 요구사항)
            risk_data = np.where(risk_mask, 1, 0).astype(np.int16)
            
            polygons = []
            for geom, value in shapes(risk_data, mask=risk_mask, transform=transform):
                if value == 1:
                    polygons.append(shape(geom))
            
            print(f"    추출된 폴리곤 수: {len(polygons):,}개")
            
            if not polygons:
                return None
            
            # 폴리곤 병합 (Dissolve)
            print("    폴리곤 병합 중...")
            merged = unary_union(polygons)
            
            # 단순화 (Simplify)
            print(f"    폴리곤 단순화 중 (tolerance={simplify_tolerance}m)...")
            simplified = merged.simplify(simplify_tolerance, preserve_topology=True)
            
            # GeoDataFrame 생성
            gdf = gpd.GeoDataFrame(
                {'risk_level': ['high'], 'geometry': [simplified]},
                crs=crs
            )
            
            # 캐시 저장
            self._landslide_cache[cache_key] = gdf
            
            print(f"    최종 위험지역 폴리곤: {len(gdf)}개")
            
            return gdf

    def calculate_landslide_proximity(self, building_gdf: gpd.GeoDataFrame,
                                       tif_path: Path = None) -> gpd.GeoDataFrame:
        """
        각 건물에서 산사태 위험지역까지의 최단거리 계산 (Distance Transform 방식)

        Args:
            building_gdf: 건물 GeoDataFrame
            tif_path: 산사태위험지도 TIF 파일 경로

        Returns:
            거리 정보가 추가된 건물 GeoDataFrame
        """
        return self._landslide_distance_transform(building_gdf, tif_path)

    def _landslide_distance_transform(self, building_gdf: gpd.GeoDataFrame,
                                       tif_path: Path) -> gpd.GeoDataFrame:
        """
        거리 래스터 변환 방식 (Distance Transform) - 메모리 최적화 버전

        최적화 내용:
        - 건물 범위(bounding box)만 윈도우로 읽어 메모리 절약
        - float32 사용으로 메모리 50% 절약
        - 명시적 가비지 컬렉션
        """
        import gc

        building_gdf = building_gdf.copy()

        if tif_path is None or not tif_path.exists():
            print("    TIF 파일 없음 - 산사태 분석 불가")
            building_gdf['산사태거리'] = 99999
            building_gdf['산사태등급'] = '분석불가'
            building_gdf['산사태점수'] = 0
            return building_gdf

        print(f"    거리 래스터 생성 중: {tif_path.name}")

        with rasterio.open(tif_path) as src:
            full_transform = src.transform
            crs = src.crs
            full_width = src.width
            full_height = src.height
            pixel_size = abs(full_transform[0])

            print(f"      전체 래스터: {full_width} x {full_height} 픽셀 ({pixel_size:.1f}m 해상도)")

            # CRS 통일
            if building_gdf.crs != crs:
                building_gdf_proj = building_gdf.to_crs(crs)
            else:
                building_gdf_proj = building_gdf

            # 건물 범위 계산 (버퍼 600m 추가 - 최대 분석 거리 + 안전 마진)
            bounds = building_gdf_proj.total_bounds  # (minx, miny, maxx, maxy)
            buffer_m = 600
            minx, miny, maxx, maxy = bounds
            minx -= buffer_m
            miny -= buffer_m
            maxx += buffer_m
            maxy += buffer_m

            # 건물 범위를 래스터 윈도우로 변환
            col_start = max(0, int((minx - full_transform[2]) / full_transform[0]))
            col_end = min(full_width, int((maxx - full_transform[2]) / full_transform[0]) + 1)
            row_start = max(0, int((maxy - full_transform[5]) / full_transform[4]))
            row_end = min(full_height, int((miny - full_transform[5]) / full_transform[4]) + 1)

            window_width = col_end - col_start
            window_height = row_end - row_start

            print(f"      건물 범위 윈도우: {window_width} x {window_height} 픽셀")

            # 윈도우 읽기
            from rasterio.windows import Window
            window = Window(col_start, row_start, window_width, window_height)
            data = src.read(1, window=window)

            # 윈도우 transform 계산
            window_transform = rasterio.windows.transform(window, full_transform)

            # 위험지역 마스크 (등급 1, 2를 위험지역으로)
            risk_mask = np.isin(data, [1, 2])
            risk_pixel_count = np.sum(risk_mask)
            print(f"      위험지역 픽셀: {risk_pixel_count:,}개")

            # 원본 데이터 메모리 해제
            del data
            gc.collect()

            if risk_pixel_count == 0:
                print("      위험지역 없음")
                building_gdf['산사태거리'] = 99999
                building_gdf['산사태등급'] = '안전'
                building_gdf['산사태점수'] = 0
                return building_gdf

            # Distance Transform (float32로 메모리 절약)
            print("      거리 변환 계산 중...")
            distance_pixels = distance_transform_edt(~risk_mask).astype(np.float32)

            # 마스크 메모리 해제
            del risk_mask
            gc.collect()

            distance_meters = distance_pixels * pixel_size

            print(f"      거리 변환 완료 (최대 거리: {distance_meters.max():.0f}m)")

            # 건물 좌표를 래스터 좌표로 변환하여 거리값 샘플링
            print(f"      건물 {len(building_gdf)}개 거리 샘플링 중...")

            # 벡터화: 모든 건물의 centroid 좌표를 한 번에 추출
            centroids = building_gdf_proj.geometry.centroid
            coords_x = centroids.x.values
            coords_y = centroids.y.values

            # 좌표 → 윈도우 래스터 인덱스 변환
            cols = ((coords_x - window_transform[2]) / window_transform[0]).astype(np.int32)
            rows = ((coords_y - window_transform[5]) / window_transform[4]).astype(np.int32)

            # 래스터 범위 체크
            valid_mask = (rows >= 0) & (rows < distance_meters.shape[0]) & \
                         (cols >= 0) & (cols < distance_meters.shape[1])

            # 거리값 추출
            distances = np.full(len(building_gdf), 99999.0, dtype=np.float32)
            valid_rows = rows[valid_mask]
            valid_cols = cols[valid_mask]
            distances[valid_mask] = distance_meters[valid_rows, valid_cols]

            building_gdf['산사태거리'] = distances

            # 메모리 정리
            del distance_pixels, distance_meters, centroids
            gc.collect()

        # 거리 기반 위험등급 분류 (벡터화)
        self._classify_landslide_risk(building_gdf)

        return building_gdf

    def _classify_landslide_risk(self, gdf: gpd.GeoDataFrame) -> None:
        """산사태 거리 기반 위험등급 분류 (벡터화 버전 - apply 제거)"""
        distances = gdf['산사태거리'].values

        # 등급 경계값과 레이블/점수 배열 생성
        boundaries = np.array([0, 50, 100, 200, 300, 400, 500, 99999])
        level_names = np.array(['매우위험', '위험', '주의', '관심', '경계', '안전', '안전'])
        scores = np.array([10, 8, 6, 4, 2, 1, 0])

        # np.searchsorted로 구간 인덱스 찾기 (벡터화)
        indices = np.searchsorted(boundaries[1:], distances, side='right')
        indices = np.clip(indices, 0, len(level_names) - 1)

        gdf['산사태등급'] = level_names[indices]
        gdf['산사태점수'] = scores[indices]

        # 통계 출력
        risk_counts = gdf['산사태등급'].value_counts()
        print(f"      산사태 근접위험 분포:")
        for level in level_names:
            if level in risk_counts.index:
                print(f"        {level}: {risk_counts[level]:,}개")

    # =========================================================================
    # 기존 기능 (건물연령, 홍수위험)
    # =========================================================================

    def calculate_building_age(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """A25(건물연령) 컬럼 사용 - 작년 기준이므로 +1"""
        gdf = gdf.copy()

        if 'A25' in gdf.columns:
            # A25는 작년 기준 연령이므로 +1
            gdf['건물연령'] = gdf['A25'].apply(
                lambda x: x + 1 if pd.notna(x) and x >= 0 else None
            )
            # 건축년도 역산 (참고용)
            gdf['건축년도'] = gdf['건물연령'].apply(
                lambda x: self.current_year - x if pd.notna(x) else None
            )
        else:
            gdf['건물연령'] = None
            gdf['건축년도'] = None

        return gdf

    def classify_age_risk(self, age: float) -> tuple:
        """건물연령에 따른 노후위험도 분류"""
        if pd.isna(age) or age is None:
            return ('미확인', 0)

        for min_age, max_age, level_name, score in self.AGE_RISK_LEVELS:
            if min_age <= age < max_age:
                return (level_name, score)

        return ('초고령', 10)

    def classify_flood_risk(self, overlap_pct: float) -> tuple:
        """홍수위험 겹침비율에 따른 등급 분류"""
        if pd.isna(overlap_pct):
            return ('구역외', 1)

        for min_pct, max_pct, level_name, score in self.FLOOD_RISK_LEVELS:
            if min_pct <= overlap_pct < max_pct:
                return (level_name, score)

        return ('구역내', 10)

    def classify_combined_risk(self, total_score) -> tuple:
        """종합위험등급 분류 (모든 위험요소 단순 합산)"""
        total_score = float(total_score) if not pd.isna(total_score) else 0
        for min_score, max_score, level_name, grade in self.COMBINED_RISK_LEVELS:
            if min_score <= total_score < max_score:
                return (level_name, grade)

        return ('위험', 'E')

    def get_age_category(self, age: float) -> str:
        """연령대 카테고리 반환"""
        if pd.isna(age) or age is None:
            return '미확인'

        if age < 5:
            return '0-5년'
        elif age < 10:
            return '5-10년'
        elif age < 20:
            return '10-20년'
        elif age < 30:
            return '20-30년'
        elif age < 50:
            return '30-50년'
        elif age < 100:
            return '50-100년'
        else:
            return '100년이상'

    def list_available_regions(self):
        """사용 가능한 지역 목록 출력"""
        print("\n" + "=" * 50)
        print("사용 가능한 지역 목록")
        print("=" * 50)

        for region_name, region_info in self.region_mapping.items():
            print(f"\n[{region_name}]")
            for district_name, district_info in region_info['districts'].items():
                code = district_info.get('code', '코드없음')
                print(f"  - {district_name} (코드: {code})")

        return self.region_mapping

    def find_flood_shp(self, region_code: str) -> Path:
        """지역코드에 해당하는 홍수위험 SHP 파일 찾기"""
        for shp_file in self.flood_path.rglob("*.shp"):
            if region_code in shp_file.name:
                return shp_file
        return None

    # =========================================================================
    # 통합 분석 (노후 + 홍수 + 산사태)
    # =========================================================================

    def analyze_region(self, region_name: str, district_name: str = None,
                       min_age: int = None, max_age: int = None,
                       include_flood: bool = True,
                       include_landslide: bool = True) -> gpd.GeoDataFrame:
        """
        특정 지역 통합 분석 수행

        Args:
            region_name: 지역명 (서울, 부산, 전북 등)
            district_name: 구/군명 (None이면 해당 지역 전체)
            min_age: 최소 건물연령 필터 (이 연령 이상만 포함)
            max_age: 최대 건물연령 필터 (이 연령 이하만 포함)
            include_flood: 홍수위험 분석 포함 여부
            include_landslide: 산사태근접위험 분석 포함 여부

        Returns:
            분석 결과 GeoDataFrame
        """
        if region_name not in self.region_mapping:
            print(f"지역을 찾을 수 없습니다: {region_name}")
            return None

        region_info = self.region_mapping[region_name]

        # 분석할 구/군 목록 결정
        if district_name:
            if district_name not in region_info['districts']:
                print(f"구/군을 찾을 수 없습니다: {district_name}")
                return None
            districts_to_analyze = {district_name: region_info['districts'][district_name]}
        else:
            districts_to_analyze = region_info['districts']

        all_results = []

        for dist_name, dist_info in districts_to_analyze.items():
            print(f"\n{'='*60}")
            print(f"분석 중: {region_name} {dist_name}")
            print(f"{'='*60}")

            result = self._analyze_single_district(
                dist_info, region_name, dist_name, min_age, max_age,
                include_flood, include_landslide
            )

            if result is not None and len(result) > 0:
                all_results.append(result)

        if all_results:
            combined_result = pd.concat(all_results, ignore_index=True)
            return gpd.GeoDataFrame(combined_result, crs=all_results[0].crs)

        return None

    def _analyze_single_district(self, dist_info: dict, region_name: str,
                                  district_name: str, min_age: int, max_age: int,
                                  include_flood: bool, include_landslide: bool) -> gpd.GeoDataFrame:
        """단일 구/군 통합 분석"""
        building_shp = dist_info['building_shp']
        region_code = dist_info['code']

        print(f"  건물연령 파일: {building_shp.name}")

        # 데이터 로드
        print("  데이터 로딩 중...")
        building_gdf = self._read_shp_with_encoding(building_shp)
        print(f"  전체 건물 수: {len(building_gdf)}")

        # 건물연령 계산
        print("  건물연령 계산 중...")
        building_gdf = self.calculate_building_age(building_gdf)

        # 연령 필터링 (분석 전)
        if min_age is not None:
            before_count = len(building_gdf)
            building_gdf = building_gdf[building_gdf['건물연령'] >= min_age]
            print(f"  연령 필터링 (>={min_age}년): {before_count} → {len(building_gdf)}개")

        if max_age is not None:
            before_count = len(building_gdf)
            building_gdf = building_gdf[building_gdf['건물연령'] <= max_age]
            print(f"  연령 필터링 (<={max_age}년): {before_count} → {len(building_gdf)}개")

        if len(building_gdf) == 0:
            print("  필터링 후 건물이 없습니다.")
            return None

        # 노후위험도 계산
        age_risk = building_gdf['건물연령'].apply(self.classify_age_risk)
        building_gdf['노후등급'] = age_risk.apply(lambda x: x[0])
        building_gdf['노후점수'] = age_risk.apply(lambda x: x[1])
        building_gdf['연령대'] = building_gdf['건물연령'].apply(self.get_age_category)

        # 홍수위험 분석 (타임아웃 적용)
        if include_flood:
            flood_shp = self.find_flood_shp(region_code)
            if flood_shp:
                print(f"  홍수위험 파일: {flood_shp.name}")
                flood_gdf = self._read_shp_with_encoding(flood_shp)
                print(f"  홍수위험구역 수: {len(flood_gdf)}")
                print("  홍수위험 교차 분석 중...")
                success, result = self._run_with_timeout(
                    self._analyze_flood_intersection,
                    args=(building_gdf, flood_gdf),
                    task_name=f"홍수위험 분석 ({region_name} {district_name})"
                )
                if success and result is not None:
                    building_gdf = result
                else:
                    print("  → 홍수위험 분석 건너뜀 (타임아웃)")
                    building_gdf['겹침비율'] = 0
                    building_gdf['홍수등급'] = '타임아웃'
                    building_gdf['홍수점수'] = 1
            else:
                print(f"  홍수위험 데이터 없음 (코드: {region_code})")
                building_gdf['겹침비율'] = 0
                building_gdf['홍수등급'] = '구역외'
                building_gdf['홍수점수'] = 1
        else:
            building_gdf['겹침비율'] = 0
            building_gdf['홍수등급'] = '미분석'
            building_gdf['홍수점수'] = 1

        # 침수흔적도(전국) 추가 분석 - 홍수위험 분석 후 보완
        if include_flood and self.flood_trace_shp.exists():
            print(f"  침수흔적도 파일: {self.flood_trace_shp.name}")
            if not hasattr(self, '_flood_trace_gdf'):
                print("  침수흔적도 데이터 로딩 중 (전국, 최초 1회)...")
                self._flood_trace_gdf = self._read_shp_with_encoding(self.flood_trace_shp)
                print(f"  침수흔적도 레코드 수: {len(self._flood_trace_gdf):,}")
            print("  침수흔적도 교차 분석 중...")
            success, result = self._run_with_timeout(
                self._analyze_flood_trace_intersection,
                args=(building_gdf, self._flood_trace_gdf),
                task_name=f"침수흔적도 분석 ({region_name} {district_name})"
            )
            if success and result is not None:
                building_gdf = result
            else:
                print("  → 침수흔적도 분석 건너뜀 (타임아웃)")
        elif include_flood:
            print("  침수흔적도 파일 없음 → 건너뜀")

        # 산사태 근접위험 분석 (타임아웃 적용)
        if include_landslide and RASTERIO_AVAILABLE:
            landslide_tif = self.find_landslide_tif(region_code)
            if landslide_tif:
                print(f"  산사태위험지도 파일: {landslide_tif.name}")
                print("  산사태 근접위험 분석 중...")
                success, result = self._run_with_timeout(
                    self.calculate_landslide_proximity,
                    args=(building_gdf,),
                    kwargs={'tif_path': landslide_tif},
                    task_name=f"산사태 분석 ({region_name} {district_name})"
                )
                if success and result is not None:
                    building_gdf = result
                else:
                    print("  → 산사태 분석 건너뜀 (타임아웃)")
                    building_gdf['산사태거리'] = 99999
                    building_gdf['산사태등급'] = '타임아웃'
                    building_gdf['산사태점수'] = 1
            else:
                print(f"  산사태위험지도 데이터 없음")
                building_gdf['산사태거리'] = 99999
                building_gdf['산사태등급'] = '안전'
                building_gdf['산사태점수'] = 1
        else:
            building_gdf['산사태거리'] = 99999
            building_gdf['산사태등급'] = '미분석'
            building_gdf['산사태점수'] = 1

        # =========================================================================
        # 기본 종합점수 계산 (노후+홍수+산사태)
        # → 용도지역, 전기화재이력은 save_results에서 적용됨
        # =========================================================================
        print("  기본 종합점수 계산 중 (노후+홍수+산사태)...")

        # 개별 위험점수 정리
        building_gdf['노후점수'] = building_gdf['노후점수'].fillna(0).astype(int)
        building_gdf['홍수점수'] = building_gdf['홍수점수'].fillna(0).astype(int)
        building_gdf['산사태점수'] = building_gdf['산사태점수'].fillna(0).astype(int)

        # 기본 종합점수 (노후+홍수+산사태)
        building_gdf['종합점수'] = (
            building_gdf['노후점수'] +
            building_gdf['홍수점수'] +
            building_gdf['산사태점수']
        )

        # 종합위험등급 (임시 - save_results에서 최종 재계산)
        combined_risk = building_gdf['종합점수'].apply(self.classify_combined_risk)
        building_gdf['종합등급'] = combined_risk.apply(lambda x: x[0])
        building_gdf['위험코드'] = combined_risk.apply(lambda x: x[1])

        # =========================================================================
        # 좌표 정보 추출 (시각화용)
        # =========================================================================
        print("  좌표 정보 추출 중...")

        # 건물 중심점 좌표 추출
        building_gdf['중심점X'] = building_gdf.geometry.centroid.x
        building_gdf['중심점Y'] = building_gdf.geometry.centroid.y

        # EPSG:5186 좌표 변환 (최종 저장 시 재계산되므로 임시값)
        # 경도/위도도 EPSG:5186 기준 X/Y 좌표로 저장
        if building_gdf.crs and building_gdf.crs.to_epsg() != 5186:
            try:
                gdf_5186 = building_gdf.to_crs(epsg=5186)
                building_gdf['경도'] = gdf_5186.geometry.centroid.x
                building_gdf['위도'] = gdf_5186.geometry.centroid.y
            except Exception as e:
                print(f"    EPSG:5186 변환 실패: {e}")
                building_gdf['경도'] = building_gdf['중심점X']
                building_gdf['위도'] = building_gdf['중심점Y']
        else:
            building_gdf['경도'] = building_gdf['중심점X']
            building_gdf['위도'] = building_gdf['중심점Y']

        # 주소 정보 추출 (원본 데이터에서)
        address_cols = ['A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'A10']  # 주소 관련 컬럼들
        for col in address_cols:
            if col in building_gdf.columns:
                # 주소 컬럼이 있으면 '주소' 컬럼으로 통합
                if '주소' not in building_gdf.columns:
                    building_gdf['주소'] = building_gdf[col].fillna('')
                else:
                    building_gdf['주소'] = building_gdf['주소'] + ' ' + building_gdf[col].fillna('')

        # 지역 정보 추가
        building_gdf['지역'] = region_name
        building_gdf['구군'] = district_name
        building_gdf['지역코드'] = region_code

        print(f"  분석 완료: {len(building_gdf)}개 건물")

        return building_gdf

    def _analyze_flood_intersection(self, building_gdf: gpd.GeoDataFrame,
                                     flood_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        [고성능 최적화] 홍수위험 교차 분석 (알림 기능 추가)
        
        최적화 전략:
        1. [범위 필터링] 건물들이 위치한 영역의 홍수 데이터만 로드 (.cx 사용)
        2. [단순화] 홍수 폴리곤의 불필요한 정밀도 낮춤 (simplify)
        3. [버퍼 역발상] 건물이 아닌 홍수 구역에 버퍼를 적용 (연산 횟수 감소)
        4. [Spatial Join] R-tree 인덱스 기반 고속 검색
        """
        import gc

        FLOOD_SCORE = 10   # 홍수위험구역 내 10점
        FLOOD_SAFE = 1     # 홍수위험구역 외 1점
        BUFFER_DIST = 10   # 10m

        # CRS 통일
        if building_gdf.crs != flood_gdf.crs:
            flood_gdf = flood_gdf.to_crs(building_gdf.crs)

        total_buildings = len(building_gdf)

        # ---------------------------------------------------------
        # 최적화 1: 범위 필터링 (Bounding Box Filtering)
        # ---------------------------------------------------------
        try:
            xmin, ymin, xmax, ymax = building_gdf.total_bounds
            # 건물 범위보다 버퍼 거리만큼 더 넓게 잡아서 검색
            flood_subset = flood_gdf.cx[xmin-BUFFER_DIST:xmax+BUFFER_DIST, 
                                      ymin-BUFFER_DIST:ymax+BUFFER_DIST].copy()
        except Exception:
            flood_subset = flood_gdf.copy()

        if len(flood_subset) == 0:
            print("    [최적화] 해당 지역 내 홍수위험지역 없음")
            building_gdf['홍수등급'] = '구역외'
            building_gdf['홍수점수'] = FLOOD_SAFE
            building_gdf['겹침비율'] = 0
            return building_gdf

        print(f"    [최적화] 분석 대상 홍수 구역 필터링: {len(flood_gdf):,}개 → {len(flood_subset):,}개")

        # ---------------------------------------------------------
        # 최적화 2: 폴리곤 단순화 (Simplification)
        # ---------------------------------------------------------
        # 0.5m 이하의 디테일은 직선화하여 연산 속도 향상
        print("    [진행] 데이터 구조 분해 및 단순화 시작...")
        
        # [Step A] MultiPolygon 분해 (Explode)
        # 거대한 덩어리를 개별 조각으로 쪼갭니다. 처리 속도가 빨라집니다.
        if 'MultiPolygon' in flood_subset.geometry.type.unique():
             flood_subset = flood_subset.explode(index_parts=False)

        # [Step B] 단순화 강도 조절 (0.5 -> 2.0)
        # 해안선같이 점이 많은 데이터는 2m 정도의 오차를 허용해도 분석에 지장 없습니다.
        # 속도는 5배 이상 빨라집니다.
        flood_subset['geometry'] = flood_subset.geometry.simplify(tolerance=2.0, preserve_topology=True)
        
        # [Step C] 유효성 검사 (옵션)
        # 단순화 과정에서 꼬인 도형이 생길 수 있어 buffer(0)으로 펴줍니다.
        # (시간이 너무 걸리면 이 줄은 주석 처리하세요)
        flood_subset['geometry'] = flood_subset.geometry.buffer(0)
        
        print(f"    [완료] 데이터 전처리 완료 ({len(flood_subset):,}개 객체)")  # <--- 알림 추가

        # ---------------------------------------------------------
        # 최적화 3: 홍수 구역 버퍼링 (역발상)
        # ---------------------------------------------------------
        print(f"    [진행] 홍수 구역 버퍼링 ({BUFFER_DIST}m) 시작...")
        flood_subset['geometry'] = flood_subset.geometry.buffer(BUFFER_DIST)
        print("    [완료] 홍수 구역 버퍼링 완료")  # <--- 알림 추가

        # ---------------------------------------------------------
        # 최적화 4: Spatial Join
        # ---------------------------------------------------------
        print("    [분석] 공간 인덱싱 및 교차 검사 (sjoin)...")
        
        try:
            # 건물은 점(Centroid) 상태로 사용 (가벼움)
            temp_buildings = gpd.GeoDataFrame(
                index=building_gdf.index,
                geometry=building_gdf.geometry.centroid,
                crs=building_gdf.crs
            )

            # 교차 검사
            joined = gpd.sjoin(temp_buildings, flood_subset[['geometry']], how='inner', predicate='intersects')
            risk_indices = joined.index.unique()
            
            # 결과 적용
            building_gdf['홍수점수'] = FLOOD_SAFE
            building_gdf['홍수등급'] = '구역외'
            building_gdf['겹침비율'] = 0

            if len(risk_indices) > 0:
                building_gdf.loc[risk_indices, '홍수점수'] = FLOOD_SCORE
                building_gdf.loc[risk_indices, '홍수등급'] = '구역내'
                building_gdf.loc[risk_indices, '겹침비율'] = 100
            
            print(f"    교차 분석 완료: {len(risk_indices):,}개 건물 위험 확인")
            
            del temp_buildings, joined, flood_subset
            gc.collect()

        except Exception as e:
            print(f"    [오류] 분석 중 예외 발생: {e}")
            building_gdf['홍수점수'] = FLOOD_SAFE
            building_gdf['홍수등급'] = '오류'

        return building_gdf

    def _analyze_flood_trace_intersection(self, building_gdf: gpd.GeoDataFrame,
                                           flood_trace_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        침수흔적도(전국) 교차 분석
        - 기존 홍수위험 분석에서 '구역외'(1점)인 건물만 대상으로 분석
        - 침수흔적도와 겹치면 홍수점수를 10점으로 업그레이드
        - 이미 홍수위험구역 내(10점)인 건물은 변경하지 않음 (중복 가중치 방지)
        """
        import gc

        FLOOD_SCORE = 10
        BUFFER_DIST = 10  # 10m

        # CRS 통일
        if building_gdf.crs != flood_trace_gdf.crs:
            flood_trace_gdf = flood_trace_gdf.to_crs(building_gdf.crs)

        # 이미 홍수위험구역 내인 건물은 제외하고, 구역외 건물만 대상
        safe_mask = building_gdf['홍수점수'] < FLOOD_SCORE
        safe_count = safe_mask.sum()

        if safe_count == 0:
            print("    [침수흔적도] 모든 건물이 이미 홍수위험구역 내 → 추가 분석 불필요")
            return building_gdf

        print(f"    [침수흔적도] 구역외 건물 {safe_count:,}개 대상 분석 시작...")

        # 범위 필터링
        try:
            xmin, ymin, xmax, ymax = building_gdf.total_bounds
            trace_subset = flood_trace_gdf.cx[xmin-BUFFER_DIST:xmax+BUFFER_DIST,
                                              ymin-BUFFER_DIST:ymax+BUFFER_DIST].copy()
        except Exception:
            trace_subset = flood_trace_gdf.copy()

        if len(trace_subset) == 0:
            print("    [침수흔적도] 해당 지역 내 침수흔적 없음")
            return building_gdf

        print(f"    [침수흔적도] 분석 대상 필터링: {len(flood_trace_gdf):,}개 → {len(trace_subset):,}개")

        # MultiPolygon 분해 및 단순화
        if 'MultiPolygon' in trace_subset.geometry.type.unique():
            trace_subset = trace_subset.explode(index_parts=False)

        # None geometry 제거
        trace_subset = trace_subset[trace_subset.geometry.notna()].copy()

        trace_subset['geometry'] = trace_subset.geometry.simplify(tolerance=2.0, preserve_topology=True)
        trace_subset['geometry'] = trace_subset.geometry.buffer(0)

        # 버퍼링
        trace_subset['geometry'] = trace_subset.geometry.buffer(BUFFER_DIST)

        # 구역외 건물만 추출하여 Spatial Join
        try:
            safe_buildings = building_gdf.loc[safe_mask].copy()
            temp_buildings = gpd.GeoDataFrame(
                index=safe_buildings.index,
                geometry=safe_buildings.geometry.centroid,
                crs=building_gdf.crs
            )

            joined = gpd.sjoin(temp_buildings, trace_subset[['geometry']], how='inner', predicate='intersects')
            risk_indices = joined.index.unique()

            if len(risk_indices) > 0:
                building_gdf.loc[risk_indices, '홍수점수'] = FLOOD_SCORE
                building_gdf.loc[risk_indices, '홍수등급'] = '구역내'

            print(f"    [침수흔적도] 추가 위험 건물: {len(risk_indices):,}개")

            del temp_buildings, joined, trace_subset
            gc.collect()

        except Exception as e:
            print(f"    [침수흔적도] 분석 중 오류: {e}")

        return building_gdf

    def _apply_fire_history_score(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        전기화재이력과 겹치는 건물에 화재점수 가산.

        - 5m 이내: 10점
        - 10m 이내: 8점
        - 20m 이내: 6점
        - 20m 초과: 0점
        - 화재발생일: 화재 점좌표 기준 10m 버퍼가 건물과 교차할 때만 반영
        """
        import gc

        # 전기화재이력 SHP 파일 경로
        fire_shp_path = self.base_path / "전기화재이력" / "전기화재_2022_2024_좌표변환_5186.shp"

        if not fire_shp_path.exists():
            print(f"\n[전기화재이력] 파일 없음: {fire_shp_path}")
            print("  → 전기화재 점수 미적용")
            gdf['화재점수'] = 0
            gdf['전기화재'] = 0
            gdf['화재발생일'] = ''
            return gdf

        print(f"\n" + "=" * 70)
        print("전기화재이력 점수 분석")
        print("=" * 70)
        print(f"  전기화재 데이터: {fire_shp_path.name}")
        print(f"  기준: 5m 이내 → 10점, 10m 이내 → 8점, 20m 이내 → 6점")

        try:
            # 전기화재이력 데이터 로드
            fire_gdf = gpd.read_file(fire_shp_path, encoding='cp949')
            print(f"  전기화재 이력 수: {len(fire_gdf)}건")

            # 좌표계 통일 (EPSG:5186)
            if fire_gdf.crs is None:
                fire_gdf = fire_gdf.set_crs(epsg=5186)
            elif fire_gdf.crs.to_epsg() != 5186:
                fire_gdf = fire_gdf.to_crs(epsg=5186)

            # 건물 GeoDataFrame 좌표계 확인 (복사 최소화)
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=5186)
            elif gdf.crs.to_epsg() != 5186:
                gdf = gdf.to_crs(epsg=5186)

            # 화재일자 컬럼 탐지
            date_col_candidates = [
                '화재발생일', '발생일', '발생일자', '화재일자', '화재일',
                'FIRE_DATE', 'FIRE_DT', 'OCCUR_DATE', 'OCCUR_DT'
            ]
            fire_date_col = next((c for c in date_col_candidates if c in fire_gdf.columns), None)

            # 점 좌표 생성 (요청사항: 점 좌표 기준)
            if {'X_5186', 'Y_5186'}.issubset(fire_gdf.columns):
                fire_points = fire_gdf.copy()
                fire_points['X_5186'] = pd.to_numeric(fire_points['X_5186'], errors='coerce')
                fire_points['Y_5186'] = pd.to_numeric(fire_points['Y_5186'], errors='coerce')
                fire_points = fire_points.dropna(subset=['X_5186', 'Y_5186'])
                fire_points = gpd.GeoDataFrame(
                    fire_points,
                    geometry=gpd.points_from_xy(fire_points['X_5186'], fire_points['Y_5186']),
                    crs='EPSG:5186'
                )
            else:
                # 좌표 컬럼이 없으면 geometry가 Point인 경우만 사용
                fire_points = fire_gdf.copy()
                fire_points = fire_points[fire_points.geometry.notna()]
                fire_points = fire_points[fire_points.geometry.geom_type == 'Point']

            print(f"  점 좌표 유효 건수: {len(fire_points)}건")

            if len(fire_points) == 0:
                print("  → 점 좌표가 없어 전기화재 점수/일자 반영 불가")
                gdf['화재점수'] = 0
                gdf['전기화재'] = 0
                gdf['화재발생일'] = ''
                return gdf

            # 건물 인덱스 저장
            gdf['_orig_idx'] = range(len(gdf))
            gdf['화재발생일'] = ''

            # 버퍼 생성 (점 좌표 기준)
            print("  버퍼 생성 중...")
            fire_gdf_5m = fire_points.copy()
            fire_gdf_5m['geometry'] = fire_gdf_5m.geometry.buffer(5)

            fire_gdf_10m = fire_points.copy()
            fire_gdf_10m['geometry'] = fire_gdf_10m.geometry.buffer(10)

            fire_gdf_20m = fire_points.copy()
            fire_gdf_20m['geometry'] = fire_gdf_20m.geometry.buffer(20)

            # 결과 배열 초기화 (기본값: 0 = 범위 밖)
            fire_flags = np.zeros(len(gdf), dtype=np.int8)

            # 1단계: 20m 범위 교차 건물 추출 (sjoin)
            print("  20m 범위 교차 분석 중...")
            joined_20m = gpd.sjoin(gdf[['_orig_idx', 'geometry']], fire_gdf_20m[['geometry']],
                                   how='inner', predicate='intersects')
            indices_20m = joined_20m['_orig_idx'].unique()
            fire_flags[indices_20m] = 1  # 20m 이내
            print(f"    20m 교차 건물: {len(indices_20m):,}개")

            del joined_20m, fire_gdf_20m
            gc.collect()

            # 2단계: 10m 범위 교차 건물 추출 (sjoin)
            print("  10m 범위 교차 분석 중...")
            joined_10m = gpd.sjoin(gdf[['_orig_idx', 'geometry']], fire_gdf_10m[['geometry']],
                                   how='inner', predicate='intersects')
            indices_10m = joined_10m['_orig_idx'].unique()
            fire_flags[indices_10m] = 2  # 10m 이내 (20m보다 우선)
            print(f"    10m 교차 건물: {len(indices_10m):,}개")

            del joined_10m, fire_gdf_10m
            gc.collect()

            # 3단계: 5m 범위 교차 건물 추출 (sjoin)
            print("  5m 범위 교차 분석 중...")
            joined_5m = gpd.sjoin(gdf[['_orig_idx', 'geometry']], fire_gdf_5m[['geometry']],
                                   how='inner', predicate='intersects')
            indices_5m = joined_5m['_orig_idx'].unique()
            fire_flags[indices_5m] = 3  # 5m 이내 (가장 높은 우선순위)
            print(f"    5m 교차 건물: {len(indices_5m):,}개")

            del joined_5m, fire_gdf_5m
            gc.collect()

            # 결과 적용
            gdf['전기화재'] = fire_flags

            # 화재점수 컬럼 생성 (벡터화): 0=범위밖, 1=20m, 2=10m, 3=5m
            score_map = np.array([0, 6, 8, 10])
            gdf['화재점수'] = score_map[fire_flags]

            # 통계 출력 (벡터화)
            counts = np.bincount(fire_flags, minlength=4)
            print(f"  5m 이내: {counts[3]:,}건 → 10점")
            print(f"  10m 이내: {counts[2]:,}건 → 8점")
            print(f"  20m 이내: {counts[1]:,}건 → 6점")
            print(f"  범위 밖: {counts[0]:,}건 → 0점")

            # 화재발생일 매핑: 점 좌표 10m + 5m 기준으로 반영
            if fire_date_col:
                date_joins = []
                for date_buf_m in (10, 5):
                    fire_points_for_date = fire_points[[fire_date_col, 'geometry']].copy()
                    fire_points_for_date['geometry'] = fire_points_for_date.geometry.buffer(date_buf_m)

                    join_part = gpd.sjoin(
                        gdf[['_orig_idx', 'geometry']],
                        fire_points_for_date[[fire_date_col, 'geometry']],
                        how='inner',
                        predicate='intersects'
                    )
                    if len(join_part) > 0:
                        date_joins.append(join_part[['_orig_idx', fire_date_col]])

                if date_joins:
                    date_join = pd.concat(date_joins, ignore_index=True)
                    date_join[fire_date_col] = date_join[fire_date_col].apply(
                        lambda v: '' if pd.isna(v) else str(v).strip()
                    )
                    date_join = date_join[date_join[fire_date_col] != '']

                    if len(date_join) > 0:
                        # 동일 건물-동일 날짜 중복 제거 후 병합
                        date_join = date_join.drop_duplicates(subset=['_orig_idx', fire_date_col], keep='first')
                        fire_dates_by_building = date_join.groupby('_orig_idx')[fire_date_col].apply(
                            lambda s: '|'.join(pd.unique(s))
                        )
                        for idx, fire_dates in fire_dates_by_building.items():
                            gdf.at[int(idx), '화재발생일'] = fire_dates

                print(f"  화재발생일 반영 건물: {(gdf['화재발생일'] != '').sum():,}개")
            else:
                print("  화재발생일 컬럼을 찾지 못해 날짜 반영을 건너뜁니다.")

            # 종합점수에 화재점수 합산
            if '종합점수' in gdf.columns:
                gdf['종합점수'] = gdf['종합점수'].astype(float) + gdf['화재점수'].astype(float)
                print(f"  → 종합점수에 화재점수 합산 완료")

            del fire_points
            gc.collect()

            # 임시 컬럼 제거
            gdf.drop(columns=['_orig_idx'], inplace=True, errors='ignore')

            print("=" * 70)

        except Exception as e:
            print(f"  전기화재이력 분석 오류: {e}")
            print("  → 전기화재 점수 미적용")
            gdf['화재점수'] = 0
            gdf['전기화재'] = 0
            gdf['화재발생일'] = ''
            gdf.drop(columns=['_orig_idx'], inplace=True, errors='ignore')

        return gdf

    def _apply_landuse_score(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        용도지역지구 위험도 점수 추가
        전국 단위 용도지역지구 SHP(용도지역지구/전국)로 일괄 적용

        Args:
            gdf: 분석 결과 GeoDataFrame

        Returns:
            용도지역 점수가 추가된 GeoDataFrame
        """
        import pandas as pd
        import re

        # 용도지역 코드 CSV 로드 (루트 폴더 우선)
        code_csv_path = self.base_path / "UQ111_용도지역_코드.csv"
        if not code_csv_path.exists():
            code_csv_path = self.base_path / "용도지역지구" / "UQ111_용도지역_코드.csv"

        if not code_csv_path.exists():
            print(f"\n[용도지역] 코드 파일 없음")
            gdf['용도코드'] = ''
            gdf['용도명'] = ''
            gdf['용도점수'] = 0.0
            return gdf

        # 코드 CSV 로드
        code_df = pd.read_csv(code_csv_path, encoding='utf-8-sig')
        # 컬럼명 호환성 처리 (위험도점수 또는 위험점수)
        score_col = '위험도점수' if '위험도점수' in code_df.columns else '위험점수'
        code_dict = dict(zip(code_df['코드값'], code_df[score_col]))
        name_dict = dict(zip(code_df['코드값'], code_df['코드값의미']))

        print(f"\n" + "=" * 70)
        print("용도지역지구 위험도 분석")
        print("=" * 70)
        print("  분석 소스: 용도지역지구/전국")

        # 결과 컬럼 초기화 (SHP 10자 제한 고려)
        gdf['용도코드'] = ''
        gdf['용도명'] = ''
        gdf['용도점수'] = 0.0

        def extract_ucode(mnum):
            if pd.isna(mnum):
                return ''
            match = re.search(r'(UQA\d{3})', str(mnum))
            return match.group(1) if match else ''

        national_landuse_dir = self.base_path / "용도지역지구" / "전국"
        if not national_landuse_dir.exists():
            print(f"  [전국] 폴더 없음: {national_landuse_dir}")
            return gdf

        shp_files = sorted(national_landuse_dir.glob("*.shp"))
        if not shp_files:
            print(f"  [전국] SHP 파일 없음: {national_landuse_dir}")
            return gdf

        try:
            landuse_parts = []
            for shp_file in shp_files:
                print(f"  [전국] 로딩: {shp_file.name}")
                part_gdf = gpd.read_file(shp_file, encoding='cp949')

                mnum_col = next((c for c in part_gdf.columns if str(c).upper() == 'MNUM'), None)
                a5_col = next((c for c in part_gdf.columns if str(c).upper() == 'A5'), None)
                a1_col = next((c for c in part_gdf.columns if str(c).upper() == 'A1'), None)

                if mnum_col is not None:
                    part_gdf['UCODE'] = part_gdf[mnum_col].apply(extract_ucode)
                    print(f"    - UCODE 추출 컬럼: {mnum_col}")
                elif a5_col is not None:
                    # 전국 SHP(AL_D124_00_*)는 A5에 UQA코드가 직접 들어있음
                    part_gdf['UCODE'] = part_gdf[a5_col].astype(str).str.extract(r'(UQA\d{3})', expand=False).fillna('')
                    print(f"    - UCODE 추출 컬럼: {a5_col}")
                elif a1_col is not None:
                    # 일부 변형본은 A1 문자열 내부에 UQA코드가 포함됨
                    part_gdf['UCODE'] = part_gdf[a1_col].astype(str).apply(extract_ucode)
                    print(f"    - UCODE 추출 컬럼: {a1_col}")
                else:
                    print("    - UCODE 추출 가능한 컬럼(MNUM/A5/A1) 없음, 건너뜀")
                    continue

                # 좌표계 통일
                if part_gdf.crs is None:
                    part_gdf = part_gdf.set_crs(epsg=5186)
                elif part_gdf.crs.to_epsg() != 5186:
                    part_gdf = part_gdf.to_crs(epsg=5186)

                landuse_parts.append(part_gdf[['UCODE', 'geometry']].copy())

            if not landuse_parts:
                print("  [전국] 사용 가능한 SHP 데이터가 없어 건너뜀")
                return gdf

            landuse_gdf = gpd.GeoDataFrame(
                pd.concat(landuse_parts, ignore_index=True),
                crs=landuse_parts[0].crs
            )
            landuse_gdf = landuse_gdf[(landuse_gdf['UCODE'] != '') & landuse_gdf.geometry.notna()]

            if len(landuse_gdf) == 0:
                print("  [전국] 유효 UCODE 데이터 없음")
                return gdf

            # 건물 좌표계 통일
            gdf_work = gdf.copy()
            if gdf_work.crs is None:
                gdf_work = gdf_work.set_crs(epsg=5186)
            elif gdf_work.crs.to_epsg() != 5186:
                gdf_work = gdf_work.to_crs(epsg=5186)

            # 공간 조인 (건물 중심점 기준)
            gdf_points = gpd.GeoDataFrame(
                geometry=gdf_work.geometry.centroid,
                index=gdf_work.index,
                crs=gdf_work.crs
            )
            joined = gpd.sjoin(
                gdf_points,
                landuse_gdf[['UCODE', 'geometry']],
                how='left',
                predicate='within'
            )
            joined = joined[~joined.index.duplicated(keep='first')]
            joined_ucode = joined['UCODE'].reindex(gdf.index).fillna('')

            # 결과 반영 (SHP 10자 제한 고려: 용도코드, 용도명, 용도점수)
            gdf['용도코드'] = joined_ucode.values
            gdf['용도명'] = gdf['용도코드'].map(name_dict).fillna('')
            gdf['용도점수'] = gdf['용도코드'].map(code_dict).fillna(0.0)

            total_matched = (gdf['용도코드'] != '').sum()
            print(f"  [전국] 매칭 건물: {total_matched:,}개")

        except Exception as e:
            print(f"  [전국] 분석 오류: {e}")
            return gdf

        # 종합점수에 합산
        if '종합점수' in gdf.columns:
            gdf['종합점수'] = gdf['종합점수'].astype(float) + gdf['용도점수'].astype(float)

        # 통계 출력
        avg_score = gdf['용도점수'].mean()
        print(f"\n  총 매칭 건물: {total_matched}개 / {len(gdf)}개")
        print(f"  평균 용도지역 점수: {avg_score:.2f}점")
        print(f"  → 종합점수에 합산 완료")
        print("=" * 70)

        return gdf

    def save_results(self, gdf: gpd.GeoDataFrame, filename: str = None,
                     region_name: str = None, district_name: str = None,
                     min_age: int = None, search_query: str = None) -> Path:
        """분석 결과 저장 (EPSG:5186 좌표계)

        Args:
            search_query: 원래 사용자 입력값 (저장 경로 결정에 사용)
        """
        if gdf is None or len(gdf) == 0:
            print("저장할 데이터가 없습니다.")
            return None

        # 파일명 생성
        if filename is None:
            parts = ['통합위험분석']
            # 사업소명(search_query)이 있으면 우선 사용
            if search_query and ('지사' in search_query or '직할' in search_query or '본부' in search_query):
                parts.append(search_query)
            else:
                if region_name:
                    parts.append(region_name)
                if district_name:
                    parts.append(district_name)
            if min_age:
                parts.append(f'{min_age}년이상')
            parts.append(datetime.now().strftime('%Y%m%d'))
            filename = '_'.join(parts) + '.shp'

        # 저장 경로 결정 (search_query에 따라 동적 경로)
        if search_query:
            output_dir = self._get_output_directory(search_query, region_name, district_name)
        else:
            output_dir = self.output_path
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # =====================================================================
        # 용도지역지구 위험도 점수 적용 (직접 실행)
        # NOTE: ThreadPool 타임아웃 경유 시 값이 빈값으로 초기화되는 사례가 있어
        #       저장 단계에서는 직접 실행 + 실패 시 중단으로 처리한다.
        # =====================================================================
        try:
            gdf = self._apply_landuse_score(gdf)
        except Exception as e:
            raise RuntimeError(f"용도지역 분석 실패: {e}") from e

        landuse_matched = 0
        if '용도코드' in gdf.columns:
            landuse_matched = int((gdf['용도코드'].astype(str).str.strip() != '').sum())
        print(f"  용도지역 매칭 건수(저장 전): {landuse_matched:,}개")
        if landuse_matched == 0:
            raise RuntimeError("용도지역 매칭 결과가 0건입니다. 산출물을 저장하지 않습니다.")

        # =====================================================================
        # 전기화재이력 점수 합산 (직접 실행)
        # =====================================================================
        try:
            gdf = self._apply_fire_history_score(gdf)
        except Exception as e:
            raise RuntimeError(f"전기화재이력 분석 실패: {e}") from e

        fire_date_cnt = 0
        if '화재발생일' in gdf.columns:
            fire_date_cnt = int((gdf['화재발생일'].astype(str).str.strip() != '').sum())
        print(f"  화재발생일 반영 건수(저장 전): {fire_date_cnt:,}개")

        # =====================================================================
        # 최종 종합등급 재계산: 노후+홍수+산사태+용도지역+전기화재 단순 합산
        # =====================================================================
        print("\n최종 종합 위험등급 계산 중...")
        combined_risk = gdf['종합점수'].apply(self.classify_combined_risk)
        gdf['종합등급'] = combined_risk.apply(lambda x: x[0])
        gdf['위험코드'] = combined_risk.apply(lambda x: x[1])
        print(f"  → 최종 종합등급 계산 완료 (단순 합산)")

        # EPSG:5186 좌표계로 변환
        print(f"\n좌표계 변환 중 (EPSG:5186)...")
        gdf_5186 = gdf.copy()

        try:
            if gdf_5186.crs and gdf_5186.crs.to_epsg() != 5186:
                gdf_5186 = gdf_5186.to_crs(epsg=5186)
                print(f"  원본 좌표계: {gdf.crs} → EPSG:5186 변환 완료")
            elif not gdf_5186.crs:
                gdf_5186 = gdf_5186.set_crs(epsg=5186)
                print(f"  좌표계 설정: EPSG:5186")
        except Exception as e:
            print(f"  좌표계 변환 실패: {e}")
            print(f"  원본 좌표계로 저장합니다.")
            gdf_5186 = gdf.copy()

        # 모든 좌표를 EPSG:5186 기준으로 재계산
        print("  좌표 재계산 (EPSG:5186)...")
        gdf_5186['중심점X'] = gdf_5186.geometry.centroid.x
        gdf_5186['중심점Y'] = gdf_5186.geometry.centroid.y
        gdf_5186['경도'] = gdf_5186.geometry.centroid.x
        gdf_5186['위도'] = gdf_5186.geometry.centroid.y

        # SHP 저장 (cp949 인코딩)
        print(f"\n결과 저장 중: {output_path}")
        self._save_shp_with_encoding(gdf_5186, output_path, encoding='cp949')

        # CSV 요약 저장 (모든 분석 결과 포함)
        csv_path = output_path.with_suffix('.csv')
        summary_cols = [
            # 위치 정보
            '지역', '구군', '지역코드', '주소',
            '중심점X', '중심점Y', '경도', '위도',
            # 건물 정보
            '건축년도', '건물연령', '연령대', 'A17', 'A19',
            # 개별 위험도
            '노후등급', '노후점수',
            '겹침비율', '홍수등급', '홍수점수',
            '산사태거리', '산사태등급', '산사태점수',
            # 용도지역지구
            '용도코드', '용도명', '용도점수',
            # 전기화재이력
            '전기화재', '화재점수', '화재발생일',
            # 최종 종합 위험도: 노후+홍수+산사태+용도지역+전기화재 단순 합산
            '종합점수', '종합등급', '위험코드'
        ]

        # 존재하는 컬럼만 선택
        available_cols = [col for col in summary_cols if col in gdf_5186.columns]
        gdf_5186[available_cols].to_csv(csv_path, index=False, encoding='utf-8-sig')

        print(f"CSV 요약 저장: {csv_path}")
        print(f"  - 포함 컬럼: {len(available_cols)}개")

        return output_path

    def print_summary(self, gdf: gpd.GeoDataFrame):
        """분석 결과 요약 출력"""
        if gdf is None or len(gdf) == 0:
            print("분석 결과가 없습니다.")
            return

        print("\n" + "=" * 70)
        print("              통합 위험분석 결과 요약")
        print("=" * 70)

        print(f"\n총 분석 건물 수: {len(gdf):,}개")
        print(f"분석 기준 연도: {self.current_year}년")

        # =========================================================================
        # 1. 개별 위험요소 분석 결과
        # =========================================================================
        print("\n" + "-" * 70)
        print("1. 개별 위험요소 분석")
        print("-" * 70)

        # 1-1. 노후위험도
        print("\n[1-1. 노후위험도]")
        print(f"  연령대별 분포:")
        age_counts = gdf['연령대'].value_counts()
        for age_cat, count in age_counts.items():
            pct = 100 * count / len(gdf)
            print(f"    {age_cat}: {count:,}개 ({pct:.1f}%)")

        print(f"\n  노후등급별 분포:")
        age_risk_counts = gdf['노후등급'].value_counts()
        for level, count in age_risk_counts.items():
            pct = 100 * count / len(gdf)
            print(f"    {level}: {count:,}개 ({pct:.1f}%)")

        avg_age = gdf['건물연령'].mean()
        print(f"\n  평균 건물연령: {avg_age:.1f}년")

        # 1-2. 홍수위험도
        if '홍수등급' in gdf.columns:
            print("\n[1-2. 홍수/침수위험도]")
            print("  (홍수/침수위험구역 내: 10점, 구역 외: 1점)")
            flood_risk_counts = gdf['홍수등급'].value_counts()
            for level, count in flood_risk_counts.items():
                pct = 100 * count / len(gdf)
                score = 10 if level == '구역내' else 1
                print(f"    {level} ({score}점): {count:,}개 ({pct:.1f}%)")

            flood_buildings = (gdf['홍수점수'] >= 10).sum()
            print(f"\n  홍수/침수위험구역 내 건물: {flood_buildings:,}개 ({100*flood_buildings/len(gdf):.1f}%)")

        # 1-3. 산사태근접위험도
        if '산사태등급' in gdf.columns:
            print("\n[1-3. 산사태근접위험도]")
            landslide_counts = gdf['산사태등급'].value_counts()
            for level, count in landslide_counts.items():
                pct = 100 * count / len(gdf)
                print(f"    {level}: {count:,}개 ({pct:.1f}%)")

            valid_distances = gdf[gdf['산사태거리'] < 99999]['산사태거리']
            if len(valid_distances) > 0:
                print(f"\n  평균 산사태위험지역 거리: {valid_distances.mean():.1f}m")
                print(f"  최소 거리: {valid_distances.min():.1f}m")

        # 1-4. 용도지역지구 위험도
        if '용도점수' in gdf.columns:
            print("\n[1-4. 용도지역지구 위험도]")
            matched = (gdf['용도코드'] != '').sum()
            unmatched = len(gdf) - matched
            print(f"  용도지역 매칭: {matched:,}개 ({100*matched/len(gdf):.1f}%)")
            print(f"  미매칭: {unmatched:,}개 ({100*unmatched/len(gdf):.1f}%)")

            if matched > 0:
                matched_gdf = gdf[gdf['용도코드'] != '']
                avg_score = matched_gdf['용도점수'].mean()
                max_score = matched_gdf['용도점수'].max()
                print(f"\n  평균 용도지역 점수: {avg_score:.2f}점")
                print(f"  최고 용도지역 점수: {max_score:.1f}점")

                # 용도지역별 분포 (상위 5개)
                print(f"\n  용도지역별 분포 (상위 5개):")
                landuse_counts = matched_gdf['용도명'].value_counts().head(5)
                for landuse, count in landuse_counts.items():
                    score = matched_gdf[matched_gdf['용도명'] == landuse]['용도점수'].iloc[0]
                    pct = 100 * count / len(gdf)
                    print(f"    {landuse} ({score}점): {count:,}개 ({pct:.1f}%)")

        # 1-5. 전기화재이력 위험도
        if '화재점수' in gdf.columns:
            print("\n[1-5. 전기화재이력 위험도]")
            fire_5m = (gdf['전기화재'] == 3).sum() if '전기화재' in gdf.columns else 0
            fire_10m = (gdf['전기화재'] == 2).sum() if '전기화재' in gdf.columns else 0
            fire_20m = (gdf['전기화재'] == 1).sum() if '전기화재' in gdf.columns else 0
            fire_none = (gdf['화재점수'] == 0).sum()

            print(f"  5m 이내 (10점): {fire_5m:,}개 ({100*fire_5m/len(gdf):.1f}%)")
            print(f"  10m 이내 (8점): {fire_10m:,}개 ({100*fire_10m/len(gdf):.1f}%)")
            print(f"  20m 이내 (6점): {fire_20m:,}개 ({100*fire_20m/len(gdf):.1f}%)")
            print(f"  범위 밖 (0점): {fire_none:,}개 ({100*fire_none/len(gdf):.1f}%)")

            avg_fire = gdf['화재점수'].mean()
            print(f"\n  평균 화재점수: {avg_fire:.2f}점")

        # =========================================================================
        # 2. 요소별 위험도 현황
        # =========================================================================
        print("\n" + "-" * 70)
        print("2. 요소별 위험도 현황")
        print("-" * 70)

        print("\n[위험요소별 평균 점수]")
        avg_age_score = gdf['노후점수'].mean()
        avg_flood_score = gdf['홍수점수'].mean()
        avg_landslide_score = gdf['산사태점수'].mean()
        print(f"    노후위험:     {avg_age_score:.2f}점")
        print(f"    홍수/침수위험: {avg_flood_score:.2f}점")
        print(f"    산사태위험:   {avg_landslide_score:.2f}점")

        if '용도점수' in gdf.columns:
            avg_landuse_score = gdf['용도점수'].mean()
            print(f"    용도지역위험: {avg_landuse_score:.2f}점")

        if '화재점수' in gdf.columns:
            avg_fire_score = gdf['화재점수'].mean()
            fire_applied = (gdf['화재점수'] > 0).sum()
            print(f"    전기화재점수: 평균 {avg_fire_score:.2f}점 (적용 건물: {fire_applied:,}개)")

        print("\n[위험요소별 고위험 건물 수]")
        high_age = (gdf['노후점수'] >= 8).sum()
        high_flood = (gdf['홍수점수'] >= 10).sum()
        high_landslide = (gdf['산사태점수'] >= 6).sum()
        print(f"    노후 8점 이상:     {high_age:,}개 ({100*high_age/len(gdf):.1f}%)")
        print(f"    홍수/침수 10점 (구역내): {high_flood:,}개 ({100*high_flood/len(gdf):.1f}%)")
        print(f"    산사태 6점 이상:   {high_landslide:,}개 ({100*high_landslide/len(gdf):.1f}%)")

        if '용도점수' in gdf.columns:
            high_landuse = (gdf['용도점수'] >= 3).sum()
            print(f"    용도지역 3점 이상: {high_landuse:,}개 ({100*high_landuse/len(gdf):.1f}%)")

        # =========================================================================
        # 3. 최종 종합 위험도 분석
        # =========================================================================
        print("\n" + "-" * 70)
        print("3. 최종 종합 위험도 분석")
        print("   노후+홍수/침수+산사태+용도지역+전기화재 단순 합산")
        print("-" * 70)

        print("\n[종합위험등급별 건물 수]")
        combined_counts = gdf['종합등급'].value_counts()
        for level, count in combined_counts.items():
            code = gdf[gdf['종합등급'] == level]['위험코드'].iloc[0]
            pct = 100 * count / len(gdf)
            print(f"    {code}등급 ({level}): {count:,}개 ({pct:.1f}%)")

        # 최고 위험 건물
        max_score = gdf['종합점수'].max()
        max_risk = gdf[gdf['종합점수'] == max_score]
        print(f"\n  최고 위험 건물 (종합점수 {max_score:.1f}점): {len(max_risk):,}개")

        avg_final = gdf['종합점수'].mean()
        print(f"  평균 종합점수: {avg_final:.2f}점")

        # 위험등급 D/E 건물 수 (각각 표시)
        d_grade = gdf[gdf['위험코드'] == 'D']
        e_grade = gdf[gdf['위험코드'] == 'E']
        d_count = len(d_grade)
        e_count = len(e_grade)
        total_de = d_count + e_count
        print(f"\n  [고위험 건물 상세]")
        print(f"    D등급 (경고): {d_count:,}개 ({100*d_count/len(gdf):.1f}%)")
        print(f"    E등급 (위험): {e_count:,}개 ({100*e_count/len(gdf):.1f}%)")
        print(f"    ─────────────────────────────")
        print(f"    D+E등급 합계: {total_de:,}개 ({100*total_de/len(gdf):.1f}%)")

        # =========================================================================
        # 4. 용도지역지구 분석 결과
        # =========================================================================
        if '용도점수' in gdf.columns:
            print("\n" + "-" * 70)
            print("4. 용도지역지구 분석")
            print("-" * 70)

            matched = (gdf['용도코드'] != '').sum()
            print(f"\n  용도지역 매칭 건물: {matched:,}개 / {len(gdf):,}개")

            if matched > 0:
                avg_score = gdf[gdf['용도코드'] != '']['용도점수'].mean()
                print(f"  평균 용도지역 위험점수: {avg_score:.2f}점")

                print(f"\n  [용도지역별 분포]")
                landuse_counts = gdf[gdf['용도명'] != '']['용도명'].value_counts().head(10)
                for landuse, count in landuse_counts.items():
                    score = gdf[gdf['용도명'] == landuse]['용도점수'].iloc[0]
                    pct = 100 * count / len(gdf)
                    print(f"    {landuse} ({score}점): {count:,}개 ({pct:.1f}%)")

        # =========================================================================
        # 5. 좌표 정보 현황
        # =========================================================================
        print("\n" + "-" * 70)
        print("5. 좌표 정보 현황 (EPSG:5186)")
        print("-" * 70)

        if '중심점X' in gdf.columns and '중심점Y' in gdf.columns:
            valid_coords = gdf[(gdf['중심점X'].notna()) & (gdf['중심점Y'].notna())]
            print(f"\n  좌표 추출 건물: {len(valid_coords):,}개")
            if len(valid_coords) > 0:
                print(f"  X 좌표 범위: {valid_coords['중심점X'].min():.2f} ~ {valid_coords['중심점X'].max():.2f}")
                print(f"  Y 좌표 범위: {valid_coords['중심점Y'].min():.2f} ~ {valid_coords['중심점Y'].max():.2f}")

        print("\n" + "=" * 70)


def find_similar_names(input_name: str, valid_names: list, threshold: float = 0.5) -> list:
    """유사한 이름 찾기 (오타 감지용)"""
    from difflib import SequenceMatcher

    similar = []
    for name in valid_names:
        ratio = SequenceMatcher(None, input_name, name).ratio()
        if ratio >= threshold:
            similar.append((name, ratio))

    # 유사도 순으로 정렬
    similar.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in similar[:3]]  # 상위 3개


def validate_region_input(analyzer, region_name: str) -> str:
    """광역지자체명 유효성 검사 및 오타 수정"""
    valid_regions = list(analyzer.region_mapping.keys())

    while region_name not in valid_regions:
        print(f"\n⚠️  '{region_name}'은(는) 올바르지 않은 지역명입니다.")

        # 유사한 지역명 제안
        similar = find_similar_names(region_name, valid_regions)
        if similar:
            print(f"   혹시 다음 중 하나를 의미하셨나요?")
            for i, name in enumerate(similar, 1):
                print(f"     {i}. {name}")

        print(f"\n   사용 가능한 지역: {', '.join(valid_regions)}")
        region_name = input("\n다시 입력하세요: ").strip()

        if not region_name:
            return None

    return region_name


def validate_district_input(analyzer, region_name: str, district_input: str) -> list:
    """구/군명 유효성 검사 및 오타 수정 (수정 시 복수 입력 완벽 지원)"""
    
    valid_districts = list(analyzer.region_mapping[region_name]['districts'].keys())
    validated = []
    
    # 1. 처리해야 할 지역들을 큐(Queue)에 담습니다.
    # 예: ['준주시', '전주시 덕진구']
    queue = [d.strip() for d in district_input.split(',') if d.strip()]

    # 2. 큐가 빌 때까지 하나씩 꺼내서 검사합니다.
    while queue:
        current_district = queue.pop(0) # 맨 앞의 지역을 꺼냄

        # ---------------------------------------------------------
        # Case A: 정확히 일치하는 경우 (정상)
        # ---------------------------------------------------------
        if current_district in valid_districts:
            validated.append(current_district)
            continue

        # ---------------------------------------------------------
        # Case B: 부분 매칭 (예: '청주시' 입력 시)
        # ---------------------------------------------------------
        partial_matches = [d for d in valid_districts if d.startswith(current_district)]
        
        if partial_matches:
            print(f"\n📍 '{current_district}'으로 시작하는 구/군이 {len(partial_matches)}개 있습니다:")
            for i, name in enumerate(partial_matches, 1):
                print(f"     {i}. {name}")
            
            is_handled = False
            while True:
                choice = input(f"\n'{current_district}' 전체({len(partial_matches)}개 구/군)를 분석하시겠습니까? (y/n): ").strip().lower()
                if choice == 'y':
                    validated.extend(partial_matches)
                    print(f"   ✓ '{current_district}' 전체 {len(partial_matches)}개 구/군 추가됨")
                    is_handled = True
                    break
                elif choice == 'n':
                    print(f"\n   분석할 구/군을 직접 선택하세요 (쉼표로 구분, 건너뛰려면 Enter):")
                    sub_choice = input("   선택: ").strip()
                    if sub_choice:
                        # 입력받은 지역들을 큐의 맨 앞에 추가하여 다시 검증받도록 함
                        sub_items = [d.strip() for d in sub_choice.split(',') if d.strip()]
                        for item in reversed(sub_items):
                            queue.insert(0, item)
                    is_handled = True
                    break
                else:
                    print("   ⚠️ 'y' 또는 'n'만 입력해주세요.")
            
            if is_handled:
                continue

        # ---------------------------------------------------------
        # Case C: 오타 발생 및 수정 로직 (핵심 수정 부분)
        # ---------------------------------------------------------
        # 유효하지 않은 이름인 동안 계속 반복
        while current_district not in valid_districts:
            print(f"\n⚠️  '{current_district}'은(는) '{region_name}'에 존재하지 않는 구/군명입니다.")

            # 유사한 구/군명 제안
            similar = find_similar_names(current_district, valid_districts)
            if similar:
                print(f"   혹시 다음 중 하나를 의미하셨나요?")
                for i, name in enumerate(similar, 1):
                    print(f"     {i}. {name}")

            print(f"\n   '{region_name}'의 구/군 목록:")
            # 목록이 너무 길면 일부만 보여주기
            if len(valid_districts) > 6:
                print(f"     {', '.join(valid_districts[:6])} ... 외 {len(valid_districts)-6}개")
            else:
                for i, name in enumerate(valid_districts, 1):
                    print(f"     {i}. {name}")

            choice = input(f"\n'{current_district}' 대신 입력할 구/군명 (쉼표로 복수 입력 가능, 건너뛰려면 Enter): ").strip()

            if not choice:
                print(f"   '{current_district}' 건너뜀")
                current_district = None
                break
            
            # [핵심] 쉼표(,)가 포함된 경우 분리해서 큐에 넣기
            if ',' in choice:
                new_items = [c.strip() for c in choice.split(',') if c.strip()]
                print(f"   ✓ {len(new_items)}개 지역으로 분리하여 다시 확인합니다.")
                
                # 분리된 아이템들을 큐의 맨 앞에 추가 (Reversed로 넣어야 순서 유지됨)
                for item in reversed(new_items):
                    queue.insert(0, item)
                
                current_district = None # 현재 오타난 항목은 폐기
                break # 내부 while 문 탈출 -> 바깥 queue loop가 새로 추가된 항목들을 처리함
            else:
                # 쉼표가 없으면 단일 수정으로 간주하고 다시 검사 루프
                current_district = choice

        # 최종적으로 유효한 이름이 확정되면 결과 리스트에 추가
        if current_district and current_district in valid_districts:
            validated.append(current_district)

    # 중복 제거 및 반환
    return list(dict.fromkeys(validated))


def merge_results_mode():
    """기존 분석 결과 통합 모드 - 지역별 분석결과 폴더의 SHP 파일들을 사업소/광역단위로 통합"""
    print("=" * 70)
    print("           기존 분석 결과 통합")
    print("=" * 70)
    print("지역별 분석결과 폴더의 데이터를 사업소 또는 광역단위로 통합합니다.")

    # 기본 경로 설정
    base_path = Path(r"C:\Users\user\Downloads\kescoaitest")

    if not base_path.exists():
        print(f"기본 경로를 찾을 수 없습니다: {base_path}")
        base_path = Path(input("데이터 폴더 경로를 입력하세요: ").strip())

    results_path = base_path / "지역별 분석결과"
    if not results_path.exists():
        print(f"\n⚠️ 지역별 분석결과 폴더가 없습니다: {results_path}")
        print("먼저 분석을 실행해주세요.")
        return

    # analyzer 생성 (사업소 매핑 로드용)
    analyzer = BuildingMultiRiskAnalyzer(str(base_path))

    # 사용 가능한 지역 표시
    print("\n[지역별 분석결과 폴더 현황]")
    available_regions = {}
    for region_dir in sorted(results_path.iterdir()):
        if region_dir.is_dir():
            districts = []
            for district_dir in sorted(region_dir.iterdir()):
                if district_dir.is_dir():
                    shp_files = list(district_dir.glob("*.shp"))
                    if shp_files:
                        districts.append(district_dir.name)
            # 지역 폴더에 직접 있는 SHP 파일도 확인
            direct_shp = list(region_dir.glob("*.shp"))
            if districts or direct_shp:
                available_regions[region_dir.name] = districts
                district_str = f"{len(districts)}개 구/군" if districts else ""
                direct_str = f", 직접 {len(direct_shp)}개 파일" if direct_shp else ""
                print(f"  - {region_dir.name}: {district_str}{direct_str}")

    if not available_regions:
        print("\n⚠️ 통합할 분석 결과가 없습니다.")
        return

    # 사업소 목록 표시
    if analyzer.branch_mapping:
        print("\n[등록된 사업소]")
        headquarters = set()
        for branch_name in analyzer.branch_mapping.keys():
            if '본부' in branch_name:
                hq_idx = branch_name.find('본부') + 2
                hq_name = branch_name[:hq_idx]
                headquarters.add(hq_name)

        if headquarters:
            print("  본부 전체: " + ", ".join(sorted(headquarters)))
        print("  개별 사업소: " + ", ".join(sorted(analyzer.branch_mapping.keys())[:10]) + " ...")

    # 통합 대상 입력
    print("\n" + "-" * 70)
    print("통합할 대상을 입력하세요:")
    print("  - 사업소: 경기본부, 경기본부직할, 광주전남본부직할 등")
    print("  - 광역지자체: 경기, 전북, 광주 등")

    target_input = input("\n통합 대상: ").strip()
    if not target_input:
        print("입력이 없습니다.")
        return

    # 통합 대상 지역 결정
    target_regions = {}  # {광역지자체: [구/군 리스트 또는 None]}

    # 1. 사업소명 확인
    branch_info = analyzer.get_branch_info(target_input)
    if branch_info:
        print(f"\n✓ 사업소 인식: {target_input}")
        for region_name, branch_districts in branch_info.items():
            if region_name in available_regions:
                if branch_districts:
                    # 사업소가 담당하는 구/군 중 분석 결과가 있는 것만
                    matching = [d for d in branch_districts if d in available_regions.get(region_name, [])]
                    if matching:
                        target_regions[region_name] = matching
                        print(f"  - {region_name}: {', '.join(matching)}")
                else:
                    target_regions[region_name] = None
                    print(f"  - {region_name}: 전체")
    else:
        # 2. 광역지자체명 확인
        region_names = {'서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
                       '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'}
        if target_input in region_names:
            if target_input in available_regions:
                target_regions[target_input] = None  # 전체
                print(f"\n✓ 광역지자체 인식: {target_input} 전체")
            else:
                print(f"\n⚠️ '{target_input}'의 분석 결과가 없습니다.")
                return
        else:
            print(f"\n⚠️ '{target_input}'을(를) 인식할 수 없습니다.")
            print("사업소명 또는 광역지자체명을 입력해주세요.")
            return

    if not target_regions:
        print("\n⚠️ 통합할 분석 결과가 없습니다.")
        return

    # SHP 파일 수집
    print("\n" + "-" * 70)
    print("SHP 파일 수집 중...")

    shp_files_to_merge = []
    for region_name, districts in target_regions.items():
        region_path = results_path / region_name

        if districts is None:
            # 전체: 하위 폴더의 모든 SHP + 직접 있는 SHP
            for item in region_path.iterdir():
                if item.is_dir():
                    shp_files = list(item.glob("*.shp"))
                    shp_files_to_merge.extend(shp_files)
                elif item.suffix.lower() == '.shp':
                    shp_files_to_merge.append(item)
        else:
            # 특정 구/군만
            for district in districts:
                district_path = region_path / district
                if district_path.exists():
                    shp_files = list(district_path.glob("*.shp"))
                    shp_files_to_merge.extend(shp_files)

    if not shp_files_to_merge:
        print("\n⚠️ 통합할 SHP 파일이 없습니다.")
        return

    # 기상적용 파일 제외 + 날짜별 분류
    import re
    date_pattern = re.compile(r'(\d{8})(?:\.shp$|_기상적용)')

    date_files = {}  # {날짜: [파일리스트]}
    no_date_files = []

    for shp_file in shp_files_to_merge:
        # 기상적용 파일 제외
        if '_기상적용_' in shp_file.name:
            continue
        match = date_pattern.search(shp_file.name)
        if match:
            file_date = match.group(1)
            if file_date not in date_files:
                date_files[file_date] = []
            date_files[file_date].append(shp_file)
        else:
            no_date_files.append(shp_file)

    if not date_files and not no_date_files:
        print("\n⚠️ 통합할 SHP 파일이 없습니다.")
        return

    # 날짜별 파일 현황 출력
    print(f"\n[날짜별 파일 현황]")
    sorted_dates = sorted(date_files.keys(), reverse=True)
    for i, d in enumerate(sorted_dates, 1):
        formatted = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        print(f"  {i}. {formatted}: {len(date_files[d])}개 파일")
    if no_date_files:
        print(f"  날짜 없음: {len(no_date_files)}개 파일")

    # 날짜 선택
    if len(sorted_dates) == 1:
        selected_date = sorted_dates[0]
        formatted = f"{selected_date[:4]}-{selected_date[4:6]}-{selected_date[6:8]}"
        print(f"\n→ {formatted} 파일만 존재하여 자동 선택")
    else:
        while True:
            date_choice = input(f"\n통합할 날짜 번호를 선택하세요 (1~{len(sorted_dates)}): ").strip()
            if date_choice.isdigit() and 1 <= int(date_choice) <= len(sorted_dates):
                selected_date = sorted_dates[int(date_choice) - 1]
                break
            print(f"  ⚠️ 1~{len(sorted_dates)} 사이의 번호를 입력해주세요.")

    shp_files_to_merge = date_files[selected_date]
    formatted = f"{selected_date[:4]}-{selected_date[4:6]}-{selected_date[6:8]}"

    print(f"\n선택된 날짜: {formatted}")
    print(f"통합 대상 파일: {len(shp_files_to_merge)}개")
    for shp_file in shp_files_to_merge[:10]:
        print(f"  - {shp_file.relative_to(results_path)}")
    if len(shp_files_to_merge) > 10:
        print(f"  ... 외 {len(shp_files_to_merge) - 10}개")

    # 통합 확인
    confirm = input(f"\n{len(shp_files_to_merge)}개 파일을 통합하시겠습니까? (y/n): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        return

    # SHP 파일 병합
    print("\n" + "-" * 70)
    print("SHP 파일 병합 중...")

    all_gdfs = []
    total_buildings = 0
    failed_files = []

    for i, shp_file in enumerate(shp_files_to_merge, 1):
        try:
            print(f"  [{i}/{len(shp_files_to_merge)}] {shp_file.name}...", end=" ")
            gdf = gpd.read_file(shp_file, encoding='cp949')
            if len(gdf) > 0:
                all_gdfs.append(gdf)
                total_buildings += len(gdf)
                print(f"{len(gdf):,}개 건물")
            else:
                print("(빈 파일)")
        except Exception as e:
            print(f"오류: {e}")
            failed_files.append(shp_file)

    if not all_gdfs:
        print("\n⚠️ 병합할 데이터가 없습니다.")
        return

    print(f"\n병합 중... (총 {total_buildings:,}개 건물)")

    # GeoDataFrame 병합
    combined_gdf = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True))
    if all_gdfs[0].crs:
        combined_gdf = combined_gdf.set_crs(all_gdfs[0].crs)

    print(f"✓ 병합 완료: {len(combined_gdf):,}개 건물")

    if failed_files:
        print(f"\n⚠️ 실패한 파일: {len(failed_files)}개")
        for f in failed_files[:5]:
            print(f"  - {f.name}")

    # 저장 경로 결정
    output_dir = analyzer._get_output_directory(target_input)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 파일명 생성
    filename = f"통합위험분석_{target_input}_{datetime.now().strftime('%Y%m%d')}.shp"
    output_path = output_dir / filename

    # 저장
    print(f"\n저장 중: {output_path}")
    try:
        # cp949 인코딩으로 저장
        combined_gdf.to_file(output_path, encoding='cp949')
        print(f"\n✓ 저장 완료: {output_path}")

        # CSV 요약도 저장
        csv_path = output_path.with_suffix('.csv')
        summary_cols = [col for col in combined_gdf.columns if col != 'geometry']
        combined_gdf[summary_cols].to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✓ CSV 요약 저장: {csv_path}")

    except Exception as e:
        print(f"\n⚠️ 저장 실패: {e}")
        # UTF-8로 재시도
        try:
            combined_gdf.to_file(output_path, encoding='utf-8')
            print(f"✓ UTF-8로 저장 완료: {output_path}")
        except Exception as e2:
            print(f"⚠️ UTF-8 저장도 실패: {e2}")
            return

    # =========================================================================
    # 상세 통계 출력
    # =========================================================================
    print("\n" + "=" * 70)
    print("                    ★ 통합 완료 ★")
    print("=" * 70)

    print(f"\n[통합 개요]")
    print(f"  • 통합 대상: {target_input}")
    print(f"  • 통합 파일 수: {len(shp_files_to_merge)}개")
    print(f"  • 총 건물 수: {len(combined_gdf):,}개")
    print(f"  • 저장 위치: {output_path}")

    # =========================================================================
    # 1. 개별 위험요소 분석
    # =========================================================================
    print("\n" + "-" * 70)
    print("1. 개별 위험요소 분석")
    print("-" * 70)

    # 1-1. 건물 노후위험도
    if '노후점수' in combined_gdf.columns:
        print("\n[1-1. 건물 노후위험도]")
        print("  (건물연령 기반 노후점수)")

        if '건물연령' in combined_gdf.columns:
            avg_age = combined_gdf['건물연령'].mean()
            max_age = combined_gdf['건물연령'].max()
            min_age = combined_gdf['건물연령'].min()
            print(f"    평균 건물연령: {avg_age:.1f}년")
            print(f"    최고 건물연령: {max_age}년")
            print(f"    최저 건물연령: {min_age}년")

        avg_score = combined_gdf['노후점수'].mean()
        print(f"\n    평균 노후점수: {avg_score:.2f}점")

        # 노후점수별 분포
        print(f"\n    노후점수별 분포:")
        for score in sorted(combined_gdf['노후점수'].unique()):
            count = (combined_gdf['노후점수'] == score).sum()
            pct = 100 * count / len(combined_gdf)
            print(f"      {score}점: {count:,}개 ({pct:.1f}%)")

    # 1-2. 홍수/침수위험도
    if '홍수점수' in combined_gdf.columns:
        print("\n[1-2. 홍수/침수위험도]")
        print("  (홍수/침수위험구역 내: 10점, 구역 외: 1점)")

        flood_buildings = (combined_gdf['홍수점수'] >= 10).sum()
        no_flood = len(combined_gdf) - flood_buildings
        print(f"    홍수/침수위험구역 내: {flood_buildings:,}개 ({100*flood_buildings/len(combined_gdf):.1f}%)")
        print(f"    홍수/침수위험구역 외: {no_flood:,}개 ({100*no_flood/len(combined_gdf):.1f}%)")

    # 1-3. 산사태근접위험도
    if '산사태점수' in combined_gdf.columns:
        print("\n[1-3. 산사태근접위험도]")

        if '산사태등급' in combined_gdf.columns:
            landslide_counts = combined_gdf['산사태등급'].value_counts()
            for level, count in landslide_counts.items():
                pct = 100 * count / len(combined_gdf)
                print(f"    {level}: {count:,}개 ({pct:.1f}%)")

        if '산사태거리' in combined_gdf.columns:
            valid_distances = combined_gdf[combined_gdf['산사태거리'] < 99999]['산사태거리']
            if len(valid_distances) > 0:
                print(f"\n    평균 산사태위험지역 거리: {valid_distances.mean():.1f}m")
                print(f"    최소 거리: {valid_distances.min():.1f}m")

    # 1-4. 용도지역지구 위험도
    if '용도점수' in combined_gdf.columns:
        print("\n[1-4. 용도지역지구 위험도]")

        if '용도코드' in combined_gdf.columns:
            matched = (combined_gdf['용도코드'] != '').sum()
            unmatched = len(combined_gdf) - matched
            print(f"    용도지역 매칭: {matched:,}개 ({100*matched/len(combined_gdf):.1f}%)")
            print(f"    미매칭: {unmatched:,}개 ({100*unmatched/len(combined_gdf):.1f}%)")

            if matched > 0 and '용도명' in combined_gdf.columns:
                matched_gdf = combined_gdf[combined_gdf['용도코드'] != '']
                avg_score = matched_gdf['용도점수'].mean()
                print(f"\n    평균 용도지역 점수: {avg_score:.2f}점")

                # 용도지역별 분포 (상위 5개)
                print(f"\n    용도지역별 분포 (상위 5개):")
                landuse_counts = matched_gdf['용도명'].value_counts().head(5)
                for landuse, count in landuse_counts.items():
                    score = matched_gdf[matched_gdf['용도명'] == landuse]['용도점수'].iloc[0]
                    pct = 100 * count / len(combined_gdf)
                    print(f"      {landuse} ({score}점): {count:,}개 ({pct:.1f}%)")

    # 1-5. 전기화재이력 위험도
    if '화재점수' in combined_gdf.columns:
        print("\n[1-5. 전기화재이력 위험도]")
        fire_5m = (combined_gdf['전기화재'] == 3).sum() if '전기화재' in combined_gdf.columns else 0
        fire_10m = (combined_gdf['전기화재'] == 2).sum() if '전기화재' in combined_gdf.columns else 0
        fire_20m = (combined_gdf['전기화재'] == 1).sum() if '전기화재' in combined_gdf.columns else 0
        fire_none = (combined_gdf['화재점수'] == 0).sum()

        print(f"    5m 이내 (10점): {fire_5m:,}개 ({100*fire_5m/len(combined_gdf):.1f}%)")
        print(f"    10m 이내 (8점): {fire_10m:,}개 ({100*fire_10m/len(combined_gdf):.1f}%)")
        print(f"    20m 이내 (6점): {fire_20m:,}개 ({100*fire_20m/len(combined_gdf):.1f}%)")
        print(f"    범위 밖 (0점): {fire_none:,}개 ({100*fire_none/len(combined_gdf):.1f}%)")

        avg_fire = combined_gdf['화재점수'].mean()
        print(f"\n    평균 화재점수: {avg_fire:.2f}점")

    # =========================================================================
    # 2. 요소별 위험도 현황
    # =========================================================================
    print("\n" + "-" * 70)
    print("2. 요소별 위험도 현황")
    print("-" * 70)

    print("\n[위험요소별 평균 점수]")
    if '노후점수' in combined_gdf.columns:
        print(f"    노후위험:     {combined_gdf['노후점수'].mean():.2f}점")
    if '홍수점수' in combined_gdf.columns:
        print(f"    홍수/침수위험: {combined_gdf['홍수점수'].mean():.2f}점")
    if '산사태점수' in combined_gdf.columns:
        print(f"    산사태위험:   {combined_gdf['산사태점수'].mean():.2f}점")
    if '용도점수' in combined_gdf.columns:
        print(f"    용도지역위험: {combined_gdf['용도점수'].mean():.2f}점")
    if '화재점수' in combined_gdf.columns:
        avg_fire = combined_gdf['화재점수'].mean()
        fire_applied = (combined_gdf['화재점수'] > 0).sum()
        print(f"    전기화재점수: 평균 {avg_fire:.2f}점 (적용 건물: {fire_applied:,}개)")

    print("\n[위험요소별 고위험 건물 수]")
    if '노후점수' in combined_gdf.columns:
        high_age = (combined_gdf['노후점수'] >= 8).sum()
        print(f"    노후 8점 이상:     {high_age:,}개 ({100*high_age/len(combined_gdf):.1f}%)")
    if '홍수점수' in combined_gdf.columns:
        high_flood = (combined_gdf['홍수점수'] >= 10).sum()
        print(f"    홍수/침수 10점 (구역내): {high_flood:,}개 ({100*high_flood/len(combined_gdf):.1f}%)")
    if '산사태점수' in combined_gdf.columns:
        high_landslide = (combined_gdf['산사태점수'] >= 6).sum()
        print(f"    산사태 6점 이상:   {high_landslide:,}개 ({100*high_landslide/len(combined_gdf):.1f}%)")
    if '용도점수' in combined_gdf.columns:
        high_landuse = (combined_gdf['용도점수'] >= 3).sum()
        print(f"    용도지역 3점 이상: {high_landuse:,}개 ({100*high_landuse/len(combined_gdf):.1f}%)")

    # =========================================================================
    # 3. 최종 종합 위험도 분석
    # =========================================================================
    print("\n" + "-" * 70)
    print("3. 최종 종합 위험도 분석")
    print("   노후+홍수/침수+산사태+용도지역+전기화재 단순 합산")
    print("-" * 70)

    if '위험코드' in combined_gdf.columns:
        print("\n[종합위험등급별 건물 수]")
        grade_info = {'A': '안전', 'B': '관심', 'C': '주의', 'D': '경고', 'E': '위험'}
        grade_counts = combined_gdf['위험코드'].value_counts()

        for grade in ['A', 'B', 'C', 'D', 'E']:
            if grade in grade_counts.index:
                count = grade_counts[grade]
                pct = 100 * count / len(combined_gdf)
                print(f"    {grade}등급 ({grade_info[grade]}): {count:,}개 ({pct:.1f}%)")

    if '종합점수' in combined_gdf.columns:
        max_score = combined_gdf['종합점수'].max()
        max_risk = combined_gdf[combined_gdf['종합점수'] == max_score]
        print(f"\n    최고 위험 건물 (종합점수 {max_score:.1f}점): {len(max_risk):,}개")

        avg_score = combined_gdf['종합점수'].mean()
        print(f"    평균 종합점수: {avg_score:.2f}점")

    if '종합점수' in combined_gdf.columns:
        avg_final = combined_gdf['종합점수'].mean()
        print(f"\n    평균 종합점수: {avg_final:.2f}점")

    # 고위험 건물 상세
    if '위험코드' in combined_gdf.columns:
        d_count = (combined_gdf['위험코드'] == 'D').sum()
        e_count = (combined_gdf['위험코드'] == 'E').sum()
        total_de = d_count + e_count

        print(f"\n    [고위험 건물 상세]")
        print(f"      D등급 (경고): {d_count:,}개 ({100*d_count/len(combined_gdf):.1f}%)")
        print(f"      E등급 (위험): {e_count:,}개 ({100*e_count/len(combined_gdf):.1f}%)")
        print(f"      ─────────────────────────────")
        print(f"      D+E등급 합계: {total_de:,}개 ({100*total_de/len(combined_gdf):.1f}%)")

    # =========================================================================
    # 4. 지역별 분포 (통합 대상 지역들)
    # =========================================================================
    if '지역' in combined_gdf.columns:
        print("\n" + "-" * 70)
        print("4. 지역별 분포")
        print("-" * 70)

        region_stats = combined_gdf.groupby('지역').agg({
            '위험코드': lambda x: (x == 'D').sum() + (x == 'E').sum() if '위험코드' in combined_gdf.columns else 0
        }).rename(columns={'위험코드': 'DE등급'})

        region_counts = combined_gdf['지역'].value_counts()

        print(f"\n{'지역':<15} {'건물수':>10} {'D+E등급':>10} {'비율':>8}")
        print("-" * 45)
        for region in region_counts.index:
            count = region_counts[region]
            de_count = region_stats.loc[region, 'DE등급'] if region in region_stats.index else 0
            pct = 100 * de_count / count if count > 0 else 0
            print(f"{region:<15} {count:>10,} {de_count:>10,} {pct:>7.1f}%")

    # =========================================================================
    # 5. 구/군별 분포 (상세)
    # =========================================================================
    if '구군' in combined_gdf.columns:
        print("\n" + "-" * 70)
        print("5. 구/군별 분포 (상위 15개)")
        print("-" * 70)

        district_counts = combined_gdf['구군'].value_counts().head(15)

        print(f"\n{'구/군':<20} {'건물수':>10} {'D+E등급':>10} {'비율':>8}")
        print("-" * 50)
        for district in district_counts.index:
            count = district_counts[district]
            district_data = combined_gdf[combined_gdf['구군'] == district]
            if '위험코드' in district_data.columns:
                de_count = ((district_data['위험코드'] == 'D') | (district_data['위험코드'] == 'E')).sum()
            else:
                de_count = 0
            pct = 100 * de_count / count if count > 0 else 0
            print(f"{district:<20} {count:>10,} {de_count:>10,} {pct:>7.1f}%")

    print("\n" + "=" * 70)
    print("                    분석 완료")
    print("=" * 70)

    # =========================================================================
    # 추가 작업 여부 확인 (자동 종료 방지)
    # =========================================================================
    print("\n")
    while True:
        continue_input = input("추가 작업을 진행하시겠습니까? (y/n): ").strip().lower()
        if continue_input == 'y':
            print("\n" + "=" * 70)
            print("메인 메뉴로 돌아갑니다...")
            interactive_mode()
            return
        elif continue_input == 'n':
            input("\n프로그램을 종료합니다. 아무 키나 누르세요...")
            return
        else:
            print("  ⚠️ 'y' 또는 'n'만 입력해주세요.")


def interactive_mode():
    """대화형 모드로 실행 (복수 지역, 오타 감지, 광역 일괄 분석, 사업소 지원)"""
    import pandas as pd
    import geopandas as gpd
    print("=" * 70)
    print("    건물 노후위험도 × 홍수위험 × 산사태근접위험 통합 분석")
    print("=" * 70)
    print(f"분석 기준 연도: {datetime.now().year}년")
    print("좌표계: EPSG:5186 (Korea 2000 / Central Belt)")

    # =========================================================================
    # 0. 작업 모드 선택
    # =========================================================================
    print("\n" + "=" * 70)
    print("[작업 선택]")
    print("-" * 70)
    print("  1. 새로운 분석 실행")
    print("  2. 기존 결과 통합 (지역별 분석결과 → 사업소/광역단위 통합)")

    while True:
        mode_choice = input("\n선택 (1 또는 2): ").strip()
        if mode_choice == '1':
            break  # 새로운 분석 실행 - 아래로 계속
        elif mode_choice == '2':
            merge_results_mode()  # 결과 통합 모드
            return  # 통합 완료 후 종료
        else:
            print("  ⚠️ '1' 또는 '2'만 입력해주세요.")

    # =========================================================================
    # 새로운 분석 실행
    # =========================================================================

    # 기본 경로 설정
    base_path = r"C:\Users\user\Downloads\kescoaitest"

    if not os.path.exists(base_path):
        print(f"기본 경로를 찾을 수 없습니다: {base_path}")
        base_path = input("데이터 폴더 경로를 입력하세요: ").strip()

    analyzer = BuildingMultiRiskAnalyzer(base_path)

    # 지역 목록 표시
    analyzer.list_available_regions()

    # 사업소 목록 표시
    if analyzer.branch_mapping:
        print("\n" + "=" * 50)
        print("등록된 사업소 목록")
        print("=" * 50)

        # 본부 전체 조회 옵션 추출
        headquarters = set()
        for branch_name in analyzer.branch_mapping.keys():
            if '본부' in branch_name:
                # '서울본부직할' → '서울본부', '경기북부본부직할' → '경기북부본부'
                hq_idx = branch_name.find('본부') + 2
                hq_name = branch_name[:hq_idx]
                headquarters.add(hq_name)

        # 본부 전체 조회 옵션 표시
        if headquarters:
            print("\n[본부 전체 조회] (본부명만 입력하면 직할+모든지사 전체 분석)")
            sorted_hqs = sorted(headquarters)
            # 한 줄에 5개씩 표시
            for i in range(0, len(sorted_hqs), 5):
                chunk = sorted_hqs[i:i+5]
                print(f"  {', '.join(chunk)}")

        # 개별 사업소 목록 표시
        print("\n[개별 사업소]")
        for branch_name, districts in analyzer.branch_mapping.items():
            if isinstance(districts, list):
                districts_str = ', '.join(districts[:5])
                if len(districts) > 5:
                    districts_str += f" 외 {len(districts)-5}개"
                print(f"  - {branch_name}: {districts_str}")
            else:
                print(f"  - {branch_name}: {districts}")

    # =========================================================================
    # 1. 광역지자체 또는 사업소 선택
    # =========================================================================
    print("\n" + "=" * 70)
    print("[1단계] 광역지자체 또는 사업소 선택")
    print("-" * 70)
    print("  - 광역지자체: 쉼표(,)로 복수 선택 가능 (예: 서울, 부산)")
    print("  - 본부 전체: 본부명만 입력 (예: 서울본부 → 직할+모든지사 전체)")
    print("  - 개별 사업소: 직접 입력 (예: 서울본부직할, 서울동부지사)")
    print("  - 단일 선택 후 구/군 지정 가능")

    region_input = input("\n분석할 광역지자체 또는 사업소를 입력하세요: ").strip()

    if not region_input:
        print("입력이 없습니다.")
        return

    # 사업소명 확인
    branch_info = analyzer.get_branch_info(region_input)

    if branch_info:
        # 사업소명으로 입력된 경우
        # branch_info = {광역지자체: [구/군 리스트], ...}
        print(f"\n✓ 사업소 인식: {region_input}")

        districts_by_region = {}
        validated_regions = []

        for region_name, branch_districts in branch_info.items():
            validated_regions.append(region_name)
            print(f"  - {region_name}: {', '.join(branch_districts) if branch_districts else '전체'}")

            if branch_districts:
                districts_by_region[region_name] = branch_districts
            else:
                districts_by_region[region_name] = None

    else:
        # 광역지자체명으로 입력된 경우 (기존 로직)
        region_names = [r.strip() for r in region_input.split(',') if r.strip()]
        validated_regions = []

        for region in region_names:
            validated = validate_region_input(analyzer, region)
            if validated:
                validated_regions.append(validated)

        if not validated_regions:
            print("유효한 지역이 없습니다.")
            return

        print(f"\n✓ 선택된 광역지자체: {', '.join(validated_regions)}")
        districts_by_region = None  # 다음 단계에서 설정

    # =========================================================================
    # 2. 구/군 선택 (복수 입력 지원) - 사업소 입력 시 건너뜀
    # =========================================================================
    if districts_by_region is None:
        # 사업소명이 아닌 광역지자체명으로 입력한 경우에만 구/군 선택
        print("\n" + "=" * 70)
        print("[2단계] 구/군 선택")
        print("-" * 70)
        print("  - 전체 분석: Enter 입력")
        print("  - 복수 선택: 쉼표(,)로 구분 (예: 전주시 완산구, 전주시 덕진구)")
        print("  - 시 전체 분석: 시명만 입력 (예: 청주시 → 청주시 전체 구 분석)")

        districts_by_region = {}

        for region in validated_regions:
            print(f"\n[{region}] 구/군 목록:")
            district_list = list(analyzer.region_mapping[region]['districts'].keys())
            for i, d in enumerate(district_list, 1):
                print(f"  {i}. {d}")

            if len(validated_regions) == 1:
                district_input = input(f"\n'{region}'에서 분석할 구/군 (전체는 Enter): ").strip()
            else:
                district_input = input(f"\n'{region}'에서 분석할 구/군 (전체는 Enter, 건너뛰기는 'skip'): ").strip()

            if district_input.lower() == 'skip':
                print(f"  '{region}' 건너뜀")
                continue
            elif not district_input:
                # 전체 분석
                districts_by_region[region] = None
                print(f"  ✓ '{region}' 전체 분석")
            else:
                # 개별 구/군 선택
                validated_districts = validate_district_input(analyzer, region, district_input)
                if validated_districts:
                    districts_by_region[region] = validated_districts
                    print(f"  ✓ 선택된 구/군: {', '.join(validated_districts)}")
                else:
                    print(f"  '{region}'에서 유효한 구/군이 없어 전체 분석으로 진행합니다.")
                    districts_by_region[region] = None

        if not districts_by_region:
            print("분석할 지역이 없습니다.")
            return
    else:
        # 사업소명으로 입력한 경우 - 구/군 선택 건너뜀
        print("\n  (사업소 지정으로 구/군 선택 단계 건너뜀)")

    # =========================================================================
    # 3. 연령 필터 설정
    # =========================================================================
    print("\n" + "=" * 70)
    print("[3단계] 연령 필터 설정")
    print("-" * 70)

    min_age_input = input("최소 건물연령 (예: 30, 미설정은 Enter): ").strip()
    min_age = int(min_age_input) if min_age_input and min_age_input.isdigit() else None

    max_age_input = input("최대 건물연령 (예: 50, 미설정은 Enter): ").strip()
    max_age = int(max_age_input) if max_age_input and max_age_input.isdigit() else None

    if min_age:
        print(f"  ✓ 최소 연령: {min_age}년 이상")
    if max_age:
        print(f"  ✓ 최대 연령: {max_age}년 이하")

    # =========================================================================
    # 4. 분석 옵션
    # =========================================================================
    print("\n" + "=" * 70)
    print("[4단계] 분석 옵션")
    print("-" * 70)

    # 홍수위험 분석 포함 여부
    while True:
        flood_input = input("홍수/침수위험 분석 포함? (y/n, 기본 y): ").strip().lower()
        if flood_input in ['y', 'n', '']:
            include_flood = flood_input != 'n'
            break
        else:
            print("  ⚠️ 'y' 또는 'n'만 입력해주세요.")

    # 산사태근접위험 분석 포함 여부
    while True:
        landslide_input = input("산사태근접위험 분석 포함? (y/n, 기본 y): ").strip().lower()
        if landslide_input in ['y', 'n', '']:
            include_landslide = landslide_input != 'n'
            break
        else:
            print("  ⚠️ 'y' 또는 'n'만 입력해주세요.")

    print(f"  ✓ 홍수/침수위험 분석: {'포함' if include_flood else '제외'}")
    print(f"  ✓ 산사태근접위험 분석: {'포함' if include_landslide else '제외'}")

    # =========================================================================
    # 5. 분석 실행
    # =========================================================================
    print("\n" + "=" * 70)
    print("[5단계] 분석 실행")
    print("=" * 70)

    all_results = []
    result_info = []  # (result, region, district) 튜플 저장

    for region, districts in districts_by_region.items():
        if districts is None:
            # 전체 분석
            print(f"\n▶ {region} 전체 분석 시작...")
            result = analyzer.analyze_region(
                region, None, min_age, max_age,
                include_flood, include_landslide
            )
            if result is not None and len(result) > 0:
                all_results.append(result)
                result_info.append((result, region, None))
        else:
            # 개별 구/군 분석
            for district in districts:
                print(f"\n▶ {region} {district} 분석 시작...")
                result = analyzer.analyze_region(
                    region, district, min_age, max_age,
                    include_flood, include_landslide
                )
                if result is not None and len(result) > 0:
                    all_results.append(result)
                    result_info.append((result, region, district))

    # =========================================================================
    # 6. 결과 저장
    # =========================================================================
    if not all_results:
        print("\n분석 결과가 없습니다.")
        # 추가 작업 여부 확인
        print("\n" + "=" * 70)
        while True:
            continue_input = input("추가 분석을 진행하시겠습니까? (y/n): ").strip().lower()
            if continue_input == 'y':
                print("\n" + "=" * 70)
                print("새로운 분석을 시작합니다...")
                interactive_mode()
                return
            elif continue_input == 'n':
                print("\n프로그램을 종료합니다. 감사합니다!")
                return
            else:
                print("  ⚠️ 'y' 또는 'n'만 입력해주세요.")

    print("\n" + "=" * 70)
    print("[6단계] 결과 저장")
    print("=" * 70)

    total_buildings = sum(len(r) for r in all_results)
    print(f"\n분석 완료: {len(all_results)}개 지역, {total_buildings:,}개 건물")

    # 2개 이상의 결과가 있으면 저장 방식 선택
    if len(all_results) >= 2:
        print("\n저장 방식을 선택해주세요:")
        print("  1. 하나의 파일로 합쳐서 저장")
        print("  2. 각 지역별로 따로 저장")

        while True:
            save_choice = input("\n선택 (1 또는 2): ").strip()
            if save_choice == '1':
                # 하나로 합쳐서 저장
                print("\n모든 결과를 하나의 파일로 병합 중...")
                combined_result = pd.concat(all_results, ignore_index=True)
                combined_gdf = gpd.GeoDataFrame(combined_result, crs=all_results[0].crs)

                # 파일명 생성 (사업소명 또는 지역명)
                # 사업소명으로 입력한 경우 사업소명 사용
                if region_input and ('지사' in region_input or '직할' in region_input or '본부' in region_input):
                    region_str = region_input
                else:
                    region_names = list(set(r for _, r, _ in result_info))
                    if len(region_names) <= 3:
                        region_str = '_'.join(region_names)
                    else:
                        region_str = f"{region_names[0]}외{len(region_names)-1}개지역"

                filename = f"통합위험분석_{region_str}"
                if min_age:
                    filename += f"_{min_age}년이상"
                filename += f"_{datetime.now().strftime('%Y%m%d')}.shp"

                output_path = analyzer.save_results(combined_gdf, filename=filename, search_query=region_input)
                print(f"\n✓ 통합 저장 완료: {output_path}")

                # 요약 출력
                analyzer.print_summary(combined_gdf)
                break

            elif save_choice == '2':
                # 각각 저장 (실제 분석 지역 기준으로 폴더 결정)
                print("\n각 지역별로 저장 중...")
                for result, region, district in result_info:
                    output_path = analyzer.save_results(
                        result, region_name=region, district_name=district, min_age=min_age,
                        search_query=region  # 실제 분석 지역(region) 기준으로 저장 경로 결정
                    )
                    district_str = district if district else "전체"
                    print(f"  ✓ {region} {district_str}: {output_path}")
                break

            else:
                print("  ⚠️ '1' 또는 '2'만 입력해주세요.")
    else:
        # 단일 결과는 바로 저장 (실제 분석 지역 기준으로 폴더 결정)
        result, region, district = result_info[0]
        output_path = analyzer.save_results(
            result, region_name=region, district_name=district, min_age=min_age,
            search_query=region  # 실제 분석 지역(region) 기준으로 저장 경로 결정
        )
        print(f"\n✓ 저장 완료: {output_path}")

        # 요약 출력
        analyzer.print_summary(result)

    # =========================================================================
    # 7. 최종 요약
    # =========================================================================
    print("\n" + "=" * 70)
    print("                    ★ 분석 완료 ★")
    print("=" * 70)
    print(f"\n[분석 개요]")
    print(f"  • 총 분석 지역: {len(all_results)}개")
    print(f"  • 총 분석 건물: {total_buildings:,}개")
    print(f"  • 결과 저장 위치: {output_path.parent}")

    # 전체 결과 통합 통계
    if len(all_results) > 0:
        import pandas as pd
        combined_for_stats = pd.concat(all_results, ignore_index=True)

        print(f"\n[전체 위험등급 분포]")
        if '위험코드' in combined_for_stats.columns:
            grade_counts = combined_for_stats['위험코드'].value_counts().sort_index()
            for grade in ['A', 'B', 'C', 'D', 'E']:
                if grade in grade_counts.index:
                    count = grade_counts[grade]
                    pct = 100 * count / len(combined_for_stats)
                    grade_name = {'A': '안전', 'B': '관심', 'C': '주의', 'D': '경고', 'E': '위험'}.get(grade, '')
                    print(f"  • {grade}등급 ({grade_name}): {count:,}개 ({pct:.1f}%)")

        print(f"\n[고위험 건물 현황]")
        d_count = (combined_for_stats['위험코드'] == 'D').sum() if '위험코드' in combined_for_stats.columns else 0
        e_count = (combined_for_stats['위험코드'] == 'E').sum() if '위험코드' in combined_for_stats.columns else 0
        print(f"  • D등급 (경고): {d_count:,}개")
        print(f"  • E등급 (위험): {e_count:,}개")
        print(f"  • D+E등급 합계: {d_count + e_count:,}개 ({100*(d_count+e_count)/len(combined_for_stats):.1f}%)")

        if '홍수점수' in combined_for_stats.columns:
            flood_count = (combined_for_stats['홍수점수'] >= 10).sum()
            print(f"\n[홍수/침수위험 현황]")
            print(f"  • 홍수/침수위험구역 내 건물: {flood_count:,}개 ({100*flood_count/len(combined_for_stats):.1f}%)")

        if '산사태점수' in combined_for_stats.columns:
            landslide_high = (combined_for_stats['산사태점수'] >= 6).sum()
            print(f"\n[산사태위험 현황]")
            print(f"  • 산사태 고위험 (6점 이상): {landslide_high:,}개 ({100*landslide_high/len(combined_for_stats):.1f}%)")

    print("\n" + "=" * 70)

    # =========================================================================
    # 8. 추가 작업 여부 확인
    # =========================================================================
    print("\n" + "=" * 70)
    while True:
        continue_input = input("추가 분석을 진행하시겠습니까? (y/n): ").strip().lower()
        if continue_input == 'y':
            print("\n" + "=" * 70)
            print("새로운 분석을 시작합니다...")
            interactive_mode()  # 재귀 호출로 다시 시작
            return
        elif continue_input == 'n':
            print("\n" + "=" * 70)
            print("프로그램을 종료합니다. 감사합니다!")
            print("=" * 70)
            input("\n종료하려면 Enter 키를 누르세요...")
            return
        else:
            print("  ⚠️ 'y' 또는 'n'만 입력해주세요.")


def quick_analyze(region_name: str, district_names=None,
                  min_age: int = None, max_age: int = None,
                  include_flood: bool = True, include_landslide: bool = True,
                  search_query: str = None):
    """
    빠른 분석 실행 (스크립트에서 직접 호출용)

    Args:
        region_name: 지역명 (서울, 부산, 전북 등)
        district_names: 구/군명 (None이면 전체, str이면 단일, list면 복수)
        min_age: 최소 건물연령 필터
        max_age: 최대 건물연령 필터
        include_flood: 홍수위험 분석 포함 여부
        include_landslide: 산사태근접위험 분석 포함 여부
        search_query: 원래 사용자 입력값 (저장 경로 결정용, None이면 region_name 사용)

    Returns:
        분석 결과 GeoDataFrame (지도 시각화용 좌표 포함)

    출력 파일:
        - SHP: EPSG:5186 좌표계
        - CSV: 모든 분석 결과 포함

    출력 컬럼:
        - 위치: 지역, 구군, 지역코드, 주소, 중심점X, 중심점Y, 경도, 위도 (모두 EPSG:5186)
        - 개별위험: 노후등급/점수, 홍수등급/점수, 산사태등급/점수/거리
        - 조합위험: 노후홍수, 홍수산사태, 노후산사태 등급/점수
        - 종합위험: 종합점수, 종합등급, 위험코드

    Examples:
        # 단일 구/군 분석
        quick_analyze("전북", "전주시 완산구", min_age=30)

        # 복수 구/군 분석
        quick_analyze("전북", ["전주시 완산구", "전주시 덕진구"], min_age=30)

        # 광역지자체 전체 분석
        quick_analyze("전북", min_age=30)
    """
    base_path = r"C:\Users\user\Downloads\kescoaitest"
    analyzer = BuildingMultiRiskAnalyzer(base_path)

    all_results = []

    # district_names 처리: None, str, list 모두 지원
    if district_names is None:
        # 전체 분석
        districts = [None]
    elif isinstance(district_names, str):
        # 단일 구/군
        districts = [district_names]
    else:
        # 리스트
        districts = district_names

    for district in districts:
        result = analyzer.analyze_region(
            region_name, district, min_age, max_age,
            include_flood, include_landslide
        )

        if result is not None and len(result) > 0:
            analyzer.print_summary(result)
            analyzer.save_results(result, region_name=region_name,
                                district_name=district, min_age=min_age,
                                search_query=search_query or region_name)
            all_results.append(result)

    # 복수 결과 병합
    if len(all_results) > 1:
        import pandas as pd
        combined = pd.concat(all_results, ignore_index=True)
        return gpd.GeoDataFrame(combined, crs=all_results[0].crs)
    elif len(all_results) == 1:
        return all_results[0]
    else:
        return None


def batch_analyze(regions: dict, min_age: int = None, max_age: int = None,
                  include_flood: bool = True, include_landslide: bool = True):
    """
    복수 광역지자체 일괄 분석

    Args:
        regions: {지역명: 구/군 리스트 또는 None} 딕셔너리
        min_age: 최소 건물연령 필터
        max_age: 최대 건물연령 필터
        include_flood: 홍수위험 분석 포함 여부
        include_landslide: 산사태근접위험 분석 포함 여부

    Examples:
        # 복수 광역지자체, 복수 구/군
        batch_analyze({
            "전북": ["전주시 완산구", "전주시 덕진구"],
            "서울": ["종로구", "중구"]
        }, min_age=30)

        # 광역지자체 전체 분석
        batch_analyze({
            "전북": None,  # 전북 전체
            "부산": None   # 부산 전체
        }, min_age=30)
    """
    all_results = []

    for region_name, district_names in regions.items():
        result = quick_analyze(
            region_name, district_names, min_age, max_age,
            include_flood, include_landslide
        )
        if result is not None:
            all_results.append(result)

    print(f"\n{'='*70}")
    print(f"일괄 분석 완료: {len(regions)}개 광역지자체")
    print(f"{'='*70}")

    return all_results


if __name__ == "__main__":
    # 대화형 모드로 실행
    interactive_mode()

    # 또는 직접 호출 예시:

    # 1. 단일 구/군 분석
    # quick_analyze("전북", "전주시 완산구", min_age=30)

    # 2. 복수 구/군 분석
    # quick_analyze("전북", ["전주시 완산구", "전주시 덕진구"], min_age=30)

    # 3. 광역지자체 전체 분석
    # quick_analyze("전북", min_age=30)

    # 4. 복수 광역지자체 일괄 분석
    # batch_analyze({
    #     "전북": ["전주시 완산구", "전주시 덕진구"],
    #     "서울": None  # 서울 전체
    # }, min_age=30)
