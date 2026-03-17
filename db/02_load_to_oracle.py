#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
건물 위험분석 CSV → Oracle DB 적재 스크립트
- 다양한 CSV 포맷 (27/28/35/58/61/69컬럼) 자동 감지
- A0~A30 건축물대장 원본 데이터 포함 적재
- 사업소별 폴더 구조 자동 탐색
- --dry-run 옵션으로 DB 없이 CSV 파싱 검증
"""

import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# CSV 포맷별 컬럼 매핑 정의
# ---------------------------------------------------------------------------

# A0-A30이 포함된 포맷 (58/61/69 컬럼): 헤더가 A0, A1, ... A30 으로 시작
# A0-A30이 없는 포맷 (27/28/35 컬럼): 헤더가 지역, 구군, ... 으로 시작

def detect_format(header):
    """CSV 헤더를 분석하여 포맷 유형과 컬럼 매핑을 반환"""
    # BOM 제거
    h0 = header[0].lstrip('\ufeff').strip()
    ncols = len(header)

    has_a0 = (h0 == 'A0')

    if has_a0:
        return _map_a0_format(header, ncols)
    else:
        return _map_named_format(header, ncols)


def _map_a0_format(header, ncols):
    """A0~A30 포함 포맷 (58/61/69컬럼)"""
    # A0-A30 → 고정 위치 0~30
    m = {}
    for i in range(31):
        m[f'A{i}'] = i

    # 나머지 컬럼은 이름으로 찾기
    name_idx = {}
    for i, h in enumerate(header):
        name_idx[h.lstrip('\ufeff').strip()] = i

    # 분석결과 컬럼 매핑
    field_map = {
        'REGION_NM':       ['지역'],
        'DISTRICT_NM':     ['구군'],
        'REGION_CD':       ['지역코드'],
        'ADDR':            ['주소'],
        'CENTER_X':        ['중심점X'],
        'CENTER_Y':        ['중심점Y'],
        'LON':             ['경도'],
        'LAT':             ['위도'],
        'BUILD_YEAR':      ['건축년도'],
        'BUILD_AGE':       ['건물연령'],
        'AGE_RANGE':       ['연령대'],
        'AGE_GRADE':       ['노후등급'],
        'AGE_SCORE':       ['노후점수'],
        'FLOOD_OVERLAP':   ['겹침비율'],
        'FLOOD_GRADE':     ['홍수등급'],
        'FLOOD_SCORE':     ['홍수점수'],
        'LANDSLIDE_DIST':  ['산사태거리'],
        'LANDSLIDE_GRADE': ['산사태등급'],
        'LANDSLIDE_SCORE': ['산사태점수'],
        # 교차 점수 (69컬럼 포맷에서 일부 이름 잘림)
        'AGE_FLOOD_SCORE':  ['노후홍수점수', '노후홍수점'],
        'AGE_FLOOD_GRADE':  ['노후홍수등급', '노후홍수등'],
        'AGE_FLOOD_CD':     ['노후홍수코드', '노후홍수코'],
        'FLOOD_LAND_SCORE': ['홍수산사태점수', '홍수산사태'],
        'FLOOD_LAND_GRADE': ['홍수산사태등급', '홍수산사_1'],
        'FLOOD_LAND_CD':    ['홍수산사태코드', '홍수산사_2'],
        'AGE_LAND_SCORE':   ['노후산사태점수', '노후산사태'],
        'AGE_LAND_GRADE':   ['노후산사태등급', '노후산사_1'],
        'AGE_LAND_CD':      ['노후산사태코드', '노후산사_2'],
        'LAND_USE_CD':     ['용도코드'],
        'LAND_USE_NM':     ['용도명'],
        'LAND_USE_SCORE':  ['용도점수'],
        'FIRE_HIST':       ['전기화재'],
        'FIRE_MULT':       ['화재배수'],
        'FIRE_SCORE':      ['화재점수'],
        'PREV_FIRE_OCCUR_DATE': ['화재발생일', '이전화재발생일'],
        'BASE_SCORE':      ['기본점수'],
        'TOTAL_SCORE':     ['종합점수'],
        'TOTAL_GRADE':     ['종합등급'],
        'RISK_CD':         ['위험코드'],
    }

    for oracle_col, csv_names in field_map.items():
        for cn in csv_names:
            if cn in name_idx:
                m[oracle_col] = name_idx[cn]
                break

    return m


def _map_named_format(header, ncols):
    """이름 기반 포맷 (27/28/35컬럼) - A0~A30 없음"""
    name_idx = {}
    for i, h in enumerate(header):
        name_idx[h.lstrip('\ufeff').strip()] = i

    m = {}

    field_map = {
        'REGION_NM':       ['지역'],
        'DISTRICT_NM':     ['구군'],
        'REGION_CD':       ['지역코드'],
        'ADDR':            ['주소'],
        'CENTER_X':        ['중심점X'],
        'CENTER_Y':        ['중심점Y'],
        'LON':             ['경도'],
        'LAT':             ['위도'],
        'BUILD_YEAR':      ['건축년도'],
        'BUILD_AGE':       ['건물연령'],
        'AGE_RANGE':       ['연령대'],
        'AGE_GRADE':       ['노후등급'],
        'AGE_SCORE':       ['노후점수'],
        'FLOOD_OVERLAP':   ['겹침비율'],
        'FLOOD_GRADE':     ['홍수등급'],
        'FLOOD_SCORE':     ['홍수점수'],
        'LANDSLIDE_DIST':  ['산사태거리'],
        'LANDSLIDE_GRADE': ['산사태등급'],
        'LANDSLIDE_SCORE': ['산사태점수'],
        # 교차 점수 (35컬럼 포맷)
        'AGE_FLOOD_SCORE':  ['노후홍수점수'],
        'AGE_FLOOD_GRADE':  ['노후홍수등급'],
        'AGE_FLOOD_CD':     ['노후홍수코드'],
        'FLOOD_LAND_SCORE': ['홍수산사태점수'],
        'FLOOD_LAND_GRADE': ['홍수산사태등급'],
        'FLOOD_LAND_CD':    ['홍수산사태코드'],
        'AGE_LAND_SCORE':   ['노후산사태점수'],
        'AGE_LAND_GRADE':   ['노후산사태등급'],
        'AGE_LAND_CD':      ['노후산사태코드'],
        'LAND_USE_CD':     ['용도코드'],
        'LAND_USE_NM':     ['용도명'],
        'LAND_USE_SCORE':  ['용도점수'],
        'FIRE_HIST':       ['전기화재'],
        'FIRE_MULT':       ['화재배수'],
        'FIRE_SCORE':      ['화재점수'],
        'PREV_FIRE_OCCUR_DATE': ['화재발생일', '이전화재발생일'],
        'BASE_SCORE':      ['기본점수'],
        'TOTAL_SCORE':     ['종합점수'],
        'TOTAL_GRADE':     ['종합등급'],
        'RISK_CD':         ['위험코드'],
    }

    for oracle_col, csv_names in field_map.items():
        for cn in csv_names:
            if cn in name_idx:
                m[oracle_col] = name_idx[cn]
                break

    return m


# ---------------------------------------------------------------------------
# Oracle 테이블 컬럼 순서 (INSERT문에 사용)
# ---------------------------------------------------------------------------
ORACLE_COLUMNS = [
    'BLDG_SEQ', 'BRANCH_NM',
    # A0 ~ A30
    'A0','A1','A2','A3','A4','A5','A6','A7','A8','A9',
    'A10','A11','A12','A13','A14','A15','A16','A17','A18','A19',
    'A20','A21','A22','A23','A24','A25','A26','A27','A28','A29','A30',
    # 위치/주소
    'REGION_NM','DISTRICT_NM','REGION_CD','ADDR',
    'CENTER_X','CENTER_Y','LON','LAT',
    # 노후도
    'BUILD_YEAR','BUILD_AGE','AGE_RANGE','AGE_GRADE','AGE_SCORE',
    # 홍수
    'FLOOD_OVERLAP','FLOOD_GRADE','FLOOD_SCORE',
    # 산사태
    'LANDSLIDE_DIST','LANDSLIDE_GRADE','LANDSLIDE_SCORE',
    # 교차점수
    'AGE_FLOOD_SCORE','AGE_FLOOD_GRADE','AGE_FLOOD_CD',
    'FLOOD_LAND_SCORE','FLOOD_LAND_GRADE','FLOOD_LAND_CD',
    'AGE_LAND_SCORE','AGE_LAND_GRADE','AGE_LAND_CD',
    # 용도
    'LAND_USE_CD','LAND_USE_NM','LAND_USE_SCORE',
    # 화재
    'FIRE_HIST','FIRE_MULT','FIRE_SCORE','PREV_FIRE_OCCUR_DATE',
    # 종합
    'BASE_SCORE','TOTAL_SCORE','TOTAL_GRADE','RISK_CD',
    # 시스템
    'ANAL_DATE',
]

# 숫자 타입 컬럼 (빈 문자열 → None 변환 대상)
NUMERIC_COLS = {
    'A15','A20','A21','A22','A25',
    'CENTER_X','CENTER_Y','LON','LAT',
    'BUILD_YEAR','BUILD_AGE','AGE_SCORE',
    'FLOOD_OVERLAP','FLOOD_SCORE',
    'LANDSLIDE_DIST','LANDSLIDE_SCORE',
    'AGE_FLOOD_SCORE','FLOOD_LAND_SCORE','AGE_LAND_SCORE',
    'LAND_USE_SCORE','FIRE_HIST','FIRE_MULT','FIRE_SCORE',
    'BASE_SCORE','TOTAL_SCORE',
}

COMBINED_RISK_LEVELS = [
    (0, 10, '안전', 'A'),
    (10, 20, '관심', 'B'),
    (20, 30, '주의', 'C'),
    (30, 40, '경고', 'D'),
    (40, 999, '위험', 'E'),
]


def extract_anal_date(filename):
    """파일명에서 분석일자 추출: 통합위험분석_XXX_20260210.csv → 2026-02-10"""
    match = re.search(r'(\d{8})', filename)
    if match:
        ds = match.group(1)
        try:
            return datetime.strptime(ds, '%Y%m%d').date()
        except ValueError:
            pass
    return None


def extract_branch_name(filepath):
    """파일 경로에서 사업소명 추출

    경로 패턴 예시:
    - .../사업소별 분석결과/경기본부직할/통합위험분석_경기본부직할_20260211.csv
    - .../분석결과/통합위험분석_경기_20260130.csv (→ 파일명에서 추출)
    """
    parts = filepath.replace('\\', '/').split('/')

    # "사업소별 분석결과" 폴더 하위의 사업소명
    for i, p in enumerate(parts):
        if '사업소별' in p and i + 1 < len(parts):
            return parts[i + 1]

    # 파일명에서 추출: 통합위험분석_XXX_YYYYMMDD.csv
    basename = os.path.splitext(os.path.basename(filepath))[0]
    # 기상적용 파일 제외
    if '기상적용' in basename:
        # 통합위험분석_XXX_YYYYMMDD_기상적용_YYYYMMDD
        m = re.match(r'통합위험분석_(.+?)_\d{8}_기상적용', basename)
        if m:
            return m.group(1)

    m = re.match(r'통합위험분석_(.+?)_\d{8}', basename)
    if m:
        return m.group(1)

    return None


def safe_float(val):
    """문자열 → float, 실패 시 None"""
    if val is None or val == '' or val == 'nan':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_str(val, maxlen=None):
    """문자열 정리, 빈값 → None"""
    if val is None or val == '':
        return None
    s = str(val).strip()
    if maxlen and len(s) > maxlen:
        s = s[:maxlen]
    return s if s else None

def score_grade(score):
    """H2 테스트 적재 스크립트와 동일한 임계치로 등급/코드 산출"""
    s = safe_float(score)
    if s is None:
        s = 0.0
    for min_score, max_score, grade_nm, grade_cd in COMBINED_RISK_LEVELS:
        if min_score <= s < max_score:
            return grade_nm, grade_cd
    return '위험', 'E'

def normalize_jibun_address(addr):
    """주소 문자열에서 분석 원본의 불필요 토큰 제거"""
    s = safe_str(addr)
    if not s:
        return None
    s = re.sub(r'\s+', ' ', s.strip())
    # "... 1 일반건축물" / "... 2 집합건축물" 꼬리 제거
    s = re.sub(r'\s+\d+\s+(?:일반건축물|집합건축물)\s*$', '', s)
    # "... 1 일반 14-1 901" -> "... 14-1"
    s = re.sub(r'\s+\d+\s+\S+\s+([0-9]+(?:-[0-9]+)?)\s+[0-9]{1,4}\s*$', r' \1', s)
    # "... 226-6 100189865" / "... 226-6 100189865 1" 형태에서 코드 제거
    s = re.sub(r' ([0-9]+(?:-[0-9]+)?) [0-9]{4,}(?: \d+)?$', r' \1', s)
    # "... 후암동 1 일반 103-17" 형태에서 중간 토큰 제거
    s = re.sub(r'\s+\d+\s+\S+\s+([0-9]+(?:-[0-9]+)?)$', r' \1', s)
    return safe_str(s, 500)

def open_csv_with_fallback(path):
    """UTF-8/CP949 계열 인코딩 자동 감지"""
    last_error = None
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            f = open(path, 'r', encoding=enc, newline='')
            f.readline()
            f.seek(0)
            return f, enc
        except UnicodeDecodeError as e:
            last_error = e
            try:
                f.close()
            except Exception:
                pass
            continue
    if last_error:
        raise last_error
    raise UnicodeDecodeError('utf-8', b'', 0, 1, 'CSV 인코딩 감지 실패')


def row_to_oracle(row, col_map, branch_nm, anal_date):
    """CSV 행 → Oracle INSERT용 딕셔너리"""
    rec = {}

    # A0~A30
    for i in range(31):
        key = f'A{i}'
        if key in col_map:
            val = row[col_map[key]] if col_map[key] < len(row) else None
            if key in NUMERIC_COLS:
                rec[key] = safe_float(val)
            else:
                rec[key] = safe_str(val)
        else:
            rec[key] = None

    # 나머지 분석 컬럼
    analysis_cols = [
        c for c in ORACLE_COLUMNS
        if c not in ('BLDG_SEQ', 'BRANCH_NM', 'ANAL_DATE')
        and not (c.startswith('A') and c[1:].isdigit())
    ]

    for col in analysis_cols:
        if col in col_map and col_map[col] < len(row):
            val = row[col_map[col]]
            if col in NUMERIC_COLS:
                rec[col] = safe_float(val)
            else:
                rec[col] = safe_str(val)
        else:
            rec[col] = None

    rec['BRANCH_NM'] = branch_nm
    rec['ANAL_DATE'] = anal_date

    # A13(건물명)이 비어있으면 용도명으로 대체 (H2 테스트 적재 스크립트와 동일)
    if not rec.get('A13'):
        rec['A13'] = rec.get('LAND_USE_NM')

    # 주소 정제
    rec['ADDR'] = normalize_jibun_address(rec.get('ADDR'))

    # TOTAL_SCORE 기반 등급/코드 재산정 (CSV 원본값보다 계산값 우선)
    grade_nm, risk_cd = score_grade(rec.get('TOTAL_SCORE'))
    rec['TOTAL_GRADE'] = grade_nm
    rec['RISK_CD'] = risk_cd

    return rec


# ---------------------------------------------------------------------------
# CSV 파일 탐색
# ---------------------------------------------------------------------------
def find_csv_files(base_dir, exclude_weather=True):
    """분석결과 CSV 파일 탐색 (기상적용 파일은 기본 제외)"""
    patterns = [
        os.path.join(base_dir, '**', '통합위험분석*.csv'),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))

    if exclude_weather:
        files = [f for f in files if '기상적용' not in os.path.basename(f)]

    return sorted(set(files))


# ---------------------------------------------------------------------------
# DB 적재
# ---------------------------------------------------------------------------
def load_to_oracle(csv_files, conn_str, batch_size=5000, delete_first=True):
    """CSV 파일들을 Oracle에 적재"""
    try:
        import oracledb
    except ImportError:
        try:
            import cx_Oracle as oracledb
        except ImportError:
            print("[ERROR] oracledb 또는 cx_Oracle 라이브러리가 필요합니다.")
            print("  pip install oracledb")
            sys.exit(1)

    conn = oracledb.connect(conn_str)
    cursor = conn.cursor()

    if delete_first:
        print("[INFO] 기존 데이터 삭제 중...")
        cursor.execute("DELETE FROM TB_BLDG_RISK_STATIC")
        conn.commit()
        print(f"[INFO] {cursor.rowcount}건 삭제 완료")

    # INSERT SQL 생성
    # 운영 스키마(SEQ_BLDG_RISK)와 IDENTITY 스키마 모두 지원
    cursor.execute(
        "SELECT COUNT(*) FROM USER_SEQUENCES WHERE SEQUENCE_NAME = 'SEQ_BLDG_RISK'"
    )
    has_seq = cursor.fetchone()[0] > 0

    cols_no_seq = [c for c in ORACLE_COLUMNS if c != 'BLDG_SEQ']
    if has_seq:
        col_list = ', '.join(['BLDG_SEQ'] + cols_no_seq)
        val_list = ', '.join(['SEQ_BLDG_RISK.NEXTVAL'] + [f':{c}' for c in cols_no_seq])
    else:
        col_list = ', '.join(cols_no_seq)
        val_list = ', '.join([f':{c}' for c in cols_no_seq])
    insert_sql = f"INSERT INTO TB_BLDG_RISK_STATIC ({col_list}) VALUES ({val_list})"

    total_loaded = 0

    for fpath in csv_files:
        print(f"\n[LOAD] {os.path.basename(fpath)}")
        anal_date = extract_anal_date(fpath)
        branch_nm = extract_branch_name(fpath)

        try:
            with open_csv_with_fallback(fpath)[0] as f:
                reader = csv.reader(f)
                header = next(reader)
                col_map = detect_format(header)

                batch = []
                row_cnt = 0

                for row in reader:
                    if not row or all(c.strip() == '' for c in row):
                        continue
                    rec = row_to_oracle(row, col_map, branch_nm, anal_date)
                    batch.append(rec)
                    row_cnt += 1

                    if len(batch) >= batch_size:
                        cursor.executemany(insert_sql, batch)
                        conn.commit()
                        batch = []

                if batch:
                    cursor.executemany(insert_sql, batch)
                    conn.commit()

                total_loaded += row_cnt
                print(f"  → {row_cnt:,}건 적재 (사업소: {branch_nm}, 분석일: {anal_date})")

        except Exception as e:
            print(f"  [ERROR] {e}")
            conn.rollback()

    cursor.close()
    conn.close()
    print(f"\n[DONE] 총 {total_loaded:,}건 적재 완료")
    return total_loaded


# ---------------------------------------------------------------------------
# Dry-run (DB 없이 CSV 파싱 검증)
# ---------------------------------------------------------------------------
def dry_run(csv_files):
    """DB 연결 없이 CSV 파싱 검증"""
    print("=" * 70)
    print("  DRY-RUN: CSV 파싱 검증 (DB 연결 없음)")
    print("=" * 70)

    total = 0
    errors = 0
    format_summary = {}

    for fpath in csv_files:
        fname = os.path.basename(fpath)
        anal_date = extract_anal_date(fpath)
        branch_nm = extract_branch_name(fpath)

        try:
            with open_csv_with_fallback(fpath)[0] as f:
                reader = csv.reader(f)
                header = next(reader)
                ncols = len(header)
                col_map = detect_format(header)

                has_a0 = any(k.startswith('A') and k[1:].isdigit() for k in col_map if k.startswith('A'))
                fmt_key = f"{ncols}컬럼 ({'A0포함' if has_a0 else '이름'})"
                format_summary.setdefault(fmt_key, []).append(fname)

                # 매핑된 Oracle 컬럼 목록
                mapped = [c for c in ORACLE_COLUMNS
                          if c not in ('BLDG_SEQ', 'BRANCH_NM', 'ANAL_DATE')
                          and c in col_map]
                unmapped = [c for c in ORACLE_COLUMNS
                            if c not in ('BLDG_SEQ', 'BRANCH_NM', 'ANAL_DATE')
                            and c not in col_map
                            and not (c.startswith('A') and c[1:].isdigit() and not has_a0)]

                row_cnt = 0
                sample_rec = None
                for row in reader:
                    if not row or all(c.strip() == '' for c in row):
                        continue
                    rec = row_to_oracle(row, col_map, branch_nm, anal_date)
                    if sample_rec is None:
                        sample_rec = rec
                    row_cnt += 1

                total += row_cnt
                print(f"\n[OK] {fname}")
                print(f"     포맷: {ncols}컬럼 | 사업소: {branch_nm} | 분석일: {anal_date}")
                print(f"     데이터: {row_cnt:,}건 | 매핑: {len(mapped)}/{len(ORACLE_COLUMNS)-3}컬럼")
                if unmapped:
                    print(f"     미매핑(NULL): {', '.join(unmapped[:10])}")

        except Exception as e:
            print(f"\n[ERROR] {fname}: {e}")
            errors += 1

    print("\n" + "=" * 70)
    print(f"  검증 결과: 파일 {len(csv_files)}개 | 총 {total:,}건 | 오류 {errors}건")
    print("=" * 70)

    print("\n[포맷별 파일 분류]")
    for fmt, fnames in sorted(format_summary.items()):
        print(f"  {fmt}: {len(fnames)}개 파일")
        for fn in fnames[:3]:
            print(f"    - {fn}")
        if len(fnames) > 3:
            print(f"    ... 외 {len(fnames)-3}개")

    return total


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='건물 위험분석 CSV → Oracle 적재',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # DB 없이 CSV 파싱 검증
  python 02_load_to_oracle.py --base-dir ../Downloads/kescoaitest --dry-run

  # Oracle 적재
  python 02_load_to_oracle.py --base-dir ../Downloads/kescoaitest \\
      --conn "user/pass@host:1521/service"

  # TNS 접속
  python 02_load_to_oracle.py --base-dir ../Downloads/kescoaitest \\
      --conn "user/pass@tns_alias"

  # 기상적용 파일도 포함
  python 02_load_to_oracle.py --base-dir ../Downloads/kescoaitest \\
      --conn "user/pass@host:1521/service" --include-weather
        """)

    parser.add_argument('--base-dir', required=True,
                        help='분석결과 CSV 기본 디렉터리')
    parser.add_argument('--conn', default=None,
                        help='Oracle 접속 문자열 (user/pass@host:port/service)')
    parser.add_argument('--dry-run', action='store_true',
                        help='DB 연결 없이 CSV 파싱만 검증')
    parser.add_argument('--batch-size', type=int, default=5000,
                        help='배치 INSERT 크기 (기본: 5000)')
    parser.add_argument('--no-delete', action='store_true',
                        help='기존 데이터 삭제 안함 (추가 적재)')
    parser.add_argument('--include-weather', action='store_true',
                        help='기상적용 파일도 포함')

    args = parser.parse_args()

    # CSV 파일 탐색
    csv_files = find_csv_files(args.base_dir,
                               exclude_weather=not args.include_weather)

    if not csv_files:
        print(f"[ERROR] CSV 파일을 찾을 수 없습니다: {args.base_dir}")
        sys.exit(1)

    print(f"[INFO] CSV 파일 {len(csv_files)}개 발견")

    if args.dry_run:
        dry_run(csv_files)
    elif args.conn:
        load_to_oracle(csv_files, args.conn,
                       batch_size=args.batch_size,
                       delete_first=not args.no_delete)
    else:
        print("[ERROR] --conn 또는 --dry-run 옵션을 지정하세요.")
        sys.exit(1)


if __name__ == '__main__':
    main()
