# -*- coding: utf-8 -*-
"""
기상특보 배치 스크립트 - API 호출 → 점수 산출 → Oracle 적재

기상청 API에서 당일 기상특보를 조회하고,
지역별 기상 위험점수를 산출하여 Oracle에 적재한다.

사용법:
  # dry-run (DB 없이 API + 점수 산출 검증)
  python 05_weather_batch.py --dry-run

  # Oracle 적재
  python 05_weather_batch.py --conn user/pass@host:1521/service

  # 과거 CSV 파일 기반 적재
  python 05_weather_batch.py --conn user/pass@host:1521/service --date 20260211

  # CSV 파일 경로 직접 지정
  python 05_weather_batch.py --dry-run --csv-file "/path/to/기상특보현황_20260211.csv"

실행:
  PYTHONIOENCODING=utf-8 /c/Users/user/AppData/Local/Programs/Python/Python313/python.exe -X utf8 "05_weather_batch.py" --dry-run
"""

import sys
import io
import os
import csv
import argparse
from datetime import datetime, date
from pathlib import Path

# Windows UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =============================================================================
# 기상청 API 호출 (save_weather_warnings_csv.py 로직)
# =============================================================================
API_AUTH_KEY = "7-5qPg-0Q7Suaj4PtBO09Q"
API_URL = "https://apihub.kma.go.kr/api/typ01/url/wrn_now_data.php"


def fetch_weather_alerts(auth_key: str = None) -> list:
    """기상청 API에서 현재 발효중인 특보 조회

    Returns:
        list of dict: 특보 레코드 목록
        각 dict 키: 특보종류, 특보수준, 특보명령, 특보구역명, 특보구역코드,
                    상위구역명, 발표시각, 발효시각, 해제예고
    """
    if auth_key is None:
        auth_key = API_AUTH_KEY

    params = {'disp': 1, 'help': 0, 'authKey': auth_key}

    try:
        resp = requests.get(API_URL, params=params, timeout=30, verify=False)
        resp.encoding = 'euc-kr'

        results = []
        for line in resp.text.strip().split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            fields = line.split(',')
            if len(fields) >= 10:
                results.append({
                    '상위구역코드': fields[0].strip(),
                    '상위구역명': fields[1].strip(),
                    '특보구역코드': fields[2].strip(),
                    '특보구역명': fields[3].strip(),
                    '발표시각': fields[4].strip(),
                    '발효시각': fields[5].strip(),
                    '특보종류': fields[6].strip(),
                    '특보수준': fields[7].strip(),
                    '특보명령': fields[8].strip(),
                    '해제예고': fields[9].strip().rstrip(',='),
                })
        return results
    except Exception as e:
        print(f"[ERROR] API 호출 실패: {e}")
        return []


