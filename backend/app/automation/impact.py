from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.automation.case_rules import (
    ALLOWED_RADII_M,
    IMPACT_RULE_VERSION,
    ImpactScopeType,
)

RISK_LINEAGE_VERSION: Final = "v27.1-focus-2026-03-60d"


@dataclass(frozen=True, slots=True)
class ImpactResult:
    case_id: UUID
    impact_scope_id: UUID
    scope_type: ImpactScopeType
    building_count: int
    high_risk_count: int
    incident_building_count: int
    precision_warning: str | None


async def _load_case(connection: AsyncConnection, case_id: UUID) -> dict[str, Any]:
    row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT case_id, primary_region_code, normalized_address,
                           location IS NOT NULL AS has_location,
                           location_precision
                    FROM case_record
                    WHERE case_id = :case_id
                    FOR UPDATE
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"Case does not exist: {case_id}")
    case_row = dict(row)
    linked_regions = (
        (
            await connection.execute(
                text(
                    """
                    SELECT DISTINCT region.region_code
                    FROM case_signal_link link
                    JOIN signal_event event
                      ON event.signal_event_id = link.signal_event_id
                    CROSS JOIN LATERAL
                      unnest(event.region_codes) AS region(region_code)
                    WHERE link.case_id = :case_id
                      AND link.link_type IN ('PRIMARY', 'UPDATE', 'MERGED_SOURCE')
                    ORDER BY region.region_code
                    """
                ),
                {"case_id": case_id},
            )
        )
        .scalars()
        .all()
    )
    primary_region = case_row["primary_region_code"]
    case_row["region_codes"] = tuple(str(value) for value in linked_regions) or (
        (str(primary_region),) if primary_region is not None else ()
    )
    return case_row


async def _assert_risk_contract(connection: AsyncConnection) -> None:
    count = (
        await connection.execute(
            text(
                """
                SELECT count(1)
                FROM building_risk_snapshot
                WHERE reference_month = DATE '2026-03-01'
                  AND horizon_days = 60
                  AND lineage_version = :lineage_version
                  AND source_class = 'V27_1_FOCUS_FINAL_SCORE'
                  AND NOT is_synthetic
                """
            ),
            {"lineage_version": RISK_LINEAGE_VERSION},
        )
    ).scalar_one()
    if int(count) != 217_238:
        raise RuntimeError(
            f"active risk contract requires 217238 rows, found {int(count)}"
        )


async def _insert_scope(
    connection: AsyncConnection,
    case_id: UUID,
    case_row: dict[str, Any],
    radius_m: int,
) -> tuple[UUID, ImpactScopeType, str | None]:
    scope_id = uuid4()
    if bool(case_row["has_location"]):
        await connection.execute(
            text(
                """
                INSERT INTO case_impact_scope (
                    impact_scope_id, case_id, scope_type, center, radius_m,
                    region_codes, precision_warning, rule_version
                )
                SELECT :scope_id, case_id, 'RADIUS', location, :radius_m,
                       '{}'::varchar(10)[], NULL, :rule_version
                FROM case_record WHERE case_id = :case_id
                """
            ),
            {
                "scope_id": scope_id,
                "case_id": case_id,
                "radius_m": radius_m,
                "rule_version": IMPACT_RULE_VERSION,
            },
        )
        return scope_id, ImpactScopeType.RADIUS, None

    region_codes = tuple(case_row["region_codes"])
    if not region_codes:
        raise ValueError("a Case without a point must identify a primary region")
    precision_warning = (
        "LOCATION_PRECISION_SIDO" if all(len(code) == 2 for code in region_codes) else None
    )
    await connection.execute(
        text(
            """
            INSERT INTO case_impact_scope (
                impact_scope_id, case_id, scope_type, center, radius_m,
                region_codes, precision_warning, rule_version
            )
            VALUES (
                :scope_id, :case_id, 'ADMIN_REGION', NULL, NULL,
                CAST(:region_codes AS varchar(10)[]), :precision_warning, :rule_version
            )
            """
        ),
        {
            "scope_id": scope_id,
            "case_id": case_id,
            "region_codes": list(region_codes),
            "precision_warning": precision_warning,
            "rule_version": IMPACT_RULE_VERSION,
        },
    )
    return scope_id, ImpactScopeType.ADMIN_REGION, precision_warning


