#!/usr/bin/env python3
"""Build a local risk-map polygon SHP that appends Jeongeup polygons.

The web risk-map polygon resolver matches building rows to SHP records by
`BLDG_SEQ - 1`. The local H2 seed appends Jeongeup rows after the existing
Gwangju/Jeonnam rows, so Jeongeup polygons must be appended to the same SHP
record order for polygon lookup to work without changing runtime code.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GWANGJU_BRANCH_DIR = PROJECT_ROOT / "사업소별 분석결과" / "광주전남본부" / "광주전남본부직할"
JEONGEUP_BRANCH_DIR = PROJECT_ROOT / "사업소별 분석결과" / "전북본부" / "전북서부지사"

GWANGJU_SOURCE = GWANGJU_BRANCH_DIR / "통합위험분석_광주전남본부직할_20260303.shp"
JEONGEUP_SOURCE = JEONGEUP_BRANCH_DIR / "통합위험분석_전북서부지사_20260423.shp"
OUTPUT = GWANGJU_BRANCH_DIR / "통합위험분석_광주전남본부직할_20260423.shp"


def read_geometry(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return gpd.read_file(path)[["geometry"]]


def main() -> None:
    gwangju = read_geometry(GWANGJU_SOURCE)
    jeongeup = read_geometry(JEONGEUP_SOURCE)

    if gwangju.crs != jeongeup.crs:
        jeongeup = jeongeup.to_crs(gwangju.crs)

    combined = gpd.GeoDataFrame(
        pd.concat([gwangju, jeongeup], ignore_index=True),
        geometry="geometry",
        crs=gwangju.crs,
    )
    combined.to_file(OUTPUT, encoding="utf-8")

    print(f"wrote: {OUTPUT}")
    print(f"gwangju_rows: {len(gwangju)}")
    print(f"jeongeup_rows: {len(jeongeup)}")
    print(f"combined_rows: {len(combined)}")


if __name__ == "__main__":
    main()
