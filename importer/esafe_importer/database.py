from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg import Cursor, sql

from esafe_importer.config import ImportConfig
from esafe_importer.domain import (
    EXPECTED_BUILDING_COUNT,
    HORIZON_DAYS,
    LINEAGE_VERSION,
    REFERENCE_MONTH,
    SOURCE_CLASS,
)
from esafe_importer.sources import ReferenceSource


class ReferenceDatabaseImporter:
    def __init__(self, config: ImportConfig) -> None:
        self.config = config
        self.source = ReferenceSource(config)

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        with psycopg.connect(  # noqa: SIM117
            self.config.database_url, application_name="esafe-reference-importer"
        ) as connection:
            with connection.transaction():
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('esafe-reference-import'))"
                )
                cursor.execute("SET LOCAL lock_timeout = '30s'")
                cursor.execute("SET LOCAL statement_timeout = '0'")
                self._create_staging_tables(cursor)
                copy_rows(
                    cursor,
                    "stg_admin_region",
                    ADMIN_COLUMNS,
                    self.source.admin_regions(),
                )
                copy_rows(
                    cursor, "stg_building", BUILDING_COLUMNS, self.source.buildings()
                )
                copy_rows(cursor, "stg_risk", RISK_COLUMNS, self.source.risks())
                copy_rows(
                    cursor, "stg_facility", FACILITY_COLUMNS, self.source.facilities()
                )
                copy_rows(
                    cursor,
                    "stg_facility_link",
                    LINK_COLUMNS,
                    self.source.facility_links(),
                )
                self._validate_staging(cursor)
                self._activate(cursor)
                self._validate_active(cursor)
                cursor.execute("ANALYZE admin_region")
                cursor.execute("ANALYZE building")
                cursor.execute("ANALYZE building_risk_snapshot")
                cursor.execute("ANALYZE facility_entity")
                cursor.execute("ANALYZE building_facility_link")
                cursor.execute("ANALYZE region_risk_summary")
        result: dict[str, Any] = {
            "status": "SUCCESS",
            "import_id": self.config.import_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "metrics": self.source.metrics.as_dict(),
        }
        return result

    @staticmethod
    def _create_staging_tables(cursor: Cursor[Any]) -> None:
        cursor.execute(
            """
            CREATE TEMP TABLE stg_admin_region (
                region_code text, level text, name text, full_name text, parent_code text,
                geometry_wkb bytea, source text, source_version text, source_metadata text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE stg_building (
                building_id uuid, source_building_key text, region_code text, road_address text,
                lot_address text, building_name text, geometry_wkb bytea, customer_data text,
                source_version text, quality_flags text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE stg_risk (
                risk_snapshot_id uuid, building_id uuid, final_score double precision,
                regional_rank integer, top_percentile double precision, risk_band text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE stg_facility (
                facility_id uuid, source_key text, source_type text, source_address text,
                normalized_address text, customer_number text, branch_name text, business_name text,
                general_building_type text, general_contract_type text, self_building_number text,
                self_asset_number text, source_use_class text, source_row_count integer,
                first_inspection_date date, last_inspection_date date, candidate_count integer,
                match_status text, source_version text, quality_flags text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE stg_facility_link (
                facility_id uuid, building_id uuid, candidate_count integer, candidate_rank integer,
                candidate_score numeric(8, 3), match_kind text, source_use_class text,
                building_use_class text, score_detail text, source_version text
            ) ON COMMIT DROP;
            """
        )

    def _validate_staging(self, cursor: Cursor[Any]) -> None:
        expectations = {
            "stg_admin_region": self.source.metrics.admin_region_count,
            "stg_building": EXPECTED_BUILDING_COUNT,
            "stg_risk": EXPECTED_BUILDING_COUNT,
            "stg_facility": self.source.metrics.facility_count,
            "stg_facility_link": self.source.metrics.facility_link_count,
        }
        for table, expected in expectations.items():
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            )
            actual = fetch_int(cursor)
            if actual != expected:
                raise ValueError(
                    f"staging count mismatch for {table}: {actual} != {expected}"
                )
        checks = [
            (
                "duplicate region",
                "SELECT count(*) FROM (SELECT region_code FROM stg_admin_region GROUP BY 1 HAVING count(*) > 1) q",
            ),
            (
                "duplicate building",
                "SELECT count(*) FROM (SELECT source_building_key FROM stg_building GROUP BY 1 HAVING count(*) > 1) q",
            ),
            (
                "unknown building region",
                "SELECT count(*) FROM stg_building b LEFT JOIN stg_admin_region r USING (region_code) WHERE r.region_code IS NULL",
            ),
            (
                "invalid building geometry",
                "SELECT count(*) FROM stg_building WHERE NOT ST_IsValid(ST_SetSRID(ST_GeomFromWKB(geometry_wkb), 4326)) OR ST_IsEmpty(ST_SetSRID(ST_GeomFromWKB(geometry_wkb), 4326))",
            ),
            (
                "duplicate risk building",
                "SELECT count(*) FROM (SELECT building_id FROM stg_risk GROUP BY 1 HAVING count(*) > 1) q",
            ),
            (
                "invalid risk",
                "SELECT count(*) FROM stg_risk WHERE final_score IS NULL OR final_score < 0 OR final_score > 1 OR regional_rank < 1 OR top_percentile <= 0 OR top_percentile > 100",
            ),
            (
                "risk rank gap",
                f"SELECT CASE WHEN min(regional_rank) = 1 AND max(regional_rank) = {EXPECTED_BUILDING_COUNT} AND count(DISTINCT regional_rank) = {EXPECTED_BUILDING_COUNT} THEN 0 ELSE 1 END FROM stg_risk",
            ),
            (
                "duplicate facility",
                "SELECT count(*) FROM (SELECT source_key FROM stg_facility GROUP BY 1 HAVING count(*) > 1) q",
            ),
            (
                "facility link orphan",
                "SELECT count(*) FROM stg_facility_link l LEFT JOIN stg_facility f USING (facility_id) LEFT JOIN stg_building b USING (building_id) WHERE f.facility_id IS NULL OR b.building_id IS NULL",
            ),
            (
                "duplicate facility link",
                "SELECT count(*) FROM (SELECT facility_id, building_id FROM stg_facility_link GROUP BY 1,2 HAVING count(*) > 1) q",
            ),
            (
                "duplicate facility rank",
                "SELECT count(*) FROM (SELECT facility_id, candidate_rank FROM stg_facility_link GROUP BY 1,2 HAVING count(*) > 1) q",
            ),
        ]
        for label, query in checks:
            cursor.execute(query)
            violations = fetch_int(cursor)
            if violations:
                raise ValueError(f"staging validation failed: {label} ({violations})")

    def _activate(self, cursor: Cursor[Any]) -> None:
        cursor.execute(
            """
            INSERT INTO admin_region (
                region_code, level, name, full_name, parent_code, geometry, centroid,
                source, source_version, source_metadata
            )
            SELECT region_code, level, name, full_name, parent_code, geometry,
                   ST_PointOnSurface(geometry), source, source_version, source_metadata::jsonb
            FROM (
                SELECT region_code, level, name, full_name, parent_code,
                       ST_Multi(ST_SetSRID(ST_GeomFromWKB(geometry_wkb), 4326)) AS geometry,
                       source, source_version, source_metadata
                FROM stg_admin_region
            ) prepared
            ORDER BY CASE level WHEN 'SIDO' THEN 1 WHEN 'SIGUNGU' THEN 2 ELSE 3 END, region_code
            ON CONFLICT (region_code) DO UPDATE SET
                level = EXCLUDED.level, name = EXCLUDED.name, full_name = EXCLUDED.full_name,
                parent_code = EXCLUDED.parent_code, geometry = EXCLUDED.geometry,
                centroid = EXCLUDED.centroid, source = EXCLUDED.source,
                source_version = EXCLUDED.source_version, source_metadata = EXCLUDED.source_metadata
            """
        )
        cursor.execute(
            """
            INSERT INTO building (
                building_id, source_building_key, region_code, road_address, lot_address,
                building_name, centroid, geometry, geometry_status, customer_data,
                facility_data, source_version, quality_flags
            )
            SELECT building_id, source_building_key, region_code, road_address, lot_address,
                   building_name, ST_PointOnSurface(geometry), geometry, 'VALID',
                   customer_data::jsonb, '{}'::jsonb, source_version, quality_flags::jsonb
            FROM (
                SELECT building_id, source_building_key, region_code, road_address, lot_address,
                       building_name,
                       ST_Multi(ST_SetSRID(ST_GeomFromWKB(geometry_wkb), 4326)) AS geometry,
                       customer_data, source_version, quality_flags
                FROM stg_building
            ) prepared
            ON CONFLICT (building_id) DO UPDATE SET
                source_building_key = EXCLUDED.source_building_key,
                region_code = EXCLUDED.region_code, road_address = EXCLUDED.road_address,
                lot_address = EXCLUDED.lot_address, building_name = EXCLUDED.building_name,
                centroid = EXCLUDED.centroid, geometry = EXCLUDED.geometry,
                geometry_status = EXCLUDED.geometry_status, customer_data = EXCLUDED.customer_data,
                facility_data = '{}'::jsonb, source_version = EXCLUDED.source_version,
                quality_flags = EXCLUDED.quality_flags
            """
        )
        cursor.execute(
            """
            INSERT INTO building_risk_snapshot (
                risk_snapshot_id, building_id, reference_month, horizon_days, final_score,
                regional_rank, top_percentile, risk_band, lineage_version, manifest_hash,
                source_class, is_synthetic, quality_flags
            )
            SELECT risk_snapshot_id, building_id, %s::date, %s, final_score, regional_rank,
                   top_percentile, risk_band, %s, %s, %s, false, '[]'::jsonb
            FROM stg_risk
            ON CONFLICT (risk_snapshot_id) DO UPDATE SET
                building_id = EXCLUDED.building_id, reference_month = EXCLUDED.reference_month,
                horizon_days = EXCLUDED.horizon_days, final_score = EXCLUDED.final_score,
                regional_rank = EXCLUDED.regional_rank, top_percentile = EXCLUDED.top_percentile,
                risk_band = EXCLUDED.risk_band, lineage_version = EXCLUDED.lineage_version,
                manifest_hash = EXCLUDED.manifest_hash, source_class = EXCLUDED.source_class,
                is_synthetic = false, quality_flags = EXCLUDED.quality_flags
            """,
            (
                REFERENCE_MONTH,
                HORIZON_DAYS,
                LINEAGE_VERSION,
                self.config.source_manifest_hash,
                SOURCE_CLASS,
            ),
        )
        cursor.execute(
            """
            INSERT INTO facility_entity (
                facility_id, source_key, source_type, source_address, normalized_address,
                customer_number, branch_name, business_name, general_building_type,
                general_contract_type, self_building_number, self_asset_number, source_use_class,
                source_row_count, first_inspection_date, last_inspection_date, candidate_count,
                match_status, source_version, quality_flags
            )
            SELECT facility_id, source_key, source_type, source_address, normalized_address,
                   customer_number, branch_name, business_name, general_building_type,
                   general_contract_type, self_building_number, self_asset_number, source_use_class,
                   source_row_count, first_inspection_date, last_inspection_date, candidate_count,
                   match_status, source_version, quality_flags::jsonb
            FROM stg_facility
            ON CONFLICT (facility_id) DO UPDATE SET
                source_key = EXCLUDED.source_key, source_type = EXCLUDED.source_type,
                source_address = EXCLUDED.source_address, normalized_address = EXCLUDED.normalized_address,
                customer_number = EXCLUDED.customer_number, branch_name = EXCLUDED.branch_name,
                business_name = EXCLUDED.business_name,
                general_building_type = EXCLUDED.general_building_type,
                general_contract_type = EXCLUDED.general_contract_type,
                self_building_number = EXCLUDED.self_building_number,
                self_asset_number = EXCLUDED.self_asset_number,
                source_use_class = EXCLUDED.source_use_class,
                source_row_count = EXCLUDED.source_row_count,
                first_inspection_date = EXCLUDED.first_inspection_date,
                last_inspection_date = EXCLUDED.last_inspection_date,
                candidate_count = EXCLUDED.candidate_count, match_status = EXCLUDED.match_status,
                source_version = EXCLUDED.source_version, quality_flags = EXCLUDED.quality_flags
            """
        )
        cursor.execute(
            """
            INSERT INTO building_facility_link (
                facility_id, building_id, candidate_count, candidate_rank, candidate_score,
                match_kind, source_use_class, building_use_class, score_detail, source_version
            )
            SELECT facility_id, building_id, candidate_count, candidate_rank, candidate_score,
                   match_kind, source_use_class, building_use_class, score_detail, source_version
            FROM stg_facility_link
            ON CONFLICT (facility_id, building_id) DO UPDATE SET
                candidate_count = EXCLUDED.candidate_count,
                candidate_rank = EXCLUDED.candidate_rank,
                candidate_score = EXCLUDED.candidate_score, match_kind = EXCLUDED.match_kind,
                source_use_class = EXCLUDED.source_use_class,
                building_use_class = EXCLUDED.building_use_class,
                score_detail = EXCLUDED.score_detail, source_version = EXCLUDED.source_version
            """
        )
        cursor.execute(
            "DELETE FROM building_facility_link l WHERE NOT EXISTS (SELECT 1 FROM stg_facility_link s WHERE s.facility_id = l.facility_id AND s.building_id = l.building_id)"
        )
        cursor.execute(
            "DELETE FROM facility_entity f WHERE NOT EXISTS (SELECT 1 FROM stg_facility s WHERE s.facility_id = f.facility_id)"
        )
        cursor.execute(
            "DELETE FROM building_risk_snapshot r WHERE r.lineage_version = %s AND NOT EXISTS (SELECT 1 FROM stg_risk s WHERE s.risk_snapshot_id = r.risk_snapshot_id)",
            (LINEAGE_VERSION,),
        )
        cursor.execute(
            "DELETE FROM building b WHERE NOT EXISTS (SELECT 1 FROM stg_building s WHERE s.building_id = b.building_id)"
        )
        cursor.execute(
            "DELETE FROM admin_region r WHERE NOT EXISTS (SELECT 1 FROM stg_admin_region s WHERE s.region_code = r.region_code)"
        )
        self._refresh_aggregates(cursor)
        cursor.execute(
            """
            UPDATE building b
            SET quality_flags = quality_flags ||
                '["ADMIN_BOUNDARY_CENTROID_MISMATCH"]'::jsonb
            FROM admin_region r
            WHERE r.region_code = b.region_code
              AND NOT ST_Covers(r.geometry, b.centroid)
            """
        )
        self.source.metrics.boundary_centroid_mismatches = cursor.rowcount or 0
        cursor.execute(
            """
            INSERT INTO reference_import (
                import_id, source_manifest_sha256, boundary_manifest_sha256,
                source_file_count, source_total_bytes, building_count, risk_count,
                facility_count, facility_link_count, source_version, quality_summary
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (import_id) DO UPDATE SET
                source_manifest_sha256 = EXCLUDED.source_manifest_sha256,
                boundary_manifest_sha256 = EXCLUDED.boundary_manifest_sha256,
                source_file_count = EXCLUDED.source_file_count,
                source_total_bytes = EXCLUDED.source_total_bytes,
                building_count = EXCLUDED.building_count, risk_count = EXCLUDED.risk_count,
                facility_count = EXCLUDED.facility_count,
                facility_link_count = EXCLUDED.facility_link_count,
                source_version = EXCLUDED.source_version,
                quality_summary = EXCLUDED.quality_summary,
                activated_at = CURRENT_TIMESTAMP
            """,
            (
                self.config.import_id,
                self.config.source_manifest_hash,
                self.config.boundary_manifest_hash,
                int(self.config.verified_manifest["fileCount"]),
                int(self.config.verified_manifest["totalBytes"]),
                self.source.metrics.building_count,
                self.source.metrics.risk_count,
                self.source.metrics.facility_count,
                self.source.metrics.facility_link_count,
                self.config.import_id,
                json.dumps(self.source.metrics.as_dict(), separators=(",", ":")),
            ),
        )
        cursor.execute(
            """
            INSERT INTO reference_dataset_state (state_id, active_import_id)
            VALUES (true, %s)
            ON CONFLICT (state_id) DO UPDATE SET
                active_import_id = EXCLUDED.active_import_id,
                activated_at = CURRENT_TIMESTAMP
            """,
            (self.config.import_id,),
        )

    @staticmethod
    def _refresh_aggregates(cursor: Cursor[Any]) -> None:
        cursor.execute(
            """
            UPDATE building SET facility_data = '{}'::jsonb;
            UPDATE building b
            SET facility_data = summary.value
            FROM (
                SELECT building_id, jsonb_build_object(
                    'candidate_source_count', count(*),
                    'general_candidate_count', count(*) FILTER (WHERE f.source_type = 'GENERAL'),
                    'self_candidate_count', count(*) FILTER (WHERE f.source_type = 'SELF'),
                    'primary_candidate_count', count(*) FILTER (WHERE l.candidate_rank = 1),
                    'latest_inspection_date', max(f.last_inspection_date)
                ) AS value
                FROM building_facility_link l
                JOIN facility_entity f USING (facility_id)
                GROUP BY building_id
            ) summary
            WHERE summary.building_id = b.building_id;

            DELETE FROM region_risk_summary WHERE lineage_version = 'v27.1-focus-2026-03-60d';
            WITH risk_members AS (
                SELECT b.region_code, r.final_score, r.risk_band
                FROM building b
                JOIN building_risk_snapshot r USING (building_id)
                WHERE r.reference_month = DATE '2026-03-01'
                  AND r.horizon_days = 60
                  AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                UNION ALL
                SELECT region.parent_code, r.final_score, r.risk_band
                FROM building b
                JOIN admin_region region ON region.region_code = b.region_code
                JOIN building_risk_snapshot r USING (building_id)
                WHERE region.parent_code IS NOT NULL
                  AND r.reference_month = DATE '2026-03-01'
                  AND r.horizon_days = 60
                  AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                UNION ALL
                SELECT emd.region_code, r.final_score, r.risk_band
                FROM building b
                JOIN admin_region emd
                  ON emd.level = 'EUPMYEONDONG'
                 AND emd.geometry && b.centroid
                 AND ST_Covers(emd.geometry, b.centroid)
                JOIN building_risk_snapshot r USING (building_id)
                WHERE r.reference_month = DATE '2026-03-01'
                  AND r.horizon_days = 60
                  AND r.lineage_version = 'v27.1-focus-2026-03-60d'
            )
            INSERT INTO region_risk_summary (
                region_code, reference_month, horizon_days, lineage_version, building_count,
                top_1_count, high_1_10_count, watch_10_25_count, general_count, top_10_count,
                score_min, score_median, score_p90, score_p99, score_max
            )
            SELECT region_code, DATE '2026-03-01', 60, 'v27.1-focus-2026-03-60d',
                   count(*), count(*) FILTER (WHERE risk_band = 'TOP_1'),
                   count(*) FILTER (WHERE risk_band = 'HIGH_1_10'),
                   count(*) FILTER (WHERE risk_band = 'WATCH_10_25'),
                   count(*) FILTER (WHERE risk_band = 'GENERAL'),
                   count(*) FILTER (WHERE risk_band IN ('TOP_1', 'HIGH_1_10')),
                   min(final_score), percentile_cont(0.5) WITHIN GROUP (ORDER BY final_score),
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY final_score),
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY final_score), max(final_score)
            FROM risk_members
            GROUP BY region_code;
            """
        )

    def _validate_active(self, cursor: Cursor[Any]) -> None:
        checks = [
            (
                "active building count",
                "SELECT count(*) FROM building",
                EXPECTED_BUILDING_COUNT,
            ),
            (
                "active risk count",
                "SELECT count(*) FROM building_risk_snapshot WHERE reference_month = DATE '2026-03-01' AND horizon_days = 60 AND lineage_version = 'v27.1-focus-2026-03-60d'",
                EXPECTED_BUILDING_COUNT,
            ),
            (
                "active invalid geometry",
                "SELECT count(*) FROM building WHERE geometry_status <> 'VALID' OR NOT ST_IsValid(geometry) OR ST_SRID(geometry) <> 4326",
                0,
            ),
            (
                "active invalid score",
                "SELECT count(*) FROM building_risk_snapshot WHERE final_score IS NULL OR final_score < 0 OR final_score > 1 OR is_synthetic OR source_class <> 'V27_1_FOCUS_FINAL_SCORE'",
                0,
            ),
        ]
        for label, query, expected in checks:
            cursor.execute(query)
            actual = fetch_int(cursor)
            if actual != expected:
                raise ValueError(f"{label}: {actual} != {expected}")


