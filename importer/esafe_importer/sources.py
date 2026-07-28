from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapefile
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from esafe_importer.config import ImportConfig, read_json
from esafe_importer.domain import (
    EXPECTED_BUILDING_COUNT,
    building_uuid,
    facility_uuid,
    rank_risks,
    risk_uuid,
)

ATTR_FIELDS = [
    "A0",
    "A1",
    "A2",
    "A3",
    "A10",
    "A13",
    "A17",
    "A18",
    "A19",
    "A20",
    "A21",
    "A22",
    "A24",
    "건물연령",
    "건축년도",
    "지역코드",
    "용도코드",
    "용도명",
]
GEOMETRY_FIELDS = ["A0", "REGION", "DISTRICT", "ADDRESS"]


@dataclass(slots=True)
class SourceMetrics:
    duplicate_attribute_rows: int = 0
    repaired_building_geometries: int = 0
    risk_rows_outside_scope: int = 0
    invalid_facility_dates: int = 0
    admin_region_count: int = 0
    building_count: int = 0
    risk_count: int = 0
    facility_count: int = 0
    facility_link_count: int = 0
    collapsed_duplicate_legacy_links: int = 0
    boundary_centroid_mismatches: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "duplicate_attribute_rows": self.duplicate_attribute_rows,
            "repaired_building_geometries": self.repaired_building_geometries,
            "risk_rows_outside_scope": self.risk_rows_outside_scope,
            "invalid_facility_dates": self.invalid_facility_dates,
            "admin_region_count": self.admin_region_count,
            "building_count": self.building_count,
            "risk_count": self.risk_count,
            "facility_count": self.facility_count,
            "facility_link_count": self.facility_link_count,
            "collapsed_duplicate_legacy_links": self.collapsed_duplicate_legacy_links,
            "boundary_centroid_mismatches": self.boundary_centroid_mismatches,
        }