async def _insert_radius_buildings(
    connection: AsyncConnection,
    case_id: UUID,
    radius_m: int,
) -> None:
    await connection.execute(
        text(
            """
            WITH case_point AS (
                SELECT location, normalized_address
                FROM case_record
                WHERE case_id = :case_id
            ),
            spatial_matches AS (
                SELECT b.building_id,
                       ST_Distance(b.centroid::geography, p.location::geography) AS distance_m,
                       (
                           ST_Covers(b.geometry, p.location)
                           OR (
                               p.normalized_address IS NOT NULL
                               AND p.normalized_address <> ''
                               AND p.normalized_address IN (
                                   regexp_replace(coalesce(b.road_address, ''), '\\s+', '', 'g'),
                                   regexp_replace(coalesce(b.lot_address, ''), '\\s+', '', 'g')
                               )
                           )
                       ) AS exact_candidate
                FROM case_point p
                JOIN building b
                  ON ST_DWithin(
                      b.centroid::geography,
                      p.location::geography,
                      :radius_m
                  )
            ),
            exact_count AS (
                SELECT count(1) FILTER (WHERE exact_candidate) AS value
                FROM spatial_matches
            ),
            ranked AS (
                SELECT m.building_id,
                       r.risk_snapshot_id,
                       m.distance_m,
                       (m.exact_candidate AND c.value = 1) AS is_incident_building,
                       (r.top_percentile <= 10.0) AS is_high_risk,
                       r.final_score
                FROM spatial_matches m
                CROSS JOIN exact_count c
                JOIN building_risk_snapshot r ON r.building_id = m.building_id
                WHERE r.reference_month = DATE '2026-03-01'
                  AND r.horizon_days = 60
                  AND r.lineage_version = :lineage_version
                  AND r.source_class = 'V27_1_FOCUS_FINAL_SCORE'
                  AND NOT r.is_synthetic
            ),
            ordered AS (
                SELECT *,
                       row_number() OVER (
                           ORDER BY is_incident_building DESC, final_score DESC, building_id
                       ) AS priority_order
                FROM ranked
            )
            INSERT INTO case_building (
                case_id, building_id, risk_snapshot_id, match_reason,
                distance_m, is_incident_building, is_high_risk,
                priority_order, rule_version
            )
            SELECT :case_id, building_id, risk_snapshot_id,
                   CASE WHEN is_incident_building THEN 'EXACT' ELSE 'RADIUS' END,
                   distance_m, is_incident_building, is_high_risk,
                   priority_order, :rule_version
            FROM ordered
            """
        ),
        {
            "case_id": case_id,
            "radius_m": radius_m,
            "lineage_version": RISK_LINEAGE_VERSION,
            "rule_version": IMPACT_RULE_VERSION,
        },
    )


async def _insert_region_buildings(
    connection: AsyncConnection,
    case_id: UUID,
    region_codes: tuple[str, ...],
) -> None:
    await connection.execute(
        text(
            """
            WITH selected_regions AS (
                SELECT region_code
                FROM admin_region
                WHERE region_code = ANY(CAST(:region_codes AS varchar(10)[]))
                   OR parent_code = ANY(CAST(:region_codes AS varchar(10)[]))
            ),
            ranked AS (
                SELECT b.building_id,
                       r.risk_snapshot_id,
                       (r.top_percentile <= 10.0) AS is_high_risk,
                       r.final_score
                FROM selected_regions selected
                JOIN building b ON b.region_code = selected.region_code
                JOIN building_risk_snapshot r ON r.building_id = b.building_id
                WHERE r.reference_month = DATE '2026-03-01'
                  AND r.horizon_days = 60
                  AND r.lineage_version = :lineage_version
                  AND r.source_class = 'V27_1_FOCUS_FINAL_SCORE'
                  AND NOT r.is_synthetic
            ),
            ordered AS (
                SELECT *,
                       row_number() OVER (
                           ORDER BY final_score DESC, building_id
                       ) AS priority_order
                FROM ranked
            )
            INSERT INTO case_building (
                case_id, building_id, risk_snapshot_id, match_reason,
                distance_m, is_incident_building, is_high_risk,
                priority_order, rule_version
            )
            SELECT :case_id, building_id, risk_snapshot_id, 'ADMIN_REGION',
                   NULL, false, is_high_risk, priority_order, :rule_version
            FROM ordered
            """
        ),
        {
            "case_id": case_id,
            "region_codes": list(region_codes),
            "lineage_version": RISK_LINEAGE_VERSION,
            "rule_version": IMPACT_RULE_VERSION,
        },
    )


async def rebuild_case_impact(
    connection: AsyncConnection,
    case_id: UUID,
    radius_m: int = 1000,
) -> ImpactResult:
    if radius_m not in ALLOWED_RADII_M:
        raise ValueError("radius_m must be one of 500, 1000, 3000, or 5000")
    case_row = await _load_case(connection, case_id)
    await _assert_risk_contract(connection)
    await connection.execute(
        text("DELETE FROM case_building WHERE case_id = :case_id"),
        {"case_id": case_id},
    )
    scope_id, scope_type, precision_warning = await _insert_scope(
        connection, case_id, case_row, radius_m
    )
    if scope_type is ImpactScopeType.RADIUS:
        await _insert_radius_buildings(connection, case_id, radius_m)
    else:
        await _insert_region_buildings(connection, case_id, tuple(case_row["region_codes"]))

    counts = (
        (
            await connection.execute(
                text(
                    """
                    SELECT count(1) AS building_count,
                           count(1) FILTER (WHERE is_high_risk) AS high_risk_count,
                           count(1) FILTER (WHERE is_incident_building) AS incident_count
                    FROM case_building
                    WHERE case_id = :case_id
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one()
    )
    building_count = int(counts["building_count"])
    if scope_type is ImpactScopeType.ADMIN_REGION and building_count == 0:
        precision_warning = "REFERENCE_BUILDINGS_UNAVAILABLE"
        await connection.execute(
            text(
                """
                UPDATE case_impact_scope
                SET precision_warning = :warning
                WHERE impact_scope_id = :scope_id
                """
            ),
            {"warning": precision_warning, "scope_id": scope_id},
        )

    return ImpactResult(
        case_id=case_id,
        impact_scope_id=scope_id,
        scope_type=scope_type,
        building_count=building_count,
        high_risk_count=int(counts["high_risk_count"]),
        incident_building_count=int(counts["incident_count"]),
        precision_warning=precision_warning,
    )
