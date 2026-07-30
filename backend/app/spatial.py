# ruff: noqa: E501
import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REFERENCE_MONTH = "2026-03-01"
HORIZON_DAYS = 60
LINEAGE_VERSION = "v27.1-focus-2026-03-60d"
MIN_BUILDING_ZOOM = 16
MAX_BUILDING_ZOOM = 20
MIN_NEIGHBORHOOD_ZOOM = 11.5
MAX_NEIGHBORHOOD_SPAN = 1.5
_MAX_VIEWPORT_SPAN = 0.35
_RISK_BANDS = frozenset({"TOP_1", "HIGH_1_10", "WATCH_10_25", "GENERAL"})


def _risk_reference() -> dict[str, Any]:
    return {
        "referenceMonth": "2026-03",
        "horizonDays": HORIZON_DAYS,
        "lineageVersion": LINEAGE_VERSION,
        "isProbability": False,
    }


@dataclass(frozen=True)
class SpatialContractError(Exception):
    status_code: int
    code: str
    message: str


@dataclass(frozen=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float


def _parse_bbox_coordinates(value: str) -> BoundingBox:
    try:
        values = [float(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise SpatialContractError(422, "INVALID_BBOX", "지도 범위 형식이 올바르지 않습니다.") from exc
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        raise SpatialContractError(422, "INVALID_BBOX", "지도 범위는 네 개의 유한한 좌표여야 합니다.")
    west, south, east, north = values
    if west >= east or south >= north or not (-180 <= west <= 180 and -90 <= south <= 90):
        raise SpatialContractError(422, "INVALID_BBOX", "지도 범위의 좌표 순서를 확인해 주세요.")
    return BoundingBox(west, south, east, north)


def parse_region_bbox(value: str) -> BoundingBox:
    parsed = _parse_bbox_coordinates(value)
    if parsed.east - parsed.west > MAX_NEIGHBORHOOD_SPAN or parsed.north - parsed.south > MAX_NEIGHBORHOOD_SPAN:
        raise SpatialContractError(422, "VIEWPORT_TOO_LARGE", "읍·면·동 조회 범위가 너무 큽니다. 지도를 더 확대해 주세요.")
    return parsed


def parse_bbox(value: str, zoom: float) -> BoundingBox:
    parsed = _parse_bbox_coordinates(value)
    if zoom < MIN_BUILDING_ZOOM:
        raise SpatialContractError(
            422,
            "BUILDING_ZOOM_REQUIRED",
            f"건물 조회는 확대수준 {MIN_BUILDING_ZOOM} 이상에서 사용할 수 있습니다.",
        )
    if parsed.east - parsed.west > _MAX_VIEWPORT_SPAN or parsed.north - parsed.south > _MAX_VIEWPORT_SPAN:
        raise SpatialContractError(
            422,
            "VIEWPORT_TOO_LARGE",
            "건물 조회 범위가 너무 큽니다. 지도를 더 확대해 주세요.",
        )
    return parsed


def _geojson(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("GeoJSON object expected")
    return parsed


def _risk(row: Any) -> dict[str, Any]:
    return {
        "referenceMonth": "2026-03",
        "horizonDays": HORIZON_DAYS,
        "lineageVersion": LINEAGE_VERSION,
        "finalScore": float(row["final_score"]),
        "regionalRank": int(row["regional_rank"]),
        "topPercentile": float(row["top_percentile"]),
        "riskBand": row["risk_band"],
        "isProbability": False,
    }


async def region_features(
    engine: AsyncEngine,
    level: Literal["SIDO", "SIGUNGU", "EUPMYEONDONG"],
    parent_code: str | None,
    timeout_seconds: float,
    bbox: BoundingBox | None = None,
) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT a.region_code, a.level, a.name, a.full_name, a.parent_code,
                               ST_AsGeoJSON(ST_SimplifyPreserveTopology(
                                   a.geometry, CASE a.level WHEN 'SIDO' THEN 0.001 WHEN 'SIGUNGU' THEN 0.00025 ELSE 0.00004 END
                               ), 6) AS geometry,
                               ARRAY[ST_XMin(Box3D(a.geometry)), ST_YMin(Box3D(a.geometry)), ST_XMax(Box3D(a.geometry)), ST_YMax(Box3D(a.geometry))] AS bounds,
                               ST_X(a.centroid) AS center_lng, ST_Y(a.centroid) AS center_lat,
                               r.building_count, r.top_1_count, r.high_1_10_count,
                               r.watch_10_25_count, r.general_count, r.top_10_count,
                               r.score_median, r.score_p90, r.score_p99, r.score_max,
                               coalesce(c.active_case_count, 0) AS active_case_count,
                               coalesce(c.urgent_case_count, 0) AS urgent_case_count,
                               r.calculated_at
                        FROM admin_region a
                        LEFT JOIN region_risk_summary r
                          ON r.region_code = a.region_code
                         AND r.reference_month = DATE '2026-03-01'
                         AND r.horizon_days = 60
                         AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS active_case_count,
                                   count(*) FILTER (WHERE monitoring_priority = 'URGENT') AS urgent_case_count
                            FROM case_record c
                            WHERE (
                                (a.level = 'EUPMYEONDONG' AND c.location IS NOT NULL AND ST_Covers(a.geometry, c.location))
                                OR (a.level <> 'EUPMYEONDONG' AND c.primary_region_code = a.region_code)
                              )
                              AND status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                        ) c ON true
                        WHERE a.level = :level
                          AND (CAST(:parent_code AS varchar) IS NULL OR a.parent_code = CAST(:parent_code AS varchar))
                          AND (CAST(:west AS double precision) IS NULL OR a.geometry && ST_MakeEnvelope(:west, :south, :east, :north, 4326))
                          AND EXISTS (SELECT 1 FROM reference_dataset_state WHERE state_id = true)
                        ORDER BY a.region_code
                        """
                    ),
                    {
                        "level": level,
                        "parent_code": parent_code,
                        "west": bbox.west if bbox else None,
                        "south": bbox.south if bbox else None,
                        "east": bbox.east if bbox else None,
                        "north": bbox.north if bbox else None,
                    },
                )
            ).mappings().all()
        features = []
        for row in rows:
            properties = {
                "regionCode": row["region_code"],
                "level": row["level"],
                "name": row["name"],
                "fullName": row["full_name"],
                "parentCode": row["parent_code"],
                "center": [float(row["center_lng"]), float(row["center_lat"])],
                "buildingCount": int(row["building_count"] or 0),
                "top1Count": int(row["top_1_count"] or 0),
                "top10Count": int(row["top_10_count"] or 0),
                "riskBands": {
                    "top1": int(row["top_1_count"] or 0),
                    "high1To10": int(row["high_1_10_count"] or 0),
                    "watch10To25": int(row["watch_10_25_count"] or 0),
                    "general": int(row["general_count"] or 0),
                },
                "scoreMedian": float(row["score_median"]) if row["score_median"] is not None else None,
                "scoreP90": float(row["score_p90"]) if row["score_p90"] is not None else None,
                "scoreP99": float(row["score_p99"]) if row["score_p99"] is not None else None,
                "scoreMax": float(row["score_max"]) if row["score_max"] is not None else None,
                "activeCaseCount": int(row["active_case_count"]),
                "urgentCaseCount": int(row["urgent_case_count"]),
                "hasCurrentSignal": int(row["active_case_count"]) > 0,
            }
            features.append(
                {
                    "type": "Feature",
                    "id": row["region_code"],
                    "bbox": [float(item) for item in row["bounds"]],
                    "geometry": _geojson(row["geometry"]),
                    "properties": properties,
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
            "riskReference": {
                "referenceMonth": "2026-03",
                "horizonDays": HORIZON_DAYS,
                "lineageVersion": LINEAGE_VERSION,
                "isProbability": False,
            },
        }

    return await asyncio.wait_for(query(), timeout=timeout_seconds)


async def building_tile(
    engine: AsyncEngine,
    z: int,
    x: int,
    y: int,
    timeout_seconds: float,
) -> bytes:
    if z < MIN_BUILDING_ZOOM or z > MAX_BUILDING_ZOOM:
        raise SpatialContractError(
            422,
            "BUILDING_ZOOM_REQUIRED",
            f"건물 타일은 확대수준 {MIN_BUILDING_ZOOM}~{MAX_BUILDING_ZOOM}에서 제공합니다.",
        )
    tile_count = 1 << z
    if x < 0 or y < 0 or x >= tile_count or y >= tile_count:
        raise SpatialContractError(422, "INVALID_TILE", "지도 타일 좌표가 올바르지 않습니다.")

    async def query() -> bytes:
        async with engine.connect() as connection:
            value = (
                await connection.execute(
                    text(
                        """
                        WITH bounds AS (
                            SELECT ST_TileEnvelope(:z, :x, :y) AS envelope_3857,
                                   ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS envelope_4326
                        ), tile_rows AS (
                            SELECT b.building_id::text AS building_id,
                                   b.region_code,
                                   coalesce(nullif(b.building_name, ''), b.lot_address) AS label,
                                   r.final_score,
                                   r.regional_rank,
                                   r.top_percentile,
                                   r.risk_band,
                                   EXISTS (
                                       SELECT 1 FROM case_record c
                                       WHERE c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                                         AND c.location IS NOT NULL
                                         AND ST_DWithin(c.location::geography, b.centroid::geography, 100)
                                   ) AS has_current_signal,
                                   ST_AsMVTGeom(
                                       ST_Transform(b.geometry, 3857), bounds.envelope_3857, 4096, 64, true
                                   ) AS geom
                            FROM building b
                            JOIN building_risk_snapshot r ON r.building_id = b.building_id
                            CROSS JOIN bounds
                            WHERE b.geometry_status = 'VALID'
                              AND b.geometry && bounds.envelope_4326
                              AND ST_Intersects(b.geometry, bounds.envelope_4326)
                              AND r.reference_month = DATE '2026-03-01'
                              AND r.horizon_days = 60
                              AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                              AND EXISTS (SELECT 1 FROM reference_dataset_state WHERE state_id = true)
                        )
                        SELECT ST_AsMVT(tile_rows, 'buildings', 4096, 'geom') FROM tile_rows
                        """
                    ),
                    {"z": z, "x": x, "y": y},
                )
            ).scalar_one()
        return bytes(value or b"")

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))


async def building_features(
    engine: AsyncEngine,
    bbox: BoundingBox,
    zoom: float,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    params = {
        "west": bbox.west,
        "south": bbox.south,
        "east": bbox.east,
        "north": bbox.north,
        "zoom": zoom,
        "limit": limit + 1,
    }

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT b.building_id, b.region_code,
                               coalesce(nullif(b.building_name, ''), b.lot_address) AS label,
                               ST_AsGeoJSON(
                                   ST_SimplifyPreserveTopology(
                                       b.geometry,
                                       CASE WHEN :zoom >= 17 THEN 0.000001 ELSE 0.000003 END
                                   ),
                                   7
                               ) AS geometry,
                               r.final_score, r.regional_rank, r.top_percentile, r.risk_band
                        FROM building b
                        JOIN building_risk_snapshot r ON r.building_id = b.building_id
                        WHERE b.geometry_status = 'VALID'
                          AND b.geometry && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
                          AND ST_Intersects(
                              b.geometry,
                              ST_MakeEnvelope(:west, :south, :east, :north, 4326)
                          )
                          AND r.reference_month = DATE '2026-03-01'
                          AND r.horizon_days = 60
                          AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                          AND EXISTS (SELECT 1 FROM reference_dataset_state WHERE state_id = true)
                        ORDER BY r.regional_rank, b.building_id
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).mappings().all()
        truncated = len(rows) > limit
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": str(row["building_id"]),
                    "geometry": _geojson(row["geometry"]),
                    "properties": {
                        "buildingId": str(row["building_id"]),
                        "regionCode": row["region_code"],
                        "label": row["label"],
                        "finalScore": float(row["final_score"]),
                        "regionalRank": int(row["regional_rank"]),
                        "topPercentile": float(row["top_percentile"]),
                        "riskBand": row["risk_band"],
                    },
                }
                for row in rows[:limit]
            ],
            "truncated": truncated,
            "limit": limit,
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))


async def viewport_buildings(
    engine: AsyncEngine,
    bbox: BoundingBox,
    page: int,
    page_size: int,
    risk_band: str | None,
    sort: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if risk_band is not None and risk_band not in _RISK_BANDS:
        raise SpatialContractError(422, "INVALID_RISK_BAND", "위험구간 필터가 올바르지 않습니다.")
    order_by = {
        "rank": "r.regional_rank ASC, b.building_id",
        "score": "r.final_score DESC, b.building_id",
        "name": "coalesce(nullif(b.building_name, ''), b.lot_address), b.building_id",
    }.get(sort)
    if order_by is None:
        raise SpatialContractError(422, "INVALID_SORT", "건물 정렬값이 올바르지 않습니다.")
    params = {
        "west": bbox.west,
        "south": bbox.south,
        "east": bbox.east,
        "north": bbox.north,
        "risk_band": risk_band,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    async def query() -> dict[str, Any]:
        filter_sql = """
            b.geometry_status = 'VALID'
            AND b.centroid && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
            AND r.reference_month = DATE '2026-03-01'
            AND r.horizon_days = 60
            AND r.lineage_version = 'v27.1-focus-2026-03-60d'
            AND (CAST(:risk_band AS varchar) IS NULL OR r.risk_band = CAST(:risk_band AS varchar))
        """
        async with engine.connect() as connection:
            total = int(
                (
                    await connection.execute(
                        text(
                            f"""SELECT count(*) FROM building b
                            JOIN building_risk_snapshot r ON r.building_id = b.building_id
                            WHERE {filter_sql}"""
                        ),
                        params,
                    )
                ).scalar_one()
            )
            rows = (
                await connection.execute(
                    text(
                        f"""
                        SELECT b.building_id, b.region_code, b.building_name,
                               b.road_address, b.lot_address,
                               ST_X(b.centroid) AS lng, ST_Y(b.centroid) AS lat,
                               r.final_score, r.regional_rank, r.top_percentile, r.risk_band
                        FROM building b
                        JOIN building_risk_snapshot r ON r.building_id = b.building_id
                        WHERE {filter_sql}
                        ORDER BY {order_by}
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    params,
                )
            ).mappings().all()
        return {
            "items": [
                {
                    "buildingId": str(row["building_id"]),
                    "regionCode": row["region_code"],
                    "name": row["building_name"] or "건물명 미등록",
                    "roadAddress": row["road_address"],
                    "lotAddress": row["lot_address"],
                    "center": [float(row["lng"]), float(row["lat"])],
                    "risk": _risk(row),
                    "hasCurrentSignal": False,
                    "monitoringPriority": "NORMAL",
                }
                for row in rows
            ],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": math.ceil(total / page_size) if total else 0,
            },
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))


