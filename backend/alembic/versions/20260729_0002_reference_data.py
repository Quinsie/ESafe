# ruff: noqa: E501
"""Create immutable reference, spatial, risk, and facility tables.

Revision ID: 20260729_0002
Revises: 20260729_0001
Create Date: 2026-07-29 04:50:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0002"
down_revision: str | None = "20260729_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE reference_import (
            import_id text PRIMARY KEY,
            source_manifest_sha256 char(64) NOT NULL,
            boundary_manifest_sha256 char(64) NOT NULL,
            source_file_count integer NOT NULL CHECK (source_file_count > 0),
            source_total_bytes bigint NOT NULL CHECK (source_total_bytes > 0),
            building_count integer NOT NULL CHECK (building_count >= 0),
            risk_count integer NOT NULL CHECK (risk_count >= 0),
            facility_count integer NOT NULL CHECK (facility_count >= 0),
            facility_link_count integer NOT NULL CHECK (facility_link_count >= 0),
            source_version text NOT NULL,
            quality_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
            activated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_reference_import_source_hash CHECK (source_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_reference_import_boundary_hash CHECK (boundary_manifest_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE reference_dataset_state (
            state_id boolean PRIMARY KEY DEFAULT true CHECK (state_id),
            active_import_id text NOT NULL REFERENCES reference_import(import_id),
            activated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE admin_region (
            region_code varchar(10) PRIMARY KEY,
            level varchar(20) NOT NULL,
            name text NOT NULL,
            full_name text NOT NULL,
            parent_code varchar(10) REFERENCES admin_region(region_code),
            geometry geometry(MultiPolygon, 4326) NOT NULL,
            centroid geometry(Point, 4326) NOT NULL,
            source text NOT NULL,
            source_version text NOT NULL,
            source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_admin_region_level CHECK (level IN ('SIDO', 'SIGUNGU', 'EUPMYEONDONG')),
            CONSTRAINT ck_admin_region_geometry_valid CHECK (ST_IsValid(geometry)),
            CONSTRAINT ck_admin_region_geometry_nonempty CHECK (NOT ST_IsEmpty(geometry)),
            CONSTRAINT ck_admin_region_centroid_nonempty CHECK (NOT ST_IsEmpty(centroid))
        );
        CREATE INDEX ix_admin_region_parent_level ON admin_region (parent_code, level);
        CREATE INDEX ix_admin_region_geometry_gist ON admin_region USING gist (geometry);

        CREATE TABLE building (
            building_id uuid PRIMARY KEY,
            source_building_key text NOT NULL UNIQUE,
            region_code varchar(10) NOT NULL REFERENCES admin_region(region_code),
            road_address text,
            lot_address text NOT NULL,
            building_name text,
            centroid geometry(Point, 4326) NOT NULL,
            geometry geometry(MultiPolygon, 4326) NOT NULL,
            geometry_status varchar(20) NOT NULL,
            customer_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            facility_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_version text NOT NULL,
            quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            CONSTRAINT ck_building_geometry_status CHECK (geometry_status IN ('VALID', 'MISSING', 'INVALID', 'UNMATCHED')),
            CONSTRAINT ck_building_valid_geometry_contract CHECK (geometry_status <> 'VALID' OR (ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry))),
            CONSTRAINT ck_building_customer_data_object CHECK (jsonb_typeof(customer_data) = 'object'),
            CONSTRAINT ck_building_facility_data_object CHECK (jsonb_typeof(facility_data) = 'object'),
            CONSTRAINT ck_building_quality_flags_array CHECK (jsonb_typeof(quality_flags) = 'array')
        );
        CREATE INDEX ix_building_region_code ON building (region_code, source_building_key);
        CREATE INDEX ix_building_geometry_gist ON building USING gist (geometry);
        CREATE INDEX ix_building_centroid_gist ON building USING gist (centroid);

        CREATE TABLE building_risk_snapshot (
            risk_snapshot_id uuid PRIMARY KEY,
            building_id uuid NOT NULL REFERENCES building(building_id) ON DELETE CASCADE,
            reference_month date NOT NULL,
            horizon_days smallint NOT NULL,
            final_score double precision NOT NULL,
            regional_rank integer NOT NULL,
            top_percentile double precision NOT NULL,
            risk_band varchar(20) NOT NULL,
            lineage_version text NOT NULL,
            manifest_hash char(64) NOT NULL,
            source_class varchar(64) NOT NULL,
            is_synthetic boolean NOT NULL DEFAULT false,
            quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            CONSTRAINT uq_building_risk_snapshot_lineage UNIQUE (building_id, reference_month, horizon_days, lineage_version),
            CONSTRAINT ck_building_risk_horizon CHECK (horizon_days = 60),
            CONSTRAINT ck_building_risk_score CHECK (final_score >= 0.0 AND final_score <= 1.0),
            CONSTRAINT ck_building_risk_rank CHECK (regional_rank > 0),
            CONSTRAINT ck_building_risk_percentile CHECK (top_percentile > 0.0 AND top_percentile <= 100.0),
            CONSTRAINT ck_building_risk_band CHECK (risk_band IN ('TOP_1', 'HIGH_1_10', 'WATCH_10_25', 'GENERAL')),
            CONSTRAINT ck_building_risk_source_class CHECK (source_class = 'V27_1_FOCUS_FINAL_SCORE'),
            CONSTRAINT ck_building_risk_not_synthetic CHECK (NOT is_synthetic),
            CONSTRAINT ck_building_risk_manifest_hash CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_building_risk_quality_flags_array CHECK (jsonb_typeof(quality_flags) = 'array')
        );
        CREATE INDEX ix_building_risk_score_desc ON building_risk_snapshot (reference_month, horizon_days, final_score DESC, building_id);
        CREATE UNIQUE INDEX ux_building_risk_regional_rank ON building_risk_snapshot (reference_month, horizon_days, lineage_version, regional_rank);
        CREATE INDEX ix_building_risk_band_rank ON building_risk_snapshot (risk_band, regional_rank);

        CREATE TABLE facility_entity (
            facility_id uuid PRIMARY KEY,
            source_key text NOT NULL UNIQUE,
            source_type varchar(16) NOT NULL,
            source_address text,
            normalized_address text,
            customer_number text,
            branch_name text,
            business_name text,
            general_building_type text,
            general_contract_type text,
            self_building_number text,
            self_asset_number text,
            source_use_class text,
            source_row_count integer NOT NULL,
            first_inspection_date date,
            last_inspection_date date,
            candidate_count integer NOT NULL,
            match_status varchar(32) NOT NULL,
            source_version text NOT NULL,
            quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            CONSTRAINT ck_facility_source_type CHECK (source_type IN ('GENERAL', 'SELF')),
            CONSTRAINT ck_facility_source_row_count CHECK (source_row_count > 0),
            CONSTRAINT ck_facility_candidate_count CHECK (candidate_count >= 0),
            CONSTRAINT ck_facility_quality_flags_array CHECK (jsonb_typeof(quality_flags) = 'array')
        );
        CREATE INDEX ix_facility_entity_type_status ON facility_entity (source_type, match_status);
        CREATE INDEX ix_facility_entity_customer_number ON facility_entity (customer_number) WHERE customer_number IS NOT NULL;

        CREATE TABLE building_facility_link (
            facility_id uuid NOT NULL REFERENCES facility_entity(facility_id) ON DELETE CASCADE,
            building_id uuid NOT NULL REFERENCES building(building_id) ON DELETE CASCADE,
            candidate_count integer NOT NULL,
            candidate_rank integer NOT NULL,
            candidate_score numeric(8, 3),
            match_kind text,
            source_use_class text,
            building_use_class text,
            score_detail text,
            source_version text NOT NULL,
            PRIMARY KEY (facility_id, building_id),
            CONSTRAINT uq_building_facility_candidate_rank UNIQUE (facility_id, candidate_rank),
            CONSTRAINT ck_building_facility_candidate_count CHECK (candidate_count > 0),
            CONSTRAINT ck_building_facility_candidate_rank CHECK (candidate_rank > 0),
            CONSTRAINT ck_building_facility_candidate_score CHECK (candidate_score IS NULL OR candidate_score >= 0)
        );
        CREATE INDEX ix_building_facility_link_building ON building_facility_link (building_id, candidate_rank);

        CREATE TABLE region_risk_summary (
            region_code varchar(10) NOT NULL REFERENCES admin_region(region_code) ON DELETE CASCADE,
            reference_month date NOT NULL,
            horizon_days smallint NOT NULL,
            lineage_version text NOT NULL,
            building_count integer NOT NULL,
            top_1_count integer NOT NULL,
            high_1_10_count integer NOT NULL,
            watch_10_25_count integer NOT NULL,
            general_count integer NOT NULL,
            top_10_count integer NOT NULL,
            score_min double precision,
            score_median double precision,
            score_p90 double precision,
            score_p99 double precision,
            score_max double precision,
            calculated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (region_code, reference_month, horizon_days, lineage_version),
            CONSTRAINT ck_region_risk_counts_nonnegative CHECK (building_count >= 0 AND top_1_count >= 0 AND high_1_10_count >= 0 AND watch_10_25_count >= 0 AND general_count >= 0 AND top_10_count >= 0),
            CONSTRAINT ck_region_risk_band_sum CHECK (building_count = top_1_count + high_1_10_count + watch_10_25_count + general_count)
        );
        CREATE INDEX ix_region_risk_summary_snapshot ON region_risk_summary (reference_month, horizon_days, lineage_version, region_code);
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE IF EXISTS region_risk_summary;
        DROP TABLE IF EXISTS building_facility_link;
        DROP TABLE IF EXISTS facility_entity;
        DROP TABLE IF EXISTS building_risk_snapshot;
        DROP TABLE IF EXISTS building;
        DROP TABLE IF EXISTS admin_region;
        DROP TABLE IF EXISTS reference_dataset_state;
        DROP TABLE IF EXISTS reference_import;
        """
    )
