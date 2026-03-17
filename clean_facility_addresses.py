#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import shutil
import time
from pathlib import Path


DOUBLE_SPACE_RE = re.compile(r"\s{2,}")
TRAILING_ZERO_LOT_RE = re.compile(r"(?<=\d)-0(?=(?:\s|,|\)|$))")
SPACE_AROUND_COMMA_RE = re.compile(r"\s*,\s*")
EMPTY_COMMA_SEGMENT_RE = re.compile(r",\s*,\s*")
SPACE_AFTER_OPEN_PAREN_RE = re.compile(r"\(\s+")
SPACE_BEFORE_CLOSE_PAREN_RE = re.compile(r"\s+\)")
MISSING_SPACE_BEFORE_PAREN_RE = re.compile(r"(?<=[^\s,(])\(")
PROJECT_ROOT = Path(__file__).resolve().parent


def clean_address(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text

    text = DOUBLE_SPACE_RE.sub(" ", text)
    text = TRAILING_ZERO_LOT_RE.sub("", text)
    text = SPACE_AROUND_COMMA_RE.sub(", ", text)
    while EMPTY_COMMA_SEGMENT_RE.search(text):
        text = EMPTY_COMMA_SEGMENT_RE.sub(", ", text)
    text = SPACE_AFTER_OPEN_PAREN_RE.sub("(", text)
    text = SPACE_BEFORE_CLOSE_PAREN_RE.sub(")", text)
    text = MISSING_SPACE_BEFORE_PAREN_RE.sub(" (", text)
    text = DOUBLE_SPACE_RE.sub(" ", text)
    return text.strip()


def open_reader(path: Path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            return handle, csv.DictReader(handle), encoding
        except Exception as exc:  # pragma: no cover
            last_error = exc
    raise RuntimeError(f"failed to open {path}: {last_error}")


def process_file(path: Path, target_columns: list[str], backup_suffix: str) -> tuple[int, int]:
    backup_path = path.with_name(path.name + backup_suffix)
    tmp_path = path.with_name(path.name + ".tmp")

    if not backup_path.exists():
        shutil.copy2(path, backup_path)

    changed_rows = 0
    changed_cells = 0

    src_handle, reader, _ = open_reader(path)
    try:
        fieldnames = list(reader.fieldnames or [])
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as dst_handle:
            writer = csv.DictWriter(dst_handle, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                row_changed = False
                for column in target_columns:
                    original = row.get(column, "")
                    cleaned = clean_address(original)
                    if cleaned != original:
                        row[column] = cleaned
                        changed_cells += 1
                        row_changed = True
                if row_changed:
                    changed_rows += 1
                writer.writerow(row)
    finally:
        src_handle.close()

    if changed_cells == 0:
        tmp_path.unlink(missing_ok=True)
        return changed_rows, changed_cells

    last_error = None
    for _ in range(10):
        try:
            shutil.move(tmp_path, path)
            break
        except PermissionError as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise last_error

    return changed_rows, changed_cells


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean facility CSV address fields in place.")
    parser.add_argument(
        "--backup-suffix",
        default=".backup_addrfix_20260312",
        help="suffix appended to the one-time backup file",
    )
    args = parser.parse_args()

    files = [
        (
            PROJECT_ROOT / "설비데이터" / "광주전남 일반용 점검 데이터_정제.csv",
            ["주소"],
        ),
        (
            PROJECT_ROOT / "설비데이터" / "광주전남 자가용 검사 데이터_정제.csv",
            ["지번주소", "도로명주소"],
        ),
    ]

    for path, columns in files:
        changed_rows, changed_cells = process_file(path, columns, args.backup_suffix)
        print(f"{path.name}: changed_rows={changed_rows}, changed_cells={changed_cells}")


if __name__ == "__main__":
    main()
