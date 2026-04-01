#!/usr/bin/env python3
"""Generate approximate Gwangju/Jeonnam district polygons from local building risk SQL.

This script creates visualization-oriented polygons that:
- touch each other like puzzle pieces
- avoid gaps / overlaps inside the generated regional coverage
- follow district building distributions instead of exact administrative borders

Implementation strategy:
1. Read building risk rows from the local H2 full seed SQL.
2. Filter target rows for Gwangju and Jeollanam-do.
3. Build a tight regional mask from sampled real building points using
   concave hull + buffered point union.
4. Pick district Voronoi seeds from real building points (not grid buckets).
5. Generate a Voronoi coverage from those seeds.
6. Clip Voronoi cells to the regional mask and dissolve them by district.
7. Apply rounded smoothing and topology-preserving simplify for a soft blob look.

The result is not an official administrative boundary dataset.
It is a coverage-style visualization layer meant for map readability.

Input coordinates in the seed SQL are stored in EPSG:5186 meters.
Output GeoJSON is written in EPSG:4326.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from pyproj import Transformer
from scipy.spatial import Voronoi
from shapely import concave_hull, coverage_union_all
from shapely.geometry import GeometryCollection, MultiPoint, MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "api/.local-seed/data-h2.full.sql"
DEFAULT_OUTPUT = ROOT / "res/jeonnam-risk-area/jeonnam-sig-approx-risk.geojson"
DEFAULT_LINE_OUTPUT = ROOT / "res/jeonnam-risk-area/jeonnam-sig-approx-risk-internal-lines.geojson"
TARGET_REGIONS = {"광주", "전남"}

FIELD_INDEX = {
    "regionNm": 5,
    "districtNm": 6,
    "regionCd": 7,
    "addr": 8,
    "lon": 9,
    "lat": 10,
    "totalScore": 24,
    "riskCd": 26,
}

SCORE_TO_RISK = (
    (40.0, "E"),
    (30.0, "D"),
    (20.0, "C"),
    (10.0, "B"),
    (-math.inf, "A"),
)

RISK_TO_COLOR = {
    "A": "#1e934c",
    "B": "#215fd1",
    "C": "#d8b300",
    "D": "#ea7a19",
    "E": "#cf2f22",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to data-h2.full.sql")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="GeoJSON output path")
    parser.add_argument("--line-output", type=Path, default=DEFAULT_LINE_OUTPUT, help="Internal boundary GeoJSON output path")
    parser.add_argument("--seed-samples-min", type=int, default=18, help="Minimum Voronoi seed points per district")
    parser.add_argument("--seed-samples-max", type=int, default=90, help="Maximum Voronoi seed points per district")
    parser.add_argument("--mask-point-limit", type=int, default=14000, help="Maximum real building points sampled for the regional mask")
    parser.add_argument("--mask-point-buffer", type=float, default=260.0, help="Buffer radius for point-union mask generation in meters")
    parser.add_argument("--mask-buffer", type=float, default=650.0, help="Outer rounding buffer for the regional mask in meters")
    parser.add_argument("--mask-simplify", type=float, default=120.0, help="Simplify tolerance for the regional mask in meters")
    parser.add_argument("--hull-ratio", type=float, default=0.12, help="Concave hull ratio for the regional mask")
    parser.add_argument("--smooth-radius", type=float, default=180.0, help="Rounded smoothing radius for district polygons in meters")
    parser.add_argument("--boundary-simplify", type=float, default=30.0, help="Light topology-preserving simplify for dissolved district polygons")
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


def risk_to_color(risk_cd: str) -> str:
    return RISK_TO_COLOR.get(str(risk_cd or "").upper(), "#7d8794")


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
        "avgTotalScore": avg_score,
        "maxScore": max_score,
        "dominantRiskCd": dominant_risk or raw_avg_risk_cd,
        "rawAvgRiskCd": raw_avg_risk_cd,
        "avgTotalRiskCd": raw_avg_risk_cd,
        "fillColor": risk_to_color(raw_avg_risk_cd),
    }


def deterministic_pick(items: List[Dict[str, object]], limit: int) -> List[Dict[str, object]]:
    if len(items) <= limit:
        return list(items)
    if limit <= 0:
        return []

    ranked = sorted(
        items,
        key=lambda row: (
            float(row["totalScore"]),
            float(row["lon"]),
            float(row["lat"]),
            str(row["addr"]),
        ),
        reverse=True,
    )
    indexes = np.linspace(0, len(ranked) - 1, num=limit, dtype=int)
    seen = set()
    selected: List[Dict[str, object]] = []
    for idx in indexes:
        picked = ranked[int(idx)]
        key = (float(picked["lon"]), float(picked["lat"]), str(picked["districtNm"]))
        if key in seen:
            continue
        seen.add(key)
        selected.append(picked)
    return selected


def sample_voronoi_seeds(rows: List[Dict[str, object]], min_points: int, max_points: int) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["districtNm"])].append(row)

    sampled: List[Dict[str, object]] = []
    for district_nm, district_rows in grouped.items():
        size = len(district_rows)
        target = int(max(min_points, min(max_points, round(math.sqrt(size) * 1.45))))
        picked = deterministic_pick(district_rows, target)
        for row in picked:
            sampled.append({
                "regionNm": row["regionNm"],
                "regionCd": row["regionCd"],
                "districtNm": district_nm,
                "x": float(row["lon"]),
                "y": float(row["lat"]),
                "count": 1,
            })
    return sampled


def normalize_geometry(geometry):
    if geometry.is_empty:
        return geometry
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [geom for geom in geometry.geoms if isinstance(geom, (Polygon, MultiPolygon)) and not geom.is_empty]
        if not polygons:
            return geometry
        if len(polygons) == 1:
            return polygons[0]
        return coverage_union_all(polygons)
    return geometry


def remove_small_holes(geometry, min_hole_area: float):
    geometry = normalize_geometry(geometry)
    if geometry.is_empty:
        return geometry

    if isinstance(geometry, Polygon):
        kept_interiors = []
        for interior in geometry.interiors:
            hole = Polygon(interior)
            if hole.area >= min_hole_area:
                kept_interiors.append(interior.coords)
        return Polygon(geometry.exterior.coords, kept_interiors)

    if isinstance(geometry, MultiPolygon):
        polygons = [remove_small_holes(poly, min_hole_area) for poly in geometry.geoms]
        polygons = [poly for poly in polygons if not poly.is_empty]
        if not polygons:
            return geometry
        return MultiPolygon(polygons)

    return geometry


def collapse_to_primary_blob(geometry, smooth_radius: float):
    geometry = normalize_geometry(geometry)
    if geometry.is_empty:
        return geometry
    if isinstance(geometry, Polygon):
        return geometry
    if not isinstance(geometry, MultiPolygon):
        return geometry

    polygons = [poly for poly in geometry.geoms if not poly.is_empty]
    if not polygons:
        return geometry

    polygons.sort(key=lambda poly: poly.area, reverse=True)
    largest_area = polygons[0].area
    min_keep_area = max(1_500_000.0, largest_area * 0.18)
    kept = [poly for poly in polygons if poly.area >= min_keep_area]
    if not kept:
        kept = [polygons[0]]

    merged = unary_union(kept)
    if smooth_radius > 0:
        merged = merged.buffer(smooth_radius * 0.55, quad_segs=16).buffer(-smooth_radius * 0.55, quad_segs=16)
    merged = normalize_geometry(merged)

    if isinstance(merged, MultiPolygon):
        merged = max(merged.geoms, key=lambda poly: poly.area)
    return merged


def build_region_mask(
    rows: List[Dict[str, object]],
    hull_ratio: float,
    mask_point_limit: int,
    mask_point_buffer: float,
    mask_buffer: float,
    mask_simplify: float,
):
    mask_rows = deterministic_pick(rows, mask_point_limit)
    points = MultiPoint([Point(float(row["lon"]), float(row["lat"])) for row in mask_rows])
    hull = concave_hull(points, ratio=hull_ratio, allow_holes=False)
    if hull.is_empty:
        hull = points.convex_hull
    buffered_points = unary_union([pt.buffer(mask_point_buffer, quad_segs=16) for pt in points.geoms])
    mask = unary_union([hull, buffered_points])
    if mask.is_empty:
        mask = points.convex_hull
    if mask_buffer > 0:
        mask = mask.buffer(mask_buffer, quad_segs=16).buffer(-mask_buffer * 0.72, quad_segs=16)
    if mask_simplify > 0:
        mask = mask.simplify(mask_simplify, preserve_topology=True)
    return remove_small_holes(mask, min_hole_area=500000.0)


def unique_seed_coords(sampled_rows: List[Dict[str, object]]) -> np.ndarray:
    seen = set()
    coords = []
    epsilon = 0.001
    for idx, row in enumerate(sampled_rows):
        x = float(row["x"])
        y = float(row["y"])
        while (round(x, 3), round(y, 3)) in seen:
            x += epsilon * ((idx % 7) + 1)
            y += epsilon * ((idx % 11) + 1)
        seen.add((round(x, 3), round(y, 3)))
        row["x"] = x
        row["y"] = y
        coords.append((x, y))
    return np.asarray(coords, dtype=float)


def voronoi_finite_polygons_2d(vor: Voronoi, radius: Optional[float] = None):
    if vor.points.shape[1] != 2:
        raise ValueError("Requires 2D input")

    new_regions = []
    new_vertices = vor.vertices.tolist()
    center = vor.points.mean(axis=0)
    if radius is None:
        radius = vor.points.ptp().max() * 2

    all_ridges: Dict[int, List[Tuple[int, int, int]]] = defaultdict(list)
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        all_ridges[p1].append((p2, v1, v2))
        all_ridges[p2].append((p1, v1, v2))

    for p1, region_index in enumerate(vor.point_region):
        vertices = vor.regions[region_index]
        if all(v >= 0 for v in vertices):
            new_regions.append(vertices)
            continue

        ridges = all_ridges[p1]
        new_region = [v for v in vertices if v >= 0]
        for p2, v1, v2 in ridges:
            if v2 < 0:
                v1, v2 = v2, v1
            if v1 >= 0:
                continue

            tangent = vor.points[p2] - vor.points[p1]
            tangent /= np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]])
            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, normal)) * normal
            far_point = vor.vertices[v2] + direction * radius

            new_region.append(len(new_vertices))
            new_vertices.append(far_point.tolist())

        region_vertices = np.asarray([new_vertices[v] for v in new_region])
        region_center = region_vertices.mean(axis=0)
        angles = np.arctan2(region_vertices[:, 1] - region_center[1], region_vertices[:, 0] - region_center[0])
        new_region = [v for _, v in sorted(zip(angles, new_region))]
        new_regions.append(new_region)

    return new_regions, np.asarray(new_vertices)


def build_region_geometries(
    rows: List[Dict[str, object]],
    seed_samples_min: int,
    seed_samples_max: int,
    mask_point_limit: int,
    mask_point_buffer: float,
    hull_ratio: float,
    mask_buffer: float,
    mask_simplify: float,
    smooth_radius: float,
    boundary_simplify: float,
    exclusion_mask=None,
) -> Dict[str, object]:
    sampled_rows = sample_voronoi_seeds(rows, seed_samples_min, seed_samples_max)
    if len(sampled_rows) < 3:
        district_points: Dict[str, List[Point]] = defaultdict(list)
        for row in rows:
            district_points[str(row["districtNm"])].append(Point(float(row["lon"]), float(row["lat"])))
        fallback = {}
        for district_nm, points in district_points.items():
            hull = concave_hull(MultiPoint(points), ratio=0.08, allow_holes=False)
            if hull.is_empty:
                hull = MultiPoint(points).convex_hull
            hull = hull.buffer(max(smooth_radius, 120.0), quad_segs=16).buffer(-max(smooth_radius * 0.7, 90.0), quad_segs=16)
            if exclusion_mask is not None:
                hull = hull.difference(exclusion_mask)
            fallback[district_nm] = remove_small_holes(hull, min_hole_area=500000.0)
        return fallback

    mask = build_region_mask(rows, hull_ratio, mask_point_limit, mask_point_buffer, mask_buffer, mask_simplify)
    if exclusion_mask is not None:
        mask = normalize_geometry(mask.difference(exclusion_mask))
    if mask.is_empty:
        return {}
    coords = unique_seed_coords(sampled_rows)
    vor = Voronoi(coords)

    minx, miny, maxx, maxy = mask.bounds
    radius = max(maxx - minx, maxy - miny) * 3.0
    regions, vertices = voronoi_finite_polygons_2d(vor, radius=radius)
    clip_box = box(minx - radius * 0.05, miny - radius * 0.05, maxx + radius * 0.05, maxy + radius * 0.05)

    district_cells: Dict[str, List[Polygon]] = defaultdict(list)
    for idx, region in enumerate(regions):
        polygon = Polygon(vertices[region])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        polygon = polygon.intersection(clip_box).intersection(mask)
        polygon = normalize_geometry(polygon)
        if polygon.is_empty:
            continue
        district_nm = str(sampled_rows[idx]["districtNm"])
        district_cells[district_nm].append(polygon)

    district_geometries: Dict[str, object] = {}
    for district_nm, cells in district_cells.items():
        geometry = coverage_union_all(cells) if len(cells) > 1 else cells[0]
        geometry = normalize_geometry(geometry)
        if smooth_radius > 0:
            geometry = geometry.buffer(smooth_radius, quad_segs=16).buffer(-smooth_radius, quad_segs=16)
        if boundary_simplify > 0:
            geometry = geometry.simplify(boundary_simplify, preserve_topology=True)
        geometry = normalize_geometry(geometry).intersection(mask)
        geometry = remove_small_holes(normalize_geometry(geometry), min_hole_area=500000.0)
        geometry = collapse_to_primary_blob(geometry, smooth_radius)
        if not geometry.is_empty:
            district_geometries[district_nm] = geometry

    return district_geometries


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Input SQL not found: {args.input}")

    rows = read_rows(args.input)
    if not rows:
        raise RuntimeError("No Gwangju/Jeonnam rows found in the input SQL.")

    grouped_by_region: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    grouped_by_region_district: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        region_nm = str(row["regionNm"])
        district_nm = str(row["districtNm"])
        grouped_by_region[region_nm].append(row)
        grouped_by_region_district[(region_nm, district_nm)].append(row)

    to_wgs84 = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform
    features = []
    region_geometry_index: Dict[str, List[Tuple[str, object]]] = defaultdict(list)
    district_geometries_by_region: Dict[str, Dict[str, object]] = {}

    if "광주" in grouped_by_region:
        district_geometries_by_region["광주"] = build_region_geometries(
            rows=grouped_by_region["광주"],
            seed_samples_min=args.seed_samples_min,
            seed_samples_max=args.seed_samples_max,
            mask_point_limit=args.mask_point_limit,
            mask_point_buffer=args.mask_point_buffer,
            hull_ratio=args.hull_ratio,
            mask_buffer=args.mask_buffer,
            mask_simplify=args.mask_simplify,
            smooth_radius=args.smooth_radius,
            boundary_simplify=args.boundary_simplify,
        )

    gwangju_mask = None
    if district_geometries_by_region.get("광주"):
        gwangju_mask = unary_union(list(district_geometries_by_region["광주"].values()))

    if "전남" in grouped_by_region:
        district_geometries_by_region["전남"] = build_region_geometries(
            rows=grouped_by_region["전남"],
            seed_samples_min=args.seed_samples_min,
            seed_samples_max=args.seed_samples_max,
            mask_point_limit=args.mask_point_limit,
            mask_point_buffer=args.mask_point_buffer,
            hull_ratio=args.hull_ratio,
            mask_buffer=args.mask_buffer,
            mask_simplify=args.mask_simplify,
            smooth_radius=args.smooth_radius,
            boundary_simplify=args.boundary_simplify,
            exclusion_mask=gwangju_mask,
        )

    for region_nm in sorted(district_geometries_by_region.keys()):
        district_geometries = district_geometries_by_region[region_nm]
        for district_nm, geometry in sorted(district_geometries.items()):
            district_rows = grouped_by_region_district[(region_nm, district_nm)]
            region_geometry_index[region_nm].append((district_nm, geometry))
            geometry_wgs84 = transform(to_wgs84, geometry)
            summary = summarize_group(district_rows)
            features.append({
                "type": "Feature",
                "properties": {
                    "regionNm": region_nm,
                    "districtNm": district_nm,
                    "districtKey": district_nm,
                    "regionCd": district_rows[0]["regionCd"],
                    **summary,
                },
                "geometry": mapping(geometry_wgs84),
            })
    for feature in features:
        props = feature["properties"]
        props["styleRiskCd"] = props["avgTotalRiskCd"]

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
            "description": "Approximate Gwangju/Jeonnam district polygons derived from Voronoi coverage over sampled building points.",
            "sourceSql": str(args.input.relative_to(ROOT)),
            "regionNames": sorted(TARGET_REGIONS),
            "featureCount": len(features),
            "method": "voronoi-tight-mask-rounded",
        },
        "features": features,
    }

    line_features = []
    for region_nm, entries in sorted(region_geometry_index.items()):
        geometries = [geom for _, geom in entries]
        if not geometries:
            continue
        merged = unary_union(geometries)
        outer_boundary = merged.boundary
        all_boundaries = unary_union([geom.boundary for geom in geometries])
        internal = all_boundaries.difference(outer_boundary.buffer(0.000001))
        internal = normalize_geometry(internal)
        if internal.is_empty:
            pass
        else:
            internal_wgs84 = transform(to_wgs84, internal)
            line_features.append({
                "type": "Feature",
                "properties": {
                    "regionNm": region_nm,
                    "lineType": "internal-boundary",
                },
                "geometry": mapping(internal_wgs84),
            })

        if region_nm == "광주" and not outer_boundary.is_empty:
            outer_wgs84 = transform(to_wgs84, outer_boundary)
            line_features.append({
                "type": "Feature",
                "properties": {
                    "regionNm": region_nm,
                    "lineType": "outer-boundary",
                },
                "geometry": mapping(outer_wgs84),
            })

    line_collection = {
        "type": "FeatureCollection",
        "name": "gwangju_jeonnam_sig_approx_risk_internal_lines",
        "crs": {
            "type": "name",
            "properties": {
                "name": "EPSG:4326",
            },
        },
        "metadata": {
            "description": "Internal shared district boundaries only (outer boundary removed).",
            "sourceSql": str(args.input.relative_to(ROOT)),
            "regionNames": sorted(TARGET_REGIONS),
            "featureCount": len(line_features),
            "method": "voronoi-tight-mask-rounded-internal-lines",
        },
        "features": line_features,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feature_collection, ensure_ascii=False), encoding="utf-8")
    args.line_output.parent.mkdir(parents=True, exist_ok=True)
    args.line_output.write_text(json.dumps(line_collection, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(features)} features to {args.output}")
    print(f"Wrote {len(line_features)} internal line features to {args.line_output}")
    for feature in features:
        props = feature["properties"]
        print(
            f"{props['regionNm']} {props['districtNm']}: buildings={props['buildingCount']}, "
            f"avg={props['avgScore']}, max={props['maxScore']}, style={props['styleRiskCd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