@dataclass(slots=True)
class ReferenceSource:
    config: ImportConfig
    metrics: SourceMetrics = field(default_factory=SourceMetrics)
    building_keys: set[str] = field(default_factory=set)
    facility_keys: set[str] = field(default_factory=set)
    legacy_building_key_map: dict[str, str] = field(default_factory=dict)

    @property
    def geometry_path(self) -> Path:
        return next(
            (self.config.source_root / "03_v27_1_hybrid_full_coverage_shapefile").glob(
                "*.shp"
            )
        )

    @property
    def attribute_path(self) -> Path:
        return next((self.config.source_root / "광주전남본부직할").glob("*.shp"))

    @property
    def risk_path(self) -> Path:
        return self.config.source_root / "test_60d_multistage_scores.parquet"

    @property
    def output_root(self) -> Path:
        return self.config.source_root / "output"

    def admin_regions(self) -> Iterator[tuple[Any, ...]]:
        collection = read_json(self.config.boundary_root / "admin_regions.geojson")
        features = collection.get("features")
        if not isinstance(features, list):
            raise ValueError("boundary GeoJSON has no feature list")
        seen: set[str] = set()
        for feature in features:
            properties = feature["properties"]
            region_code = str(properties["region_code"])
            if region_code in seen:
                raise ValueError(f"duplicate admin region: {region_code}")
            seen.add(region_code)
            geometry, _ = normalize_multipolygon(shape(feature["geometry"]))
            metadata = {
                "osm_type": properties.get("osm_type"),
                "osm_id": properties.get("osm_id"),
                "display_name": properties.get("display_name"),
                "licence": properties.get("licence"),
            }
            yield (
                region_code,
                str(properties["level"]),
                str(properties["name"]),
                str(properties["full_name"]),
                nullable_text(properties.get("parent_code")),
                geometry.wkb,
                str(properties["source"]),
                str(properties["source_version"]),
                compact_json(metadata),
            )
        self.metrics.admin_region_count = len(seen)

    def buildings(self) -> Iterator[tuple[Any, ...]]:
        attributes, duplicate_keys = self._load_attributes()
        transformer = Transformer.from_crs(5186, 4326, always_xy=True)
        reader = shapefile.Reader(
            str(self.geometry_path), encoding="utf-8", encodingErrors="strict"
        )
        seen: set[str] = set()
        for shape_record in reader.iterShapeRecords(fields=GEOMETRY_FIELDS):
            values = dict(zip(GEOMETRY_FIELDS, shape_record.record, strict=True))
            source_key = str(values["A0"])
            if source_key in seen:
                raise ValueError(f"duplicate building geometry key: {source_key}")
            attribute = attributes.get(source_key)
            if attribute is None:
                raise ValueError(f"missing building attribute row: {source_key}")
            region_code = normalized_code(attribute["지역코드"])
            geometry, repaired = normalize_multipolygon(
                shape(shape_record.shape.__geo_interface__)
            )
            geometry = transform(transformer.transform, geometry)
            geometry, repaired_after_transform = normalize_multipolygon(geometry)
            repaired = repaired or repaired_after_transform
            if not bounds_within_wgs84(geometry):
                raise ValueError(
                    f"building geometry outside WGS84 bounds: {source_key}"
                )
            quality_flags: list[str] = []
            if source_key in duplicate_keys:
                quality_flags.append("DUPLICATE_IDENTICAL_ATTRIBUTE_ROW")
            if repaired:
                quality_flags.append("GEOMETRY_REPAIRED")
                self.metrics.repaired_building_geometries += 1
            customer_data = build_customer_data(attribute)
            lot_address = nullable_text(values.get("ADDRESS"))
            if lot_address is None:
                raise ValueError(f"building lot address is missing: {source_key}")
            yield (
                building_uuid(source_key),
                source_key,
                region_code,
                None,
                lot_address,
                nullable_text(attribute.get("A13")),
                geometry.wkb,
                compact_json(customer_data),
                self.config.import_id,
                compact_json(quality_flags),
            )
            seen.add(source_key)
        if len(seen) != EXPECTED_BUILDING_COUNT:
            raise ValueError(f"unexpected building count: {len(seen)}")
        if set(attributes) != seen:
            raise ValueError("building attribute and geometry key sets differ")
        self.building_keys = seen
        self.metrics.building_count = len(seen)

    def risks(self) -> Iterator[tuple[Any, ...]]:
        if len(self.building_keys) != EXPECTED_BUILDING_COUNT:
            raise RuntimeError("buildings must be read before risks")
        table = pq.read_table(
            self.risk_path,
            columns=["snapshot_month", "bldg_seq", "final_score"],
            filters=[("snapshot_month", "=", "2026-03")],
        )
        table = table.filter(pc.equal(table["snapshot_month"], "2026-03"))
        keys = table["bldg_seq"].to_pylist()
        values = table["final_score"].to_pylist()
        scores: dict[str, float] = {}
        outside_scope = 0
        for raw_key, raw_score in zip(keys, values, strict=True):
            source_key = str(raw_key)
            if source_key not in self.building_keys:
                outside_scope += 1
                continue
            if source_key in scores:
                raise ValueError(f"duplicate March risk score: {source_key}")
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError(f"non-finite March risk score: {source_key}")
            scores[source_key] = score
        if set(scores) != self.building_keys:
            missing = len(self.building_keys - set(scores))
            raise ValueError(f"March risk score missing for {missing} buildings")
        self.metrics.risk_rows_outside_scope = outside_scope
        for row in rank_risks(scores):
            yield (
                risk_uuid(row.source_building_key),
                building_uuid(row.source_building_key),
                row.score,
                row.rank,
                row.top_percentile,
                row.band,
            )
        self.metrics.risk_count = len(scores)

    def facilities(self) -> Iterator[tuple[Any, ...]]:
        path = self.output_root / "source_entity_seed.csv"
        count = 0
        seen: set[str] = set()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "source_key",
                "source_type",
                "source_addr",
                "source_addr_norm",
                "customer_no",
                "branch_nm",
                "biz_nm",
                "general_building_type",
                "general_contract_type",
                "self_building_no",
                "self_asset_no",
                "source_use_class",
                "row_count",
                "first_date",
                "last_date",
                "candidate_count",
                "match_status",
            }
            if set(reader.fieldnames or []) != required:
                raise ValueError("facility source CSV header mismatch")
            for row in reader:
                if None in row:
                    raise ValueError(
                        f"malformed facility source CSV row: {reader.line_num}"
                    )
                source_key = row["source_key"]
                if source_key in seen:
                    raise ValueError(f"duplicate facility source key: {source_key}")
                flags: list[str] = []
                first_date = parse_optional_date(row["first_date"], flags)
                last_date = parse_optional_date(row["last_date"], flags)
                if flags:
                    self.metrics.invalid_facility_dates += 1
                yield (
                    facility_uuid(source_key),
                    source_key,
                    row["source_type"],
                    nullable_text(row["source_addr"]),
                    nullable_text(row["source_addr_norm"]),
                    nullable_text(row["customer_no"]),
                    nullable_text(row["branch_nm"]),
                    nullable_text(row["biz_nm"]),
                    nullable_text(row["general_building_type"]),
                    nullable_text(row["general_contract_type"]),
                    nullable_text(row["self_building_no"]),
                    nullable_text(row["self_asset_no"]),
                    nullable_text(row["source_use_class"]),
                    int(row["row_count"]),
                    first_date,
                    last_date,
                    int(row["candidate_count"]),
                    row["match_status"],
                    self.config.import_id,
                    compact_json(flags),
                )
                seen.add(source_key)
                count += 1
        if count != 948_464:
            raise ValueError(f"unexpected facility entity count: {count}")
        self.facility_keys = seen
        self.metrics.facility_count = count

    def facility_links(self) -> Iterator[tuple[Any, ...]]:
        if (
            not self.facility_keys
            or not self.building_keys
            or not self.legacy_building_key_map
        ):
            raise RuntimeError(
                "facilities and buildings must be read before facility links"
            )
        path = self.output_root / "source_entity_building_map.csv"
        raw_count = 0
        best_candidates: dict[tuple[str, str], tuple[Any, ...]] = {}
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                if None in row:
                    raise ValueError(
                        f"malformed facility link CSV row: {reader.line_num}"
                    )
                source_key = row["source_key"]
                legacy_building_key = row["bldg_seq"]
                building_key = self.legacy_building_key_map.get(legacy_building_key)
                if source_key not in self.facility_keys:
                    raise ValueError(f"facility link has unknown source: {source_key}")
                if building_key is None or building_key not in self.building_keys:
                    raise ValueError(
                        f"facility link has unknown legacy building: {legacy_building_key}"
                    )
                original_rank = int(row["candidate_rank"])
                score_text = nullable_text(row["candidate_score"])
                candidate = (
                    source_key,
                    building_key,
                    original_rank,
                    float(score_text) if score_text is not None else None,
                    nullable_text(row["match_kind"]),
                    nullable_text(row["source_use_class"]),
                    nullable_text(row["building_use_class"]),
                    nullable_text(row["score_detail"]),
                )
                pair = (source_key, building_key)
                previous = best_candidates.get(pair)
                if previous is None or original_rank < int(previous[2]):
                    best_candidates[pair] = candidate
                raw_count += 1
        if raw_count != 1_678_473:
            raise ValueError(f"unexpected raw facility link count: {raw_count}")
        collapsed = raw_count - len(best_candidates)
        candidate_counts: dict[str, int] = {}
        for source_key, _building_key in best_candidates:
            candidate_counts[source_key] = candidate_counts.get(source_key, 0) + 1
        previous_source: str | None = None
        canonical_rank = 0
        ordered = sorted(
            best_candidates.values(),
            key=lambda row: (str(row[0]), int(row[2]), int(str(row[1]))),
        )
        for candidate in ordered:
            source_key = str(candidate[0])
            building_key = str(candidate[1])
            if source_key != previous_source:
                previous_source = source_key
                canonical_rank = 0
            canonical_rank += 1
            yield (
                facility_uuid(source_key),
                building_uuid(building_key),
                candidate_counts[source_key],
                canonical_rank,
                candidate[3],
                candidate[4],
                candidate[5],
                candidate[6],
                candidate[7],
                self.config.import_id,
            )
        self.metrics.collapsed_duplicate_legacy_links = collapsed
        self.metrics.facility_link_count = len(best_candidates)

    def _load_attributes(self) -> tuple[dict[str, dict[str, Any]], set[str]]:
        reader = shapefile.Reader(
            str(self.attribute_path), encoding="cp949", encodingErrors="strict"
        )
        attributes: dict[str, dict[str, Any]] = {}
        duplicate_keys: set[str] = set()
        for legacy_index, record in enumerate(
            reader.iterRecords(fields=ATTR_FIELDS), start=1
        ):
            row = dict(zip(ATTR_FIELDS, record, strict=True))
            source_key = str(row["A0"])
            self.legacy_building_key_map[str(legacy_index)] = source_key
            previous = attributes.get(source_key)
            if previous is not None:
                if previous != row:
                    raise ValueError(
                        f"conflicting duplicate building attribute: {source_key}"
                    )
                duplicate_keys.add(source_key)
                self.metrics.duplicate_attribute_rows += 1
                continue
            attributes[source_key] = row
        return attributes, duplicate_keys