async def risk_rankings(
    engine: AsyncEngine,
    level: Literal["SIDO", "SIGUNGU", "EUPMYEONDONG", "BUILDING"],
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        params = {"level": level, "limit": page_size, "offset": (page - 1) * page_size}
        async with engine.connect() as connection:
            if level == "BUILDING":
                total = int(
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT count(*)
                                FROM building_risk_snapshot
                                WHERE reference_month = DATE '2026-03-01'
                                  AND horizon_days = 60
                                  AND lineage_version = 'v27.1-focus-2026-03-60d'
                                """
                            )
                        )
                    ).scalar_one()
                )
                rows = (
                    await connection.execute(
                        text(
                            """
                            SELECT b.building_id AS entity_id,
                                   coalesce(nullif(b.building_name, ''), b.lot_address) AS name,
                                   coalesce(b.road_address, b.lot_address) AS full_name,
                                   a.full_name AS region_name,
                                   r.final_score, r.regional_rank,
                                   r.top_percentile, r.risk_band
                            FROM building_risk_snapshot r
                            JOIN building b ON b.building_id = r.building_id
                            JOIN admin_region a ON a.region_code = b.region_code
                            WHERE r.reference_month = DATE '2026-03-01'
                              AND r.horizon_days = 60
                              AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                            ORDER BY r.regional_rank, b.building_id
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        params,
                    )
                ).mappings().all()
                items = [
                    {
                        "entityType": "BUILDING",
                        "entityId": str(row["entity_id"]),
                        "level": "BUILDING",
                        "name": row["name"],
                        "fullName": row["full_name"],
                        "regionName": row["region_name"],
                        "rankingPosition": int(row["regional_rank"]),
                        "buildingCount": 1,
                        "top1Count": 1 if row["risk_band"] == "TOP_1" else 0,
                        "top10Count": (
                            1 if float(row["top_percentile"]) <= 10 else 0
                        ),
                        "top10Share": (
                            100.0 if float(row["top_percentile"]) <= 10 else 0.0
                        ),
                        "scoreP99": float(row["final_score"]),
                        "finalScore": float(row["final_score"]),
                        "topPercentile": float(row["top_percentile"]),
                        "riskBand": row["risk_band"],
                    }
                    for row in rows
                ]
            else:
                total = int(
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT count(*)
                                FROM region_risk_summary r
                                JOIN admin_region a ON a.region_code = r.region_code
                                WHERE a.level = :level
                                  AND r.reference_month = DATE '2026-03-01'
                                  AND r.horizon_days = 60
                                  AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                                """
                            ),
                            params,
                        )
                    ).scalar_one()
                )
                rows = (
                    await connection.execute(
                        text(
                            """
                            SELECT a.region_code AS entity_id, a.name, a.full_name,
                                   r.building_count, r.top_1_count, r.top_10_count,
                                   r.score_p99,
                                   row_number() OVER (
                                     ORDER BY r.top_10_count DESC, a.region_code
                                   ) AS ranking_position
                            FROM region_risk_summary r
                            JOIN admin_region a ON a.region_code = r.region_code
                            WHERE a.level = :level
                              AND r.reference_month = DATE '2026-03-01'
                              AND r.horizon_days = 60
                              AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                            ORDER BY r.top_10_count DESC, a.region_code
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        params,
                    )
                ).mappings().all()
                items = [
                    {
                        "entityType": "REGION",
                        "entityId": row["entity_id"],
                        "level": level,
                        "name": row["name"],
                        "fullName": row["full_name"],
                        "regionName": row["full_name"],
                        "rankingPosition": int(row["ranking_position"]),
                        "buildingCount": int(row["building_count"]),
                        "top1Count": int(row["top_1_count"]),
                        "top10Count": int(row["top_10_count"]),
                        "top10Share": round(
                            int(row["top_10_count"])
                            / max(1, int(row["building_count"]))
                            * 100,
                            2,
                        ),
                        "scoreP99": (
                            float(row["score_p99"])
                            if row["score_p99"] is not None
                            else None
                        ),
                        "finalScore": None,
                        "topPercentile": None,
                        "riskBand": None,
                    }
                    for row in rows
                ]
        return {
            "level": level,
            "rankingBasis": (
                "GWANGJU_JEONNAM_REGIONAL_RANK"
                if level == "BUILDING"
                else "TOP_10_BUILDING_COUNT"
            ),
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": math.ceil(total / page_size) if total else 0,
            },
            "riskReference": _risk_reference(),
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))


