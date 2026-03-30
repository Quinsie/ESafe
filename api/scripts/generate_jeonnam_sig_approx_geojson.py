#!/usr/bin/env python3
"""Generate approximate Gwangju/Jeonnam district polygons from local building risk SQL.

This script does not try to reconstruct official administrative boundaries.
It creates visualization-friendly area polygons by:
1. Reading building coordinates from the local H2 full seed SQL.
2. Filtering target rows for Gwangju and Jeollanam-do.
3. Grouping buildings by `DISTRICT_NM`.
4. Snapping points to a coarse grid and unioning buffered cell centroids.
5. Writing a lightweight GeoJSON for OpenLayers consumption.

Input coordinates in the seed SQL are stored in EPSG:5186 meters.
The output GeoJSON is written in EPSG:4326.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from pyproj import Transformer
from shapely.geometry import MultiPoint, Point, mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "api/.local-seed/data-h2.full.sql"
DEFAULT_OUTPUT = ROOT / "api/src/main/webapp/resources/data/jeonnam-risk-area/jeonnam-sig-approx-risk.geojson"
TARGET_REGIONS = {"광주", "전남"}

FIELD_INDEX = {
    "regionNm": 5,
    "districtNm": 6,
    "regionCd": 7,
    "addr": 8,
    "lon": 9,
    "lat": 10,
    "totalScore": 24,
    "totalGrade": 25,
    "riskCd": 26,
}

SCORE_TO_RISK = (
    (80.0, "E"),
    (60.0, "D"),
    (40.0, "C"),
    (20.0, "B"),
    (-math.inf, "A"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to data-h2.full.sql")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="GeoJSON output path")
    parser.add_argument("--grid-size", type=float, default=320.0, help="Grid size in EPSG:5186 meters")
    parser.add_argument("--buffer-size", type=float, default=260.0, help="Cell buffer radius in meters")
    parser.add_argument("--smooth-buffer", type=float, default=140.0, help="Extra smoothing buffer in meters")
    parser.add_argument("--simplify", type=float, default=90.0, help="Simplify tolerance in meters")
    return parser.parse_args()


def split_sql_values(payload: str) -> List[str]:
    values: List[str] = []
    current: List[str] = []
    in_quote = False
    i = 0
    while i < len(payload):
        ch = payload[i]
        if ch == "'":
            current.append(ch)
            if i + 1 < len(payload) and payload[i + 1] == "'":
                current.append("'")
                i += 2
                continue
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    values.append("".join(current).strip())
    return values


def sql_string(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def sql_float(value: str) -> Optional[float]:
    value = sql_string(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def score_to_risk(score: float) -> str:
    for threshold, risk_cd in SCORE_TO_RISK:
        if score >= threshold:
            return risk_cd
    return "A"


def read_rows(sql_path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with sql_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if "INSERT INTO TB_BUILDING_RISK" not in line:
                continue
            values = split_sql_values(line.split("VALUES (", 1)[1].rsplit(");", 1)[0])
            region_nm = sql_string(values[FIELD_INDEX["regionNm"]])
            if region_nm not in TARGET_REGIONS:
                continue
            lon = sql_float(values[FIELD_INDEX["lon"]])
            lat = sql_float(values[FIELD_INDEX["lat"]])
            if lon is None or lat is None:
                continue
            district_nm = sql_string(values[FIELD_INDEX["districtNm"]]).strip()
            if not district_nm:
                continue
            score = sql_float(values[FIELD_INDEX["totalScore"]])
            rows.append({
                "regionNm": region_nm,
                "regionCd": sql_string(values[FIELD_INDEX["regionCd"]]).strip(),
                "districtNm": district_nm,
                "addr": sql_string(values[FIELD_INDEX["addr"]]).strip(),
                "lon": lon,
                "lat": lat,
                "totalScore": score if score is not None else 0.0,
                "riskCd": sql_string(values[FIELD_INDEX["riskCd"]]).strip(),
            })
    return rows


def build_geometry(points: Iterable[Point], grid_size: float, buffer_size: float, smooth_buffer: float, simplify_tolerance: float):
    occupied = set()
    for point in points:
        gx = int(round(point.x / grid_size))
        gy = int(round(point.y / grid_size))
        occupied.add((gx, gy))

    cell_buffers = [
        Point(gx * grid_size, gy * grid_size).buffer(buffer_size, quad_segs=4)
        for gx, gy in sorted(occupied)
    ]

    if not cell_buffers:
        return None

    geometry = unary_union(cell_buffers)
    if smooth_buffer > 0:
        geometry = geometry.buffer(smooth_buffer).buffer(-smooth_buffer * 0.78)

    geometry = geometry.simplify(simplify_tolerance, preserve_topology=True)
    if geometry.is_empty:
        multipoint = MultiPoint([Point(gx * grid_size, gy * grid_size) for gx, gy in sorted(occupied)])
        geometry = multipoint.convex_hull.buffer(buffer_size * 0.75)
    return geometry


def summarize_group(rows: List[Dict[str, object]]) -> Dict[str, object]:
    scores = [float(row["totalScore"]) for row in rows]
    risk_counts = Counter(str(row.get("riskCd") or "").upper() for row in rows)
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    max_score = round(max(scores), 2) if scores else 0.0
    raw_avg_risk_cd = score_to_risk(avg_score)
    dominant_risk = risk_counts.most_common(1)[0][0] if risk_counts else raw_avg_risk_cd
    return {
        "buildingCount": len(rows),
        "avgScore": avg_score,
        "maxScore": max_score,
        "dominantRiskCd": dominant_risk or raw_avg_risk_cd,
        "rawAvgRiskCd": raw_avg_risk_cd,
    }


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Input SQL not found: {args.input}")

    rows = read_rows(args.input)
    if not rows:
        raise RuntimeError("No Gwangju/Jeonnam rows found in the input SQL.")

    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["districtNm"])].append(row)

    to_wgs84 = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform
    features = []
    for district_nm in sorted(grouped.keys()):
        district_rows = grouped[district_nm]
        points = [Point(float(row["lon"]), float(row["lat"])) for row in district_rows]
        geometry = build_geometry(
            points=points,
            grid_size=args.grid_size,
            buffer_size=args.buffer_size,
            smooth_buffer=args.smooth_buffer,
            simplify_tolerance=args.simplify,
        )
        if geometry is None or geometry.is_empty:
            continue

        geometry_wgs84 = transform(to_wgs84, geometry)
        summary = summarize_group(district_rows)
        features.append({
            "type": "Feature",
            "properties": {
                "regionNm": district_rows[0]["regionNm"],
                "districtNm": district_nm,
                "districtKey": district_nm,
                "regionCd": district_rows[0]["regionCd"],
                **summary,
            },
            "geometry": mapping(geometry_wgs84),
        })

    avg_scores = [feature["properties"]["avgScore"] for feature in features]
    min_avg = min(avg_scores) if avg_scores else 0.0
    max_avg = max(avg_scores) if avg_scores else 0.0
    score_range = max_avg - min_avg
    for feature in features:
        props = feature["properties"]
        avg_score = props["avgScore"]
        if score_range <= 0:
            scaled_score = 50.0
        else:
            scaled_score = round(((avg_score - min_avg) / score_range) * 100.0, 2)
        props["avgScoreScaled"] = scaled_score
        props["styleRiskCd"] = score_to_risk(scaled_score)

    feature_collection = {
        "type": "FeatureCollection",
        "name": "gwangju_jeonnam_sig_approx_risk",
        "crs": {
            "type": "name",
            "properties": {
                "name": "EPSG:4326",
            },
        },
        "metadata": {
            "description": "Approximate Gwangju/Jeonnam district polygons derived from building point distribution for visualization.",
            "sourceSql": str(args.input.relative_to(ROOT)),
            "regionNames": sorted(TARGET_REGIONS),
            "featureCount": len(features),
        },
        "features": features,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feature_collection, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(features)} features to {args.output}")
    for feature in features:
        props = feature["properties"]
        print(
            f"{props['regionNm']} {props['districtNm']}: buildings={props['buildingCount']}, "
            f"avg={props['avgScore']}, max={props['maxScore']}, style={props['styleRiskCd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