def build_customer_data(attribute: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "building_register_key": "A1",
        "land_key": "A2",
        "legal_dong_code": "A3",
        "register_type": "A10",
        "main_structure": "A17",
        "main_use_code": "A18",
        "main_use_name": "A19",
        "gross_floor_area_m2": "A20",
        "floors_above": "A21",
        "floors_below": "A22",
        "approval_date": "A24",
        "building_age": "건물연령",
        "building_year": "건축년도",
        "land_use_code": "용도코드",
        "land_use_name": "용도명",
    }
    return {
        target: attribute[source]
        for target, source in fields.items()
        if attribute.get(source) not in (None, "")
    }


def normalize_multipolygon(geometry: BaseGeometry) -> tuple[MultiPolygon, bool]:
    repaired = False
    if geometry.is_empty:
        raise ValueError("empty polygon geometry")
    if not geometry.is_valid:
        geometry = make_valid(geometry)
        repaired = True
    polygons = collect_polygons(geometry)
    if not polygons:
        raise ValueError(f"geometry contains no polygon: {geometry.geom_type}")
    result = MultiPolygon(polygons)
    if not result.is_valid:
        result = make_valid(result)
        repaired = True
        polygons = collect_polygons(result)
        result = MultiPolygon(polygons)
    if result.is_empty or not result.is_valid:
        raise ValueError("unable to create a valid multipolygon")
    return result, repaired


def collect_polygons(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [
            polygon for part in geometry.geoms for polygon in collect_polygons(part)
        ]
    return []


def normalized_code(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def parse_optional_date(value: str, flags: list[str]) -> date | None:
    text = value.strip()
    if not text:
        return None
    candidates = [text[:10], text]
    if len(text) == 8 and text.isdigit():
        candidates.insert(0, f"{text[:4]}-{text[4:6]}-{text[6:]}")
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    flags.append("INVALID_INSPECTION_DATE")
    return None


def bounds_within_wgs84(geometry: BaseGeometry) -> bool:
    minimum_x, minimum_y, maximum_x, maximum_y = geometry.bounds
    return -180 <= minimum_x <= maximum_x <= 180 and -90 <= minimum_y <= maximum_y <= 90
