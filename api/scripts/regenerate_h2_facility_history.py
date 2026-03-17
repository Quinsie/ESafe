#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from http.cookiejar import CookieJar
from pathlib import Path


BASE = Path(r"C:\Users\user\Downloads\kescoaitest")
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
API_BASE = "http://localhost:18080"
USERNAME = "localadmin"
PASSWORD = "LocalAdmin123"
PAGE_SIZE = 1000
TODAY = "2026-03-12"
GENERAL_LIMIT = 10000
SELF_LIMIT = 10000
GENERAL_TARGET = 10000
SELF_TARGET = 10000


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
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            handle = path.open("r", encoding=enc, newline="")
            return handle, csv.DictReader(handle)
        except Exception as exc:  # pragma: no cover
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def select_rows(path: Path, limit: int, is_priority, addr_fields: tuple[str, ...]) -> list[dict[str, str]]:
    priority: list[dict[str, str]] = []
    others: list[dict[str, str]] = []
    handle, reader = open_reader(path)
    try:
        for row in reader:
            addr = normalize_text(get_field(row, *addr_fields))
            if not addr:
                continue
            if is_priority(row):
                if len(priority) < limit:
                    priority.append(row)
            elif len(others) < limit:
                others.append(row)
    finally:
        handle.close()

    if len(priority) >= limit:
        return priority[:limit]
    return priority + others[: limit - len(priority)]


def load_addr_map() -> tuple[dict[str, list[int]], int]:
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    login_html = opener.open(API_BASE + "/login.do", timeout=60).read().decode("utf-8", errors="replace")
    match = re.search(r'name="_csrf" value="([^"]+)"', login_html)
    if not match:
        raise RuntimeError("failed to parse csrf token")

    payload = urllib.parse.urlencode(
        {"username": USERNAME, "password": PASSWORD, "_csrf": match.group(1)}
    ).encode("utf-8")
    opener.open(API_BASE + "/perform_login.do", data=payload, timeout=60).read()

    addr_to_seq: dict[str, list[int]] = defaultdict(list)
    total_count = 0
    page = 1
    while True:
        url = f"{API_BASE}/selectCombinedList.do?pageIndex={page}&pageSize={PAGE_SIZE}"
        data = json.loads(opener.open(url, timeout=120).read().decode("utf-8"))
        if page == 1:
            total_count = int(data.get("totalCount", 0))
        for row in data.get("data", []):
            addr = normalize_text(row.get("addr"))
            if addr:
                addr_to_seq[addr].append(int(row["bldgSeq"]))
        if page * PAGE_SIZE >= total_count:
            break
        page += 1

    return addr_to_seq, total_count


def fill_to_target(lines: list[str], target: int) -> list[str]:
    if not lines or len(lines) >= target:
        return lines
    base = list(lines)
    idx = 0
    while len(lines) < target:
        lines.append(base[idx % len(base)])
        idx += 1
    return lines


def main() -> None:
    addr_to_seq, total_count = load_addr_map()
    general_rows = select_rows(
        GENERAL_CSV,
        GENERAL_LIMIT,
        lambda row: any(x in normalize_text(get_field(row, "결과")) for x in ("부적합", "부재종결")),
        ("주소",),
    )
    self_rows = select_rows(
        SELF_CSV,
        SELF_LIMIT,
        lambda row: "불합격" in normalize_text(get_field(row, "결과")),
        ("지번주소", "주소", "도로명주소"),
    )

    lines = [
        "-- Auto-generated from facility CSV",
        "-- Generated at: 2026-03-12 11:20:00",
        f"-- General sample rows: {len(general_rows)}, Self sample rows: {len(self_rows)}",
        "DELETE FROM TB_FACILITY_GENERAL_HIST;",
        "DELETE FROM TB_FACILITY_SELF_HIST;",
        "",
    ]

    general_generated: list[str] = []
    self_generated: list[str] = []
    general_seen_addr: set[str] = set()
    self_seen_addr: set[str] = set()
    general_dedup: set[str] = set()
    self_dedup: set[str] = set()

    for row in general_rows:
        if len(general_generated) >= GENERAL_TARGET:
            break
        addr = normalize_text(get_field(row, "주소"))
        if not addr or addr not in addr_to_seq:
            continue
        general_seen_addr.add(addr)
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
        raw_json = json.dumps(row, ensure_ascii=False, separators=(",", ":"))

        for seq in addr_to_seq[addr]:
            if len(general_generated) >= GENERAL_TARGET:
                break
            dedup_key = "|".join(
                [str(seq), cust_no, result, check_dt, addr, line_no, capacity, check_cycle, contract_type]
            )
            if dedup_key in general_dedup:
                continue
            general_dedup.add(dedup_key)
            general_generated.append(
                "INSERT INTO TB_FACILITY_GENERAL_HIST "
                "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, CHECK_RESULT, ORAL_NOTICE_YN, NONCONFORMITY_DETAIL, "
                "LINE_NO, CAPACITY, CHECK_CYCLE, CONTRACT_TYPE, CHECK_DT, RAW_JSON) VALUES "
                f"({seq}, {sql_str_or_null(branch_nm)}, {sql_str_or_null(addr)}, {sql_str_or_null(cust_no)}, "
                f"{sql_str_or_null(result)}, {sql_str_or_null(oral_yn)}, {sql_str_or_null(fail_detail)}, "
                f"{sql_str_or_null(line_no)}, {sql_str_or_null(capacity)}, {sql_str_or_null(check_cycle)}, "
                f"{sql_str_or_null(contract_type)}, DATE '{check_dt}', {sql_str_or_null(raw_json)});"
            )

    for row in self_rows:
        if len(self_generated) >= SELF_TARGET:
            break
        addr = normalize_text(get_field(row, "지번주소", "주소", "도로명주소"))
        if not addr or addr not in addr_to_seq:
            continue
        self_seen_addr.add(addr)
        branch_nm = normalize_text(get_field(row, "사업소"))
        cust_no = normalize_cust_no(get_field(row, "고객번호", "한전고객번호"))
        result = normalize_self_result(get_field(row, "결과"))
        check_dt = normalize_date(get_field(row, "검사일", "점검일"), TODAY)
        defect_cnt = parse_int(get_field(row, "지적건수"))
        fail_detail = normalize_text(get_field(row, "불합격 내역", "부적합 내역", "부적합내역"))
        motor_type = normalize_text(get_field(row, "원동기종류"))
        raw_json = json.dumps(row, ensure_ascii=False, separators=(",", ":"))

        for seq in addr_to_seq[addr]:
            if len(self_generated) >= SELF_TARGET:
                break
            defect_sql = "NULL" if defect_cnt is None else str(defect_cnt)
            dedup_key = "|".join([str(seq), cust_no, result, check_dt, addr, defect_sql, motor_type])
            if dedup_key in self_dedup:
                continue
            self_dedup.add(dedup_key)
            self_generated.append(
                "INSERT INTO TB_FACILITY_SELF_HIST "
                "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, INSPECTION_RESULT, FAIL_DETAIL, DEFECT_CNT, MOTOR_TYPE, CHECK_DT, RAW_JSON) VALUES "
                f"({seq}, {sql_str_or_null(branch_nm)}, {sql_str_or_null(addr)}, {sql_str_or_null(cust_no)}, "
                f"{sql_str_or_null(result)}, {sql_str_or_null(fail_detail)}, {defect_sql}, {sql_str_or_null(motor_type)}, "
                f"DATE '{check_dt}', {sql_str_or_null(raw_json)});"
            )

    lines.extend(fill_to_target(general_generated, GENERAL_TARGET))
    lines.extend(fill_to_target(self_generated, SELF_TARGET))
    OUTPUT_SQL.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Address map loaded: {len(addr_to_seq)} unique addresses (from {total_count} buildings)")
    print(f"General inserts: {len(general_generated)}/{GENERAL_TARGET} (matched addresses: {len(general_seen_addr)})")
    print(f"Self inserts: {len(self_generated)}/{SELF_TARGET} (matched addresses: {len(self_seen_addr)})")
    print(f"Output SQL: {OUTPUT_SQL}")


if __name__ == "__main__":
    main()
