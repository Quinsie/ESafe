#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT
CSV_PATH = (
    BASE_DIR
    / "사업소별 분석결과"
    / "광주전남본부"
    / "광주전남본부직할"
    / "통합위험분석_광주전남본부직할_20260303.csv"
)
SQL_PATH = (
    BASE_DIR
    / "api"
    / "src"
    / "main"
    / "resources"
    / "egovframework"
    / "spring"
    / "data-h2.sql"
)

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
    text = as_str(value)
    if not text:
        return default
    try:
        return float(text)
    except Exception:
        return default


def as_int_sql(value) -> str:
    text = as_str(value)
    if not text:
        return "NULL"
    try:
        return str(int(float(text)))
    except Exception:
        return "NULL"


def as_float_sql(value) -> str:
    text = as_str(value)
    if not text:
        return "NULL"
    try:
        return str(float(text))
    except Exception:
        return "NULL"


def extract_anal_date(csv_path: Path) -> str:
    match = re.search(r"(\d{8})", csv_path.stem)
    return match.group(1) if match else ""


def branch_from_filename(csv_path: Path) -> str:
    match = re.match(r"통합위험분석_(.+?)_\d{8}", csv_path.stem)
    return match.group(1) if match else "광주전남본부직할"


def grade_to_code(value: str) -> str:
    text = as_str(value)
    if text in ("A", "B", "C", "D", "E"):
        return text
    return GRADE_CODE_MAP.get(text, "C")


def pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and as_str(row.get(key)):
            return as_str(row.get(key))
    return ""


def normalize_row_keys(row: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        clean_key = str(key).replace("\ufeff", "").replace("\r", " ").replace("\n", " ").strip()
        clean_key = re.sub(r"\s+", " ", clean_key)
        normalized[clean_key] = value
    return normalized


def normalize_addr(value: str) -> str:
    text = as_str(value)
    if not text:
        return ""
    text = re.sub(r"\s+\d{3,}\s+\d+\s+(?:일반건축물|집합건축물)$", "", text)
    text = re.sub(r"\s+\d+\s+일반\s+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def open_reader(path: Path):
    last_error = None
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            handle = path.open("r", encoding=enc, newline="")
            return handle, csv.DictReader(handle)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    branch_nm = branch_from_filename(CSV_PATH)
    anal_date = extract_anal_date(CSV_PATH)
    row_count = 0
    non_empty_a17 = 0
    non_empty_a19 = 0

    handle, reader = open_reader(CSV_PATH)
    try:
        with SQL_PATH.open("w", encoding="utf-8", newline="\n") as out:
            out.write(f"-- H2 full branch data ({branch_nm})\n\n")

            for raw_row in reader:
                row = normalize_row_keys(raw_row)
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
                addr = esc(normalize_addr(pick(row, "주소")))

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
                row_count += 1
    finally:
        handle.close()

    print(f"Source CSV           : {CSV_PATH}")
    print(f"Output SQL           : {SQL_PATH}")
    print(f"Output building rows : {row_count}")
    print(f"Non-empty A17/A19    : {non_empty_a17} / {non_empty_a19}")


if __name__ == "__main__":
    main()