async def region_detail(
    engine: AsyncEngine,
    region_code: str,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT a.region_code, a.level, a.name, a.full_name, a.parent_code,
                               p.full_name AS parent_name,
                               ST_AsGeoJSON(a.geometry, 7) AS geometry,
                               ARRAY[ST_XMin(Box3D(a.geometry)), ST_YMin(Box3D(a.geometry)), ST_XMax(Box3D(a.geometry)), ST_YMax(Box3D(a.geometry))] AS bounds,
                               ST_X(a.centroid) AS center_lng, ST_Y(a.centroid) AS center_lat,
                               r.building_count, r.top_1_count, r.high_1_10_count,
                               r.watch_10_25_count, r.general_count, r.top_10_count,
                               r.score_min, r.score_median, r.score_p90, r.score_p99, r.score_max,
                               r.calculated_at,
                               coalesce(c.active_case_count, 0) AS active_case_count,
                               coalesce(c.urgent_case_count, 0) AS urgent_case_count
                        FROM admin_region a
                        LEFT JOIN admin_region p ON p.region_code = a.parent_code
                        JOIN region_risk_summary r
                          ON r.region_code = a.region_code
                         AND r.reference_month = DATE '2026-03-01'
                         AND r.horizon_days = 60
                         AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS active_case_count,
                                   count(*) FILTER (WHERE monitoring_priority = 'URGENT') AS urgent_case_count
                            FROM case_record c
                            WHERE c.primary_region_code = a.region_code
                              AND c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                        ) c ON true
                        WHERE a.region_code = :region_code
                          AND EXISTS (SELECT 1 FROM reference_dataset_state WHERE state_id = true)
                        """
                    ),
                    {"region_code": region_code},
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            buildings = (
                await connection.execute(
                    text(
                        """
                        SELECT b.building_id, b.building_name, b.road_address, b.lot_address,
                               ST_X(b.centroid) AS lng, ST_Y(b.centroid) AS lat,
                               r.final_score, r.regional_rank, r.top_percentile, r.risk_band
                        FROM building b
                        JOIN building_risk_snapshot r ON r.building_id = b.building_id
                        WHERE b.region_code = :region_code
                          AND r.reference_month = DATE '2026-03-01'
                          AND r.horizon_days = 60
                          AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        ORDER BY r.regional_rank, b.building_id
                        LIMIT 10
                        """
                    ),
                    {"region_code": region_code},
                )
            ).mappings().all()
        building_count = int(row["building_count"])
        bands = {
            "top1": int(row["top_1_count"]),
            "high1To10": int(row["high_1_10_count"]),
            "watch10To25": int(row["watch_10_25_count"]),
            "general": int(row["general_count"]),
        }
        return {
            "regionCode": row["region_code"],
            "level": row["level"],
            "name": row["name"],
            "fullName": row["full_name"],
            "parent": (
                {"regionCode": row["parent_code"], "fullName": row["parent_name"]}
                if row["parent_code"]
                else None
            ),
            "center": [float(row["center_lng"]), float(row["center_lat"])],
            "bounds": [float(item) for item in row["bounds"]],
            "geometry": _geojson(row["geometry"]),
            "riskReference": {
                "referenceMonth": "2026-03",
                "horizonDays": HORIZON_DAYS,
                "lineageVersion": LINEAGE_VERSION,
                "isProbability": False,
                "calculatedAt": row["calculated_at"].isoformat(),
            },
            "distribution": {
                "buildingCount": building_count,
                "top10Count": int(row["top_10_count"]),
                "bands": bands,
                "bandShares": {
                    key: round(value / building_count * 100, 2) if building_count else 0
                    for key, value in bands.items()
                },
                "scoreStats": {
                    "minimum": float(row["score_min"]),
                    "median": float(row["score_median"]),
                    "p90": float(row["score_p90"]),
                    "p99": float(row["score_p99"]),
                    "maximum": float(row["score_max"]),
                },
            },
            "currentSignals": {
                "activeCaseCount": int(row["active_case_count"]),
                "urgentCaseCount": int(row["urgent_case_count"]),
                "hasCurrentSignal": int(row["active_case_count"]) > 0,
            },
            "topBuildings": [
                {
                    "buildingId": str(item["building_id"]),
                    "name": item["building_name"] or "건물명 미등록",
                    "roadAddress": item["road_address"],
                    "lotAddress": item["lot_address"],
                    "center": [float(item["lng"]), float(item["lat"])],
                    "risk": _risk(item),
                }
                for item in buildings
            ],
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def building_detail(
    engine: AsyncEngine,
    building_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT b.building_id, b.source_building_key, b.region_code,
                               a.full_name AS region_name, b.road_address, b.lot_address,
                               b.building_name, b.geometry_status,
                               b.customer_data, b.facility_data, b.quality_flags,
                               ST_X(b.centroid) AS lng, ST_Y(b.centroid) AS lat,
                               ST_AsGeoJSON(b.geometry, 8) AS geometry,
                               ARRAY[ST_XMin(Box3D(b.geometry)), ST_YMin(Box3D(b.geometry)), ST_XMax(Box3D(b.geometry)), ST_YMax(Box3D(b.geometry))] AS bounds,
                               r.final_score, r.regional_rank, r.top_percentile, r.risk_band,
                               r.manifest_hash, r.source_class, r.quality_flags AS risk_quality_flags,
                               coalesce(f.facility_count, 0) AS facility_count,
                               coalesce(f.general_count, 0) AS general_count,
                               coalesce(f.self_count, 0) AS self_count,
                               f.latest_inspection_date,
                               coalesce(c.active_case_count, 0) AS active_case_count,
                               coalesce(c.urgent_case_count, 0) AS urgent_case_count
                        FROM building b
                        JOIN admin_region a ON a.region_code = b.region_code
                        JOIN building_risk_snapshot r
                          ON r.building_id = b.building_id
                         AND r.reference_month = DATE '2026-03-01'
                         AND r.horizon_days = 60
                         AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS facility_count,
                                   count(*) FILTER (WHERE fe.source_type = 'GENERAL') AS general_count,
                                   count(*) FILTER (WHERE fe.source_type = 'SELF') AS self_count,
                                   max(fe.last_inspection_date) AS latest_inspection_date
                            FROM building_facility_link l
                            JOIN facility_entity fe ON fe.facility_id = l.facility_id
                            WHERE l.building_id = b.building_id
                        ) f ON true
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS active_case_count,
                                   count(*) FILTER (WHERE monitoring_priority = 'URGENT') AS urgent_case_count
                            FROM case_record c
                            WHERE c.location IS NOT NULL
                              AND c.status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW')
                              AND ST_DWithin(c.location::geography, b.centroid::geography, 100)
                        ) c ON true
                        WHERE b.building_id = :building_id
                          AND EXISTS (SELECT 1 FROM reference_dataset_state WHERE state_id = true)
                        """
                    ),
                    {"building_id": building_id},
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        customer = dict(row["customer_data"])
        facility = dict(row["facility_data"])
        return {
            "buildingId": str(row["building_id"]),
            "sourceBuildingKey": row["source_building_key"],
            "region": {"regionCode": row["region_code"], "fullName": row["region_name"]},
            "name": row["building_name"] or "건물명 미등록",
            "roadAddress": row["road_address"],
            "lotAddress": row["lot_address"],
            "center": [float(row["lng"]), float(row["lat"])],
            "bounds": [float(item) for item in row["bounds"]],
            "geometry": _geojson(row["geometry"]),
            "geometryStatus": row["geometry_status"],
            "attributes": {
                "mainUseName": customer.get("main_use_name"),
                "mainStructure": customer.get("main_structure"),
                "buildingYear": customer.get("building_year"),
                "buildingAge": customer.get("building_age"),
                "approvalDate": customer.get("approval_date"),
                "floorsAbove": customer.get("floors_above"),
                "floorsBelow": customer.get("floors_below"),
                "grossFloorAreaM2": customer.get("gross_floor_area_m2"),
                "landUseName": customer.get("land_use_name"),
                "registerType": customer.get("register_type"),
            },
            "facilitySummary": {
                "linkedFacilityCount": int(row["facility_count"]),
                "generalCount": int(row["general_count"]),
                "selfCount": int(row["self_count"]),
                "latestInspectionDate": (
                    row["latest_inspection_date"].isoformat()
                    if row["latest_inspection_date"] is not None
                    else facility.get("latest_inspection_date")
                ),
                "candidateSourceCount": facility.get("candidate_source_count", 0),
            },
            "risk": {
                **_risk(row),
                "sourceClass": row["source_class"],
                "manifestHash": row["manifest_hash"],
            },
            "currentSignals": {
                "activeCaseCount": int(row["active_case_count"]),
                "urgentCaseCount": int(row["urgent_case_count"]),
                "hasCurrentSignal": int(row["active_case_count"]) > 0,
            },
            "quality": {
                "buildingFlags": list(row["quality_flags"]),
                "riskFlags": list(row["risk_quality_flags"]),
            },
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))