def fetch_int(cursor: Cursor[Any]) -> int:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("database count query returned no row")
    return int(row[0])


def copy_rows(
    cursor: Cursor[Any],
    table: str,
    columns: tuple[str, ...],
    rows: Iterable[tuple[Any, ...]],
) -> int:
    query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    count = 0
    started = time.monotonic()
    with cursor.copy(query) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
            if count % 100_000 == 0:
                print(
                    json.dumps(
                        {"event": "copy_progress", "table": table, "rows": count}
                    ),
                    flush=True,
                )
    print(
        json.dumps(
            {
                "event": "copy_complete",
                "table": table,
                "rows": count,
                "seconds": round(time.monotonic() - started, 3),
            }
        ),
        flush=True,
    )
    return count


ADMIN_COLUMNS = (
    "region_code",
    "level",
    "name",
    "full_name",
    "parent_code",
    "geometry_wkb",
    "source",
    "source_version",
    "source_metadata",
)
BUILDING_COLUMNS = (
    "building_id",
    "source_building_key",
    "region_code",
    "road_address",
    "lot_address",
    "building_name",
    "geometry_wkb",
    "customer_data",
    "source_version",
    "quality_flags",
)
RISK_COLUMNS = (
    "risk_snapshot_id",
    "building_id",
    "final_score",
    "regional_rank",
    "top_percentile",
    "risk_band",
)
FACILITY_COLUMNS = (
    "facility_id",
    "source_key",
    "source_type",
    "source_address",
    "normalized_address",
    "customer_number",
    "branch_name",
    "business_name",
    "general_building_type",
    "general_contract_type",
    "self_building_number",
    "self_asset_number",
    "source_use_class",
    "source_row_count",
    "first_inspection_date",
    "last_inspection_date",
    "candidate_count",
    "match_status",
    "source_version",
    "quality_flags",
)
LINK_COLUMNS = (
    "facility_id",
    "building_id",
    "candidate_count",
    "candidate_rank",
    "candidate_score",
    "match_kind",
    "source_use_class",
    "building_use_class",
    "score_detail",
    "source_version",
)
