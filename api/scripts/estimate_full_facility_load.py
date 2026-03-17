#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from collections import defaultdict
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
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def main() -> None:
    addr_counts: dict[str, int] = defaultdict(int)
    with BUILDING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            addr = normalize_building(row.get("주소", ""))
            if addr:
                addr_counts[addr] += 1

    general_inserts = 0
    fh, reader = open_reader(GENERAL_CSV)
    with fh:
        for row in reader:
            addr = normalize_facility(row.get("주소", ""))
            general_inserts += addr_counts.get(addr, 0)

    self_inserts = 0
    fh, reader = open_reader(SELF_CSV)
    with fh:
        for row in reader:
            addr = normalize_facility(row.get("지번주소") or row.get("주소") or row.get("도로명주소") or "")
            self_inserts += addr_counts.get(addr, 0)

    print(f"general_estimated_inserts={general_inserts}")
    print(f"self_estimated_inserts={self_inserts}")
    print(f"total_estimated_inserts={general_inserts + self_inserts}")


if __name__ == "__main__":
    main()
