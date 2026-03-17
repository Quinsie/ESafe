# -*- coding: utf-8 -*-
"""
Auto statistical report generator.

This script scans the latest analysis shapefile for a selected branch/region,
creates a lightweight summary report, and exports CSV/TXT outputs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

try:
    import geopandas as gpd
except ImportError as exc:
    raise SystemExit(f"geopandas is required: {exc}")

BASE_PATH = Path(__file__).resolve().parent
BRANCH_RESULT_PATH = BASE_PATH / "사업소별 분석결과"
REGION_RESULT_PATH = BASE_PATH / "지역별 분석결과"
REPORT_PATH = BASE_PATH / "보고서"


@dataclass
class TargetFile:
    target: str
    file_path: Path


def list_candidates(query: str) -> List[Path]:
    candidates: List[Path] = []
    if BRANCH_RESULT_PATH.exists():
        candidates.extend([p for p in BRANCH_RESULT_PATH.rglob("*.shp") if query in str(p)])
    if REGION_RESULT_PATH.exists():
        candidates.extend([p for p in REGION_RESULT_PATH.rglob("*.shp") if query in str(p)])
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def pick_target(argv: List[str]) -> TargetFile:
    if len(argv) > 1:
        query = argv[1].strip()
    else:
        query = input("분석 대상 키워드(사업소/지역)를 입력하세요: ").strip()

    if not query:
        raise SystemExit("검색어가 비어 있습니다.")

    files = list_candidates(query)
    if not files:
        raise SystemExit(f"대상 파일을 찾지 못했습니다: {query}")

    return TargetFile(target=query, file_path=files[0])


def safe_col(df: pd.DataFrame, preferred: List[str]) -> str | None:
    for col in preferred:
        if col in df.columns:
            return col
    return None


def summarize(gdf: "gpd.GeoDataFrame") -> pd.DataFrame:
    fire_col = safe_col(gdf, ["화재점수", "fire_score", "FIRE_SCORE"])
    total_col = safe_col(gdf, ["종합점수", "total_score", "TOTAL_SCORE"])
    region_col = safe_col(gdf, ["시도", "region_nm", "REGION_NM"])

    df = pd.DataFrame()
    df["row_count"] = [len(gdf)]

    if fire_col:
        fire_events = (gdf[fire_col].fillna(0) > 0).sum()
        df["fire_events"] = [int(fire_events)]
        df["fire_rate_pct"] = [round(float(fire_events) * 100.0 / max(len(gdf), 1), 3)]

    if total_col:
        total = pd.to_numeric(gdf[total_col], errors="coerce")
        df["total_score_avg"] = [round(float(total.mean()), 3)]
        df["total_score_max"] = [round(float(total.max()), 3)]

    if region_col:
        top_regions = (
            gdf[region_col].fillna("UNKNOWN").astype(str).value_counts().head(10).to_dict()
        )
        df["top_regions"] = [", ".join([f"{k}:{v}" for k, v in top_regions.items()])]

    return df


def write_reports(target: TargetFile, summary_df: pd.DataFrame) -> None:
    REPORT_PATH.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

    txt_path = REPORT_PATH / f"분석보고서_{target.target}_{today}.txt"
    csv_path = REPORT_PATH / f"분석요약_{target.target}_{today}.csv"

    lines = [
        "=" * 80,
        f"자동 통계분석 보고서 - {target.target}",
        f"생성시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"입력파일: {target.file_path}",
        "=" * 80,
        "",
    ]
    for col in summary_df.columns:
        lines.append(f"- {col}: {summary_df.iloc[0][col]}")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    summary_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"TXT 저장: {txt_path}")
    print(f"CSV 저장: {csv_path}")


def main(argv: List[str]) -> None:
    target = pick_target(argv)

    try:
        gdf = gpd.read_file(target.file_path, encoding="cp949")
    except Exception:
        gdf = gpd.read_file(target.file_path, encoding="utf-8")

    summary_df = summarize(gdf)
    write_reports(target, summary_df)


if __name__ == "__main__":
    main(sys.argv)
