#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate H2 seed SQL from 광주전남본부직할 CSV.
Rules for this project task:
- Building rows: 10,000 rows
- Source buildings should match addresses selected from facility sample CSVs
- Facility sample focus:
  - 일반용: 부적합 / 부재종결 우선
  - 자가용: 불합격 우선
"""

from __future__ import annotations

import csv
import glob
import os
import re
from typing import Dict, List, Iterable

BASE_DIR = r"C:\Users\user\Downloads\kescoaitest"
CSV_DIR = os.path.join(BASE_DIR, "사업소별 분석결과", "광주전남본부", "광주전남본부직할")
CSV_GLOB = "통합위험분석_광주전남본부직할_*.csv"
GENERAL_CSV = os.path.join(BASE_DIR, "설비데이터", "일반용 샘플 데이터2.csv")
SELF_CSV = os.path.join(BASE_DIR, "설비데이터", "자가용 샘플 데이터.csv")
SQL_PATH = os.path.join(
    BASE_DIR,
    "api",
    "src",
    "main",
    "resources",
    "egovframework",
    "spring",
    "data-h2.sql",
)

BUILDING_TARGET_ROWS = 10000
GENERAL_SAMPLE_ROWS = 10000
SELF_SAMPLE_ROWS = 10000

GRADE_CODE_MAP = {
    "안전": "A",
    "양호": "B",
    "관심": "B",
    "보통": "C",
    "주의": "C",
    "노후": "D",
    "경고": "D",
    "위험": "E",
    "고령": "E",
    "매우위험": "E",
    "경계": "B",
}


def esc(value: str) -> str:
    return (value or "").replace("'", "''")


def as_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_float(value, default: float = 0.0) -> float:
    s = as_str(value)
    if not s:
        return default
    try:
        return float(s)
    except Exception:
        return default


def as_int_sql(value) -> str:
    s = as_str(value)
    if not s:
        return "NULL"
    try:
        return str(int(float(s)))
    except Exception:
        return "NULL"


def as_float_sql(value) -> str:
    s = as_str(value)
    if not s:
        return "NULL"
    try:
        return str(float(s))
    except Exception:
        return "NULL"


def extract_anal_date(csv_path: str) -> str:
    base = os.path.splitext(os.path.basename(csv_path))[0]
    m = re.search(r"(\d{8})", base)
    return m.group(1) if m else ""


def branch_from_filename(csv_path: str) -> str:
    base = os.path.splitext(os.path.basename(csv_path))[0]
    m = re.match(r"통합위험분석_(.+?)_\d{8}", base)
    return m.group(1) if m else "광주전남본부직할"


def grade_to_code(value: str) -> str:
    if not value:
        return "C"
    if value in ("A", "B", "C", "D", "E"):
        return value
    return GRADE_CODE_MAP.get(value, "C")


def pick(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and as_str(row.get(key)):
            return as_str(row.get(key))
    return ""


def normalize_row_keys(row: Dict[str, str]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        clean_key = str(key).replace("\ufeff", "").replace("\r", " ").replace("\n", " ").strip()
        clean_key = re.sub(r"\s+", " ", clean_key)
        normalized[clean_key] = value
    return normalized


def normalize_addr(v: str) -> str:
    s = as_str(v)
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_status(v: str) -> str:
    return re.sub(r"\s+", "", as_str(v))


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    encodings = ["utf-8-sig", "cp949", "utf-8"]
    last_error = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = [normalize_row_keys(r) for r in csv.DictReader(f)]
                return rows
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Failed to read CSV: {path} ({last_error})")


def prioritized_rows(rows: List[Dict[str, str]], limit: int, predicate) -> List[Dict[str, str]]:
    priority = [r for r in rows if predicate(r)]
    others = [r for r in rows if not predicate(r)]
    ordered = priority + others
    if limit <= 0:
        return ordered
    return ordered[:limit]


def extract_facility_addr_set() -> set[str]:
    general_rows = read_csv_rows(GENERAL_CSV)
    self_rows = read_csv_rows(SELF_CSV)

    sampled_general = prioritized_rows(
        general_rows,
        GENERAL_SAMPLE_ROWS,
        lambda r: ("부적합" in normalize_status(pick(r, "결과")) or "부재종결" in normalize_status(pick(r, "결과"))),
    )
    sampled_self = prioritized_rows(
        self_rows,
        SELF_SAMPLE_ROWS,
        lambda r: "불합격" in normalize_status(pick(r, "결과")),
    )

    addr_set: set[str] = set()
    for r in sampled_general:
        a = normalize_addr(pick(r, "주소"))
        if a:
            addr_set.add(a)
    for r in sampled_self:
        a = normalize_addr(pick(r, "지번주소", "주소", "도로명주소"))
        if a:
            addr_set.add(a)

    return addr_set


def main() -> None:
    csv_candidates = sorted(glob.glob(os.path.join(CSV_DIR, CSV_GLOB)))
    if not csv_candidates:
        raise FileNotFoundError(f"No source CSV found: {os.path.join(CSV_DIR, CSV_GLOB)}")

    csv_path = csv_candidates[-1]
    branch_nm = branch_from_filename(csv_path)
    anal_date = extract_anal_date(csv_path)

    rows = read_csv_rows(csv_path)
    addr_set = extract_facility_addr_set()

    matched = []
    for row in rows:
        if normalize_addr(pick(row, "주소")) in addr_set:
            matched.append(row)

    sample = matched[:BUILDING_TARGET_ROWS]

    non_empty_a17 = 0
    non_empty_a19 = 0

    with open(SQL_PATH, "w", encoding="utf-8") as out:
        out.write(f"-- H2 sample data ({branch_nm} {len(sample)} rows, matched-address-only)\n\n")

        for row in sample:
            a0 = esc(pick(row, "A0"))
            a13_raw = pick(row, "A13", "용도명")
            a17_raw = pick(row, "A17")
            a19_raw = pick(row, "A19")
            a13 = esc(a13_raw)
            a17 = esc(a17_raw)
            a19 = esc(a19_raw)
            if a17_raw:
                non_empty_a17 += 1
            if a19_raw:
                non_empty_a19 += 1
            region_nm = esc(pick(row, "지역"))
            district_nm = esc(pick(row, "구군"))
            region_cd = esc(pick(row, "지역코드"))
            addr = esc(pick(row, "주소"))

            lon = as_float(pick(row, "경도", "중심점X"), 0.0)
            lat = as_float(pick(row, "위도", "중심점Y"), 0.0)

            build_year_sql = as_int_sql(pick(row, "건축년도", "BUILD_YEAR"))
            build_age_sql = as_int_sql(pick(row, "건물연령", "BUILD_AGE"))
            completion_date = esc(pick(row, "A24", "사용승인일", "준공일자"))

            age_grade = grade_to_code(pick(row, "노후등급", "AGE_GRADE"))
            age_score = int(as_float(pick(row, "노후점수", "AGE_SCORE"), 0))

            flood_grade = grade_to_code(pick(row, "홍수등급", "FLOOD_GRADE"))
            flood_score = int(as_float(pick(row, "홍수점수", "FLOOD_SCORE"), 0))

            landslide_dist_sql = as_float_sql(pick(row, "산사태거리", "LANDSLIDE_DIST"))
            landslide_grade = grade_to_code(pick(row, "산사태등급", "LANDSLIDE_GRADE"))
            landslide_score = int(as_float(pick(row, "산사태점수", "LANDSLIDE_SCORE"), 0))

            fire_score = int(as_float(pick(row, "화재점수", "FIRE_SCORE"), 0))
            prev_fire_occur_date = esc(pick(row, "화재발생일", "이전화재발생일", "PREV_FIRE_OCCUR_DATE"))

            land_use_score = int(as_float(pick(row, "용도점수", "LAND_USE_SCORE"), 0))
            total_score = as_float(pick(row, "종합점수", "TOTAL_SCORE"), 0.0)

            total_grade_src = pick(row, "종합등급", "TOTAL_GRADE")
            total_grade = esc(total_grade_src)
            risk_cd = pick(row, "위험코드", "RISK_CD")
            if not risk_cd:
                risk_cd = grade_to_code(total_grade_src)
            risk_cd = esc(risk_cd)

            out.write(
                "INSERT INTO TB_BUILDING_RISK "
                "(BRANCH_NM,A0,A13,A17,A19,REGION_NM,DISTRICT_NM,REGION_CD,ADDR,LON,LAT,"
                "BUILD_YEAR,BUILD_AGE,A24,AGE_GRADE,AGE_SCORE,FLOOD_GRADE,FLOOD_SCORE,"
                "LANDSLIDE_DIST,LANDSLIDE_GRADE,LANDSLIDE_SCORE,FIRE_SCORE,PREV_FIRE_OCCUR_DATE,"
                "LAND_USE_SCORE,TOTAL_SCORE,TOTAL_GRADE,RISK_CD,ANAL_DATE) VALUES ("
                f"'{esc(branch_nm)}','{a0}','{a13}','{a17}','{a19}','{region_nm}','{district_nm}',"
                f"'{region_cd}','{addr}',{lon},{lat},{build_year_sql},{build_age_sql},"
                f"'{completion_date}','{age_grade}',{age_score},'{flood_grade}',{flood_score},"
                f"{landslide_dist_sql},'{landslide_grade}',{landslide_score},{fire_score},'{prev_fire_occur_date}',"
                f"{land_use_score},{total_score},'{total_grade}','{risk_cd}','{anal_date}');\n"
            )

    print(f"Source CSV              : {csv_path}")
    print(f"Facility address count  : {len(addr_set):,}")
    print(f"Matched building rows   : {len(matched):,}")
    print(f"Output building rows    : {len(sample):,}")
    if len(sample) < BUILDING_TARGET_ROWS:
        print(f"WARNING: target {BUILDING_TARGET_ROWS:,} not reached")
    print(f"Non-empty A17/A19       : {non_empty_a17:,} / {non_empty_a19:,}")
    print(f"Output SQL              : {SQL_PATH}")


if __name__ == "__main__":
    main()
