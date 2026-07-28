# ruff: noqa: E501
"""Create de-identified historical incident and public facility reference tables.

Revision ID: 20260729_0005
Revises: 20260729_0004
Create Date: 2026-07-29 08:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0005"
down_revision: str | None = "20260729_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE historical_incident (
            incident_id uuid PRIMARY KEY,
            source_family varchar(16) NOT NULL,
            source_format varchar(8) NOT NULL,
            source_hash char(64) NOT NULL,
            reported_on date,
            display_title text NOT NULL,
            incident_type varchar(32) NOT NULL,
            sido_name varchar(32),
            sigungu_name varchar(32),
            facility_type varchar(64) NOT NULL,
            cause_categories jsonb NOT NULL DEFAULT '[]'::jsonb,
            damage_categories jsonb NOT NULL DEFAULT '[]'::jsonb,
            action_categories jsonb NOT NULL DEFAULT '[]'::jsonb,
            equipment_categories jsonb NOT NULL DEFAULT '[]'::jsonb,
            parser_status varchar(24) NOT NULL,
            privacy_status varchar(24) NOT NULL,
            quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            source_version varchar(128) NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_historical_incident_family CHECK (source_family IN ('GENERAL', 'MAJOR')),
            CONSTRAINT ck_historical_incident_format CHECK (source_format IN ('HWPX', 'HWP')),
            CONSTRAINT ck_historical_incident_parser CHECK (parser_status IN ('STRUCTURED_PREVIEW', 'METADATA_ONLY')),
            CONSTRAINT ck_historical_incident_privacy CHECK (privacy_status = 'DERIVED_NO_PII'),
            CONSTRAINT ck_historical_incident_hash CHECK (source_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_historical_incident_title CHECK (length(trim(display_title)) > 0),
            CONSTRAINT ck_historical_incident_arrays CHECK (
                jsonb_typeof(cause_categories) = 'array'
                AND jsonb_typeof(damage_categories) = 'array'
                AND jsonb_typeof(action_categories) = 'array'
                AND jsonb_typeof(equipment_categories) = 'array'
                AND jsonb_typeof(quality_flags) = 'array'
            )
        );
        CREATE INDEX ix_historical_incident_source_hash ON historical_incident (source_hash);
        CREATE INDEX ix_historical_incident_reported ON historical_incident (reported_on DESC NULLS LAST, incident_id);
        CREATE INDEX ix_historical_incident_region ON historical_incident (sido_name, sigungu_name, reported_on DESC);
        CREATE INDEX ix_historical_incident_facility ON historical_incident (facility_type, incident_type, reported_on DESC);
        CREATE INDEX ix_historical_incident_categories ON historical_incident USING gin (cause_categories jsonb_path_ops);

        CREATE TABLE public_facility_reference (
            facility_reference_id uuid PRIMARY KEY,
            source_key varchar(64) NOT NULL UNIQUE,
            facility_name text NOT NULL,
            business_type varchar(128),
            building_use varchar(128),
            sido_name varchar(32) NOT NULL,
            sigungu_name varchar(32),
            region_code varchar(10) REFERENCES admin_region(region_code) ON DELETE SET NULL,
            address_summary varchar(96) NOT NULL,
            structure_name varchar(128),
            floor_name varchar(64),
            interior_materials text,
            installation_area_m2 numeric(14, 3),
            registered_on date,
            declared_on date,
            completed_on date,
            closed_on date,
            is_active boolean NOT NULL,
            row_hash char(64) NOT NULL,
            source_version varchar(128) NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_public_facility_region CHECK (sido_name IN ('광주광역시', '전라남도')),
            CONSTRAINT ck_public_facility_hash CHECK (row_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_public_facility_name CHECK (length(trim(facility_name)) > 0),
            CONSTRAINT ck_public_facility_address CHECK (length(trim(address_summary)) > 0),
            CONSTRAINT ck_public_facility_area CHECK (installation_area_m2 IS NULL OR installation_area_m2 >= 0)
        );
        CREATE INDEX ix_public_facility_region ON public_facility_reference (region_code, is_active, building_use);
        CREATE INDEX ix_public_facility_admin_name ON public_facility_reference (sido_name, sigungu_name, is_active);
        CREATE INDEX ix_public_facility_type ON public_facility_reference (building_use, business_type, is_active);
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE IF EXISTS public_facility_reference;
        DROP TABLE IF EXISTS historical_incident;
        """
    )