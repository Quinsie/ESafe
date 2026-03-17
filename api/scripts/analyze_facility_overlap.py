#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE = PROJECT_ROOT
BUILDING_CSV = (
    BASE
    / "사업소별 분석결과"
    / "광주전남본부"
    / "광주전남본부직할"
    / "통합위험분석_광주전남본부직할_20260303.csv"
)
GENERAL_CSV = BASE / "설비데이터" / "광주전남 일반용 점검 데이터_정제.csv"
SELF_CSV = BASE / "설비데이터" / "광주전남 자가용 검사 데이터_정제.csv"


def normalize_building(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+\d{3,}\s+\d+\s+(?:일반건축물|집합건축물)$", "", text)
    text = re.sub(r"\s+\d+\s+일반\s+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_facility(value: str) -> str:
    text = (value or "").strip().replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def open_reader(path: Path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            return handle, csv.DictReader(handle)
        except Exception as exc:  # pragma: no cover
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def main() -> None:
    building_addrs: set[str] = set()
    total_building_rows = 0
    with BUILDING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total_building_rows += 1
            addr = normalize_building(row.get("주소", ""))
            if addr:
                building_addrs.add(addr)

    fh, reader = open_reader(GENERAL_CSV)
    general_total_rows = 0
    general_match_rows = 0
    general_addrs: set[str] = set()
    general_match_addrs: set[str] = set()
    with fh:
        for row in reader:
            general_total_rows += 1
            addr = normalize_facility(row.get("주소", ""))
            if not addr:
                continue
            general_addrs.add(addr)
            if addr in building_addrs:
                general_match_rows += 1
                general_match_addrs.add(addr)

    fh, reader = open_reader(SELF_CSV)
    self_total_rows = 0
    self_match_rows = 0
    self_addrs: set[str] = set()
    self_match_addrs: set[str] = set()
    with fh:
        for row in reader:
            self_total_rows += 1
            addr = normalize_facility(row.get("지번주소") or row.get("주소") or row.get("도로명주소") or "")
            if not addr:
                continue
            self_addrs.add(addr)
            if addr in building_addrs:
                self_match_rows += 1
                self_match_addrs.add(addr)

    print(f"building_total_rows={total_building_rows}")
    print(f"building_unique_addresses={len(building_addrs)}")
    print(f"general_total_rows={general_total_rows}")
    print(f"general_unique_addresses={len(general_addrs)}")
    print(f"general_matched_rows={general_match_rows}")
    print(f"general_matched_unique_addresses={len(general_match_addrs)}")
    print(f"self_total_rows={self_total_rows}")
    print(f"self_unique_addresses={len(self_addrs)}")
    print(f"self_matched_rows={self_match_rows}")
    print(f"self_matched_unique_addresses={len(self_match_addrs)}")


if __name__ == "__main__":
    main()