def load_alerts_from_csv(csv_path: str) -> list:
    """기존 CSV 파일에서 특보 데이터 로드

    Args:
        csv_path: 기상특보현황_YYYYMMDD.csv 경로

    Returns:
        list of dict (fetch_weather_alerts와 동일 구조)
    """
    results = []
    encodings = ['utf-8-sig', 'utf-8', 'cp949']

    for enc in encodings:
        try:
            with open(csv_path, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    results.append(row)
            break
        except (UnicodeDecodeError, KeyError):
            continue

    if not results:
        print(f"[ERROR] CSV 로드 실패: {csv_path}")

    return results


# =============================================================================
# 기상점수 산출 (weather_risk_multiplier.py 로직)
# =============================================================================

# 호우/태풍/한파/폭염만 점수 부여, 나머지 0점
WEATHER_SCORES = {
    '호우': {'예비': 2, '주의': 6, '경보': 10},
    '태풍': {'예비': 2, '주의': 6, '경보': 10},
    '한파': {'예비': 2, '주의': 6, '경보': 10},
    '폭염': {'예비': 2, '주의': 6, '경보': 10},
}

# 기상특보 구역명에서 시도 추출 (상위구역명 기반)
PARENT_TO_REGION = {
    '서울특별시': '서울', '서울': '서울',
    '부산광역시': '부산', '부산': '부산',
    '대구광역시': '대구', '대구': '대구',
    '인천광역시': '인천', '인천': '인천',
    '광주광역시': '광주', '광주': '광주',
    '대전광역시': '대전', '대전': '대전',
    '울산광역시': '울산', '울산': '울산',
    '세종특별자치시': '세종', '세종': '세종',
    '경기도': '경기', '경기': '경기',
    '강원도': '강원', '강원특별자치도': '강원', '강원': '강원',
    '충청북도': '충북', '충북': '충북',
    '충청남도': '충남', '충남': '충남',
    '전라북도': '전북', '전북특별자치도': '전북', '전북': '전북',
    '전라남도': '전남', '전남': '전남',
    '경상북도': '경북', '경북': '경북',
    '경상남도': '경남', '경남': '경남',
    '제주특별자치도': '제주', '제주도': '제주', '제주': '제주',
}

# 특보구역명 → 시도별 구군 매핑 (weather_risk_multiplier.py의 weather_region_mapping 확장)
WEATHER_REGION_MAPPING = {
    # 서울 권역
    '서울동남권': ('서울', ['강남구', '서초구', '송파구', '강동구']),
    '서울동북권': ('서울', ['동대문구', '성동구', '광진구', '중랑구', '성북구', '강북구', '도봉구', '노원구']),
    '서울서남권': ('서울', ['영등포구', '구로구', '금천구', '동작구', '관악구']),
    '서울서북권': ('서울', ['마포구', '서대문구', '은평구', '용산구', '종로구', '중구']),
    # 부산
    '부산동부': ('부산', ['해운대구', '수영구', '남구', '동래구', '연제구', '금정구', '기장군']),
    '부산중부': ('부산', ['중구', '동구', '부산진구', '북구']),
    '부산서부': ('부산', ['서구', '사하구', '사상구', '강서구', '영도구']),
    # 울산
    '울산동부': ('울산', ['동구', '북구', '울주군']),
    '울산서부': ('울산', ['중구', '남구']),
    # 인천
    '인천동부': ('인천', ['남동구', '연수구', '중구', '동구', '미추홀구']),
    '인천서부': ('인천', ['서구', '계양구', '부평구']),
    # 경기 남부
    '경기남부': ('경기', ['수원시', '성남시', '안양시', '안산시', '용인시', '화성시', '평택시', '광명시',
                       '시흥시', '군포시', '의왕시', '과천시', '하남시', '오산시', '이천시', '안성시',
                       '광주시', '여주시', '양평군']),
    '경기북부': ('경기', ['고양시', '의정부시', '파주시', '양주시', '동두천시', '연천군', '포천시', '가평군',
                       '구리시', '남양주시']),
    # 강원 권역
    '강원남부평지': ('강원', []),
    '강원남부산지': ('강원', []),
    '강원북부평지': ('강원', []),
    '강원북부산지': ('강원', []),
    '강원중부평지': ('강원', []),
    '강원중부산지': ('강원', []),
}

# 접미사 제거용 (평지, 산지, 시 등)
REGION_SUFFIXES = ['평지', '산지', '안쪽', '바깥쪽', '먼바다', '앞바다', '전해상']


def normalize_region_name(name: str) -> str:
    """특보구역명 정규화 (접미사 제거)"""
    result = name
    for suffix in REGION_SUFFIXES:
        if result.endswith(suffix):
            result = result[:-len(suffix)]
    return result.strip()


def extract_parent_region(parent_name: str) -> str:
    """상위구역명에서 시도 약칭 추출"""
    return PARENT_TO_REGION.get(parent_name, parent_name)


def calculate_region_scores(alerts: list) -> dict:
    """특보 목록에서 지역(시도)별 기상점수 산출

    Args:
        alerts: fetch_weather_alerts() 또는 load_alerts_from_csv() 결과

    Returns:
        dict: {(시도명, 구군명): (점수, 적용특보문자열)} 매핑
        구군 매핑이 불가한 경우 구군명은 '' (시도 전체 적용)
    """
    # 1단계: 시도별 특보 수집
    #   key = (시도명, 구군명), value = [(특보종류, 특보수준), ...]
    region_alerts = {}

    for rec in alerts:
        alert_type = rec.get('특보종류', '')
        alert_level = rec.get('특보수준', '')
        region_nm = rec.get('특보구역명', '')
        parent = rec.get('상위구역명', '')

        if not alert_type or not alert_level:
            continue

        sido = extract_parent_region(parent)
        normalized = normalize_region_name(region_nm)

        # 권역 매핑 확인 (서울동남권 → 개별 구)
        if region_nm in WEATHER_REGION_MAPPING:
            mapped_sido, districts = WEATHER_REGION_MAPPING[region_nm]
            if districts:
                for dist in districts:
                    key = (mapped_sido, dist)
                    region_alerts.setdefault(key, []).append((alert_type, alert_level))
            else:
                # 구군 매핑 없음 → 시도 전체
                key = (mapped_sido, '')
                region_alerts.setdefault(key, []).append((alert_type, alert_level))
        elif normalized in WEATHER_REGION_MAPPING:
            mapped_sido, districts = WEATHER_REGION_MAPPING[normalized]
            if districts:
                for dist in districts:
                    key = (mapped_sido, dist)
                    region_alerts.setdefault(key, []).append((alert_type, alert_level))
            else:
                key = (mapped_sido, '')
                region_alerts.setdefault(key, []).append((alert_type, alert_level))
        else:
            # 직접 매핑: 구역명에서 시군구 추출 시도
            # 예: "강릉시평지" → "강릉시", "경주시" → "경주시"
            district_guess = normalized
            # 시/군/구로 끝나면 구군명으로 사용
            if any(district_guess.endswith(s) for s in ['시', '군', '구']):
                key = (sido, district_guess)
                region_alerts.setdefault(key, []).append((alert_type, alert_level))
            else:
                # 시도 전체 적용
                key = (sido, '')
                region_alerts.setdefault(key, []).append((alert_type, alert_level))

    # 2단계: 지역별 점수 계산
    result = {}
    for (sido, district), alert_list in region_alerts.items():
        score, applied_str = _calc_score(alert_list)
        result[(sido, district)] = (score, applied_str)

    return result


def _calc_score(alerts: list) -> tuple:
    """특보 목록 → (가산점, 적용특보문자열)

    - 태풍+강풍 중복 시 태풍만
    - 같은 종류 최고 점수만
    """
    if not alerts:
        return 0, ""

    # 태풍+강풍 중복 처리
    has_typhoon = any(t == '태풍' for t, _ in alerts)
    if has_typhoon:
        alerts = [(t, l) for t, l in alerts if t != '강풍']

    # 같은 종류 최고 점수만
    best = {}
    for alert_type, alert_level in alerts:
        score = WEATHER_SCORES.get(alert_type, {}).get(alert_level, 0)
        if alert_type not in best or score > best[alert_type][0]:
            best[alert_type] = (score, alert_level)

    total = 0
    parts = []
    for alert_type, (score, alert_level) in best.items():
        if score > 0:
            total += score
            parts.append(f"{alert_type}{alert_level}({score})")

    return total, ", ".join(parts)


# =============================================================================
# 지역코드 매핑 (TB_BLDG_RISK_STATIC에서 추출 또는 정적 사전)
# =============================================================================

def load_region_codes_from_db(cursor) -> dict:
    """DB에서 DISTINCT (REGION_NM, DISTRICT_NM, REGION_CD) 추출

    Returns:
        dict: {(시도명, 구군명): 지역코드}
    """
    sql = """
        SELECT DISTINCT REGION_NM, DISTRICT_NM, REGION_CD
          FROM TB_BLDG_RISK_STATIC
         WHERE REGION_CD IS NOT NULL
    """
    cursor.execute(sql)
    mapping = {}
    for region_nm, district_nm, region_cd in cursor:
        if region_nm and region_cd:
            mapping[(region_nm, district_nm or '')] = region_cd
    return mapping


def load_region_codes_static() -> dict:
    """정적 지역코드 매핑 (dry-run용, 주요 시도 코드)"""
    return {
        ('서울', ''): '11000',
        ('부산', ''): '26000',
        ('대구', ''): '27000',
        ('인천', ''): '28000',
        ('광주', ''): '29000',
        ('대전', ''): '30000',
        ('울산', ''): '31000',
        ('세종', ''): '36000',
        ('경기', ''): '41000',
        ('강원', ''): '42000',
        ('충북', ''): '43000',
        ('충남', ''): '44000',
        ('전북', ''): '45000',
        ('전남', ''): '46000',
        ('경북', ''): '47000',
        ('경남', ''): '48000',
        ('제주', ''): '50000',
    }


def resolve_region_code(sido: str, district: str, code_map: dict) -> str:
    """(시도, 구군) → 지역코드 매핑

    1차: 정확히 매칭
    2차: 구군 포함 검색
    3차: 시도만으로 매칭
    """
    # 정확히 매칭
    key = (sido, district)
    if key in code_map:
        return code_map[key]

    # 구군이 있으면 부분 매칭 시도
    if district:
        for (r, d), cd in code_map.items():
            if r == sido and d and district in d:
                return cd
            if r == sido and d and d in district:
                return cd

    # 시도만으로 매칭
    key = (sido, '')
    if key in code_map:
        return code_map[key]

    return ''


# =============================================================================
# Oracle 적재
# =============================================================================

def get_connection(conn_str: str):
    """Oracle 접속"""
    try:
        import oracledb
        # user/pass@host:port/service 파싱
        user_pass, dsn = conn_str.split('@', 1)
        user, password = user_pass.split('/', 1)
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        print(f"[OK] Oracle 접속 (oracledb): {dsn}")
        return conn
    except ImportError:
        pass

    try:
        import cx_Oracle
        user_pass, dsn = conn_str.split('@', 1)
        user, password = user_pass.split('/', 1)
        conn = cx_Oracle.connect(user=user, password=password, dsn=dsn)
        print(f"[OK] Oracle 접속 (cx_Oracle): {dsn}")
        return conn
    except ImportError:
        pass

    print("[ERROR] oracledb 또는 cx_Oracle 패키지가 필요합니다.")
    print("  pip install oracledb")
    sys.exit(1)


def insert_weather_alerts(cursor, alerts: list, alert_date: date):
    """TB_WEATHER_ALERT에 특보 원본 INSERT"""
    sql = """
        INSERT INTO TB_WEATHER_ALERT
            (ALERT_SEQ, ALERT_DATE, ALERT_TYPE, ALERT_LEVEL, ALERT_CMD,
             REGION_NM, REGION_CD, PARENT_REGION, ISSUE_DT, EFFECT_DT, CANCEL_NOTE)
        VALUES
            (SEQ_WEATHER_ALERT.NEXTVAL, :alert_date, :alert_type, :alert_level, :alert_cmd,
             :region_nm, :region_cd, :parent_region, :issue_dt, :effect_dt, :cancel_note)
    """
    rows = []
    for rec in alerts:
        rows.append({
            'alert_date': alert_date,
            'alert_type': rec.get('특보종류', ''),
            'alert_level': rec.get('특보수준', ''),
            'alert_cmd': rec.get('특보명령', ''),
            'region_nm': rec.get('특보구역명', ''),
            'region_cd': rec.get('특보구역코드', ''),
            'parent_region': rec.get('상위구역명', ''),
            'issue_dt': rec.get('발표시각', ''),
            'effect_dt': rec.get('발효시각', ''),
            'cancel_note': rec.get('해제예고', ''),
        })

    if rows:
        cursor.executemany(sql, rows)
    return len(rows)


def merge_weather_risk(cursor, scores: dict, alert_date: date, code_map: dict):
    """TB_WEATHER_RISK에 지역별 점수 MERGE (당일 데이터 갱신)"""
    sql = """
        MERGE INTO TB_WEATHER_RISK t
        USING (
            SELECT :risk_date AS RISK_DATE,
                   :region_cd AS REGION_CD,
                   :region_nm AS REGION_NM,
                   :district_nm AS DISTRICT_NM,
                   :weather_score AS WEATHER_SCORE,
                   :applied_alerts AS APPLIED_ALERTS
              FROM DUAL
        ) s
        ON (t.RISK_DATE = s.RISK_DATE AND t.REGION_CD = s.REGION_CD)
        WHEN MATCHED THEN
            UPDATE SET t.WEATHER_SCORE   = s.WEATHER_SCORE,
                       t.APPLIED_ALERTS  = s.APPLIED_ALERTS,
                       t.REG_DT          = SYSTIMESTAMP
        WHEN NOT MATCHED THEN
            INSERT (RISK_SEQ, RISK_DATE, REGION_CD, REGION_NM, DISTRICT_NM,
                    WEATHER_SCORE, APPLIED_ALERTS)
            VALUES (SEQ_WEATHER_RISK.NEXTVAL, s.RISK_DATE, s.REGION_CD, s.REGION_NM,
                    s.DISTRICT_NM, s.WEATHER_SCORE, s.APPLIED_ALERTS)
    """
    count = 0
    for (sido, district), (score, applied_str) in scores.items():
        region_cd = resolve_region_code(sido, district, code_map)
        if not region_cd:
            print(f"  [SKIP] 지역코드 미매핑: {sido} {district}")
            continue

        cursor.execute(sql, {
            'risk_date': alert_date,
            'region_cd': region_cd,
            'region_nm': sido,
            'district_nm': district,
            'weather_score': score,
            'applied_alerts': applied_str,
        })
        count += 1

    return count


def delete_alerts_for_date(cursor, alert_date: date):
    """당일 기존 특보 원본 삭제 (재적재 대비)"""
    cursor.execute(
        "DELETE FROM TB_WEATHER_ALERT WHERE ALERT_DATE = :d",
        {'d': alert_date}
    )
    return cursor.rowcount


# =============================================================================
# 메인 배치
# =============================================================================

def run_batch(args):
    """배치 메인 로직"""
    print("=" * 70)
    print("  기상특보 배치 - API 호출 → 점수 산출 → Oracle 적재")
    print("=" * 70)

    # ----- 1. 특보 데이터 취득 -----
    if args.csv_file:
        # 직접 지정한 CSV 파일
        print(f"\n[1/4] CSV 파일 로드: {args.csv_file}")
        alerts = load_alerts_from_csv(args.csv_file)
        # 날짜 추출
        if args.date:
            alert_date = datetime.strptime(args.date, '%Y%m%d').date()
        else:
            # 파일명에서 추출 시도
            basename = os.path.basename(args.csv_file)
            for part in basename.replace('.', '_').split('_'):
                if len(part) == 8 and part.isdigit():
                    alert_date = datetime.strptime(part, '%Y%m%d').date()
                    break
            else:
                alert_date = date.today()
    elif args.date:
        # 과거 날짜 CSV 파일 찾기
        alert_date = datetime.strptime(args.date, '%Y%m%d').date()
        print(f"\n[1/4] 과거 데이터 로드: {args.date}")

        # 기본 CSV 경로 탐색
        search_dirs = [
            os.path.join(os.path.dirname(__file__), '..', '기상특보'),
            os.path.join(os.path.dirname(__file__)),
            str(Path(__file__).resolve().parents[1] / '기상특보'),
        ]
        csv_path = None
        for d in search_dirs:
            candidate = os.path.join(d, f'기상특보현황_{args.date}.csv')
            if os.path.isfile(candidate):
                csv_path = candidate
                break

        if csv_path:
            print(f"  CSV 파일 발견: {csv_path}")
            alerts = load_alerts_from_csv(csv_path)
        else:
            print(f"  [WARN] CSV 파일 없음 → API 호출로 대체 (당일 데이터)")
            alerts = fetch_weather_alerts(args.auth_key)
    else:
        # 당일 API 호출
        alert_date = date.today()
        print(f"\n[1/4] 기상청 API 호출 ({alert_date})")
        alerts = fetch_weather_alerts(args.auth_key)

    if not alerts:
        print("  특보 데이터 없음 (발효중인 특보가 없거나 API 오류)")
        print("  → 전 지역 기상점수 0점으로 처리")

    print(f"  조회된 특보: {len(alerts)}건")
    print(f"  기준일자: {alert_date}")

    # 특보 유형 요약 출력
    if alerts:
        type_counts = {}
        for rec in alerts:
            key = f"{rec.get('특보종류', '')} {rec.get('특보수준', '')}"
            type_counts[key] = type_counts.get(key, 0) + 1
        print("\n  [특보 현황]")
        for key in sorted(type_counts.keys()):
            print(f"    {key}: {type_counts[key]}건")

    # ----- 2. 지역별 기상점수 산출 -----
    print(f"\n[2/4] 지역별 기상점수 산출")
    region_scores = calculate_region_scores(alerts)

    scored_regions = {k: v for k, v in region_scores.items() if v[0] > 0}
    print(f"  전체 매핑 지역: {len(region_scores)}개")
    print(f"  점수 발생 지역: {len(scored_regions)}개")

    if scored_regions:
        print("\n  [점수 발생 지역]")
        for (sido, district), (score, applied) in sorted(scored_regions.items()):
            label = f"{sido} {district}".strip()
            print(f"    {label}: {score}점 ({applied})")

    # ----- 3. Oracle 적재 -----
    if args.dry_run:
        print(f"\n[3/4] Oracle 적재 (dry-run → 건너뜀)")
        print(f"  --dry-run 모드: DB 접속 없이 검증만 수행")
    else:
        print(f"\n[3/4] Oracle 적재")

        if not args.conn:
            print("[ERROR] --conn 접속문자열이 필요합니다.")
            sys.exit(1)

        conn = get_connection(args.conn)
        cursor = conn.cursor()

        try:
            # 지역코드 매핑 로드
            print("  지역코드 매핑 로드...")
            code_map = load_region_codes_from_db(cursor)
            if not code_map:
                print("  [WARN] DB에 지역코드 없음 → 정적 매핑 사용")
                code_map = load_region_codes_static()
            print(f"  지역코드: {len(code_map)}건")

            # 당일 기존 데이터 삭제 (재적재)
            deleted = delete_alerts_for_date(cursor, alert_date)
            if deleted:
                print(f"  기존 특보 삭제: {deleted}건")

            # TB_WEATHER_ALERT INSERT
            inserted = insert_weather_alerts(cursor, alerts, alert_date)
            print(f"  TB_WEATHER_ALERT INSERT: {inserted}건")

            # TB_WEATHER_RISK MERGE
            merged = merge_weather_risk(cursor, region_scores, alert_date, code_map)
            print(f"  TB_WEATHER_RISK MERGE: {merged}건")

            conn.commit()
            print("  COMMIT 완료")
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Oracle 적재 실패 (ROLLBACK): {e}")
            import traceback
            traceback.print_exc()
        finally:
            cursor.close()
            conn.close()

    # ----- 4. 결과 요약 -----
    print(f"\n[4/4] 배치 완료")
    print("-" * 70)
    print(f"  기준일자     : {alert_date}")
    print(f"  조회 특보    : {len(alerts)}건")
    print(f"  매핑 지역    : {len(region_scores)}개")
    print(f"  점수 발생    : {len(scored_regions)}개")
    if scored_regions:
        max_region = max(scored_regions.items(), key=lambda x: x[1][0])
        label = f"{max_region[0][0]} {max_region[0][1]}".strip()
        print(f"  최고 점수    : {max_region[1][0]}점 ({label})")
    print(f"  모드         : {'dry-run' if args.dry_run else 'Oracle 적재'}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='기상특보 배치 - API 호출 → 점수 산출 → Oracle 적재',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # dry-run (검증만)
  python 05_weather_batch.py --dry-run

  # Oracle 적재
  python 05_weather_batch.py --conn user/pass@host:1521/service

  # 과거 CSV 기반 적재
  python 05_weather_batch.py --conn user/pass@host:1521/service --date 20260211

  # 특정 CSV 파일 지정
  python 05_weather_batch.py --dry-run --csv-file "기상특보현황_20260211.csv"
        """
    )
    parser.add_argument('--conn', type=str, default=None,
                        help='Oracle 접속문자열 (user/pass@host:port/service)')
    parser.add_argument('--dry-run', action='store_true',
                        help='DB 없이 API + 점수 산출만 검증')
    parser.add_argument('--date', type=str, default=None,
                        help='특정일자 (YYYYMMDD, 과거 CSV 파일 기반)')
    parser.add_argument('--csv-file', type=str, default=None,
                        help='CSV 파일 경로 직접 지정')
    parser.add_argument('--auth-key', type=str, default=API_AUTH_KEY,
                        help='기상청 API 인증키')

    args = parser.parse_args()

    # 유효성 검사
    if not args.dry_run and not args.conn:
        print("[ERROR] --conn 또는 --dry-run 중 하나를 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)

    run_batch(args)


if __name__ == '__main__':
    main()
