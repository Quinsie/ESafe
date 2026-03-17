#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path


BASE = Path(r"C:\Users\user\Downloads\kescoaitest")
BUILDING_CSV = (
    BASE
    / "사업소별 분석결과"
    / "광주전남본부"
    / "광주전남본부직할"
    / "통합위험분석_광주전남본부직할_20260303.csv"
)
GENERAL_CSV = BASE / "설비데이터" / "광주전남 일반용 점검 데이터_정제.csv"
SELF_CSV = BASE / "설비데이터" / "광주전남 자가용 검사 데이터_정제.csv"
OUTPUT_SQL = (
    BASE
    / "api"
    / "src"
    / "main"
    / "resources"
    / "egovframework"
    / "spring"
    / "data-h2-facility-history.sql"
)
TODAY = "2026-03-12"


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().replace(",", " "))


def sql_str_or_null(value: str) -> str:
    if not value:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def normalize_cust_no(value: object) -> str:
    return re.sub(r"\.0$", "", normalize_text(value))


def normalize_general_result(value: object) -> str:
    return normalize_text(value) or "미입력"


def normalize_self_result(value: object) -> str:
    text = normalize_text(value)
    if "불합격" in text or "부적합" in text:
        return "불합격"
    return "합격"


def normalize_oral_yn(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if text.lower() == "y" or "예" in text:
        return "Y"
    if text.lower() == "n" or "아니오" in text:
        return "N"
    return ""


def normalize_date(value: object, fallback: str) -> str:
    text = normalize_text(value)
    if not text:
        return fallback
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return fallback


def parse_int(value: object) -> int | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def get_field(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return ""


def open_reader(path: Path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            return handle, csv.DictReader(handle)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def normalize_building_addr(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"\s+\d{3,}\s+\d+\s+(?:일반건축물|집합건축물)$", "", text)
    text = re.sub(r"\s+\d+\s+일반\s+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_addr_map() -> tuple[dict[str, list[int]], int]:
    addr_to_seq: dict[str, list[int]] = defaultdict(list)
    total_count = 0

    with BUILDING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total_count += 1
            addr = normalize_building_addr(row.get("주소"))
            if addr:
                addr_to_seq[addr].append(total_count)
            if total_count % 50000 == 0:
                print(f"loaded building rows: {total_count}")

    return addr_to_seq, total_count


def write_general(out, addr_to_seq: dict[str, list[int]]) -> tuple[int, int, int]:
    src_rows = 0
    matched_rows = 0
    insert_rows = 0
    matched_addrs: set[str] = set()

    handle, reader = open_reader(GENERAL_CSV)
    try:
        for row in reader:
            src_rows += 1
            addr = normalize_text(get_field(row, "주소"))
            if not addr:
                continue
            seqs = addr_to_seq.get(addr)
            if not seqs:
                continue
            matched_rows += 1
            matched_addrs.add(addr)
            branch_nm = normalize_text(get_field(row, "사업소"))
            cust_no = normalize_cust_no(get_field(row, "한전고객번호", "고객번호"))
            result = normalize_general_result(get_field(row, "결과"))
            oral_yn = normalize_oral_yn(get_field(row, "구두통보"))
            check_dt = normalize_date(get_field(row, "점검일자", "점검일"), TODAY)
            fail_detail = normalize_text(get_field(row, "부적합 내역", "부적합내역"))
            line_no = normalize_text(get_field(row, "선식번호"))
            capacity = normalize_text(get_field(row, "용량"))
            check_cycle = normalize_text(get_field(row, "주기"))
            contract_type = normalize_text(get_field(row, "계약종별"))

            for seq in seqs:
                out.write(
                    "INSERT INTO TB_FACILITY_GENERAL_HIST "
                    "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, CHECK_RESULT, ORAL_NOTICE_YN, NONCONFORMITY_DETAIL, "
                    "LINE_NO, CAPACITY, CHECK_CYCLE, CONTRACT_TYPE, CHECK_DT, RAW_JSON) VALUES "
                    f"({seq}, {sql_str_or_null(branch_nm)}, {sql_str_or_null(addr)}, {sql_str_or_null(cust_no)}, "
                    f"{sql_str_or_null(result)}, {sql_str_or_null(oral_yn)}, {sql_str_or_null(fail_detail)}, "
                    f"{sql_str_or_null(line_no)}, {sql_str_or_null(capacity)}, {sql_str_or_null(check_cycle)}, "
                    f"{sql_str_or_null(contract_type)}, DATE '{check_dt}', NULL);\n"
                )
                insert_rows += 1

            if src_rows % 100000 == 0:
                print(
                    f"general progress: src_rows={src_rows} matched_rows={matched_rows} "
                    f"inserts={insert_rows}"
                )
    finally:
        handle.close()

    return src_rows, matched_rows, insert_rows, len(matched_addrs)


def write_self(out, addr_to_seq: dict[str, list[int]]) -> tuple[int, int, int]:
    src_rows = 0
    matched_rows = 0
    insert_rows = 0
    matched_addrs: set[str] = set()

    handle, reader = open_reader(SELF_CSV)
    try:
        for row in reader:
            src_rows += 1
            addr = normalize_text(get_field(row, "지번주소", "주소", "도로명주소"))
            if not addr:
                continue
            seqs = addr_to_seq.get(addr)
            if not seqs:
                continue
            matched_rows += 1
            matched_addrs.add(addr)
            branch_nm = normalize_text(get_field(row, "사업소"))
            cust_no = normalize_cust_no(get_field(row, "고객번호", "한전고객번호"))
            result = normalize_self_result(get_field(row, "결과"))
            check_dt = normalize_date(get_field(row, "검사일", "점검일"), TODAY)
            defect_cnt = parse_int(get_field(row, "지적건수"))
            fail_detail = normalize_text(get_field(row, "불합격 내역", "부적합 내역", "부적합내역"))
            motor_type = normalize_text(get_field(row, "원동기종류"))
            defect_sql = "NULL" if defect_cnt is None else str(defect_cnt)

            for seq in seqs:
                out.write(
                    "INSERT INTO TB_FACILITY_SELF_HIST "
                    "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, INSPECTION_RESULT, FAIL_DETAIL, DEFECT_CNT, MOTOR_TYPE, CHECK_DT, RAW_JSON) VALUES "
                    f"({seq}, {sql_str_or_null(branch_nm)}, {sql_str_or_null(addr)}, {sql_str_or_null(cust_no)}, "
                    f"{sql_str_or_null(result)}, {sql_str_or_null(fail_detail)}, {defect_sql}, {sql_str_or_null(motor_type)}, "
                    f"DATE '{check_dt}', NULL);\n"
                )
                insert_rows += 1

            if src_rows % 10000 == 0:
                print(
                    f"self progress: src_rows={src_rows} matched_rows={matched_rows} "
                    f"inserts={insert_rows}"
                )
    finally:
        handle.close()

    return src_rows, matched_rows, insert_rows, len(matched_addrs)


def main() -> None:
    addr_to_seq, total_count = load_addr_map()
    with OUTPUT_SQL.open("w", encoding="utf-8", newline="\n") as out:
        out.write("-- Auto-generated full facility history from facility CSV\n")
        out.write("-- Generated at: 2026-03-12 12:00:00\n")
        out.write("-- RAW_JSON intentionally set to NULL for full-load H2 size control.\n")
        out.write("DELETE FROM TB_FACILITY_GENERAL_HIST;\n")
        out.write("DELETE FROM TB_FACILITY_SELF_HIST;\n\n")

        general_stats = write_general(out, addr_to_seq)
        self_stats = write_self(out, addr_to_seq)

    print(f"address_map_unique={len(addr_to_seq)} from_buildings={total_count}")
    print(
        "general_total_rows={} general_matched_rows={} general_inserts={} general_matched_unique_addresses={}".format(
            *general_stats
        )
    )
    print(
        "self_total_rows={} self_matched_rows={} self_inserts={} self_matched_unique_addresses={}".format(
            *self_stats
        )
    )
    print(f"output_sql={OUTPUT_SQL}")


if __name__ == "__main__":
    main()
