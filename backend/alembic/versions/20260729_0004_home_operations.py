# ruff: noqa: E501
"""Create the operational records required by the home briefing.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29 06:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0004"
down_revision: str | None = "20260729_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE source_health (
            source varchar(32) PRIMARY KEY,
            execution_mode varchar(16) NOT NULL,
            enabled boolean NOT NULL,
            status varchar(16) NOT NULL,
            last_attempt_at timestamptz,
            last_success_at timestamptz,
            last_failure_at timestamptz,
            consecutive_failures integer NOT NULL DEFAULT 0,
            next_poll_at timestamptz,
            backoff_until timestamptz,
            last_http_status integer,
            last_error_code varchar(64),
            parser_version varchar(64) NOT NULL,
            contract_version varchar(64) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_source_health_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_source_health_mode CHECK (execution_mode IN ('EXTERNAL', 'FIXTURE')),
            CONSTRAINT ck_source_health_status CHECK (status IN ('HEALTHY', 'DELAYED', 'OUTAGE', 'DISABLED')),
            CONSTRAINT ck_source_health_failure_count CHECK (consecutive_failures >= 0),
            CONSTRAINT ck_source_health_http_status CHECK (last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599),
            CONSTRAINT ck_source_health_disabled CHECK (enabled OR status = 'DISABLED')
        );
        CREATE INDEX ix_source_health_status ON source_health (status, updated_at);

        CREATE TABLE case_record (
            case_id uuid PRIMARY KEY,
            case_number varchar(32) NOT NULL UNIQUE,
            case_type varchar(32) NOT NULL,
            title text NOT NULL,
            status varchar(32) NOT NULL,
            source_status varchar(64) NOT NULL,
            monitoring_priority varchar(16) NOT NULL DEFAULT 'NORMAL',
            primary_region_code varchar(10) REFERENCES admin_region(region_code),
            location geometry(Point, 4326),
            normalized_address text,
            location_precision varchar(20),
            opened_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            source_resolved_at timestamptz,
            closed_at timestamptz,
            close_reason varchar(32),
            is_simulated boolean NOT NULL DEFAULT false,
            scenario_id uuid,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT ck_case_record_status CHECK (status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW', 'CLOSED', 'MERGED')),
            CONSTRAINT ck_case_record_priority CHECK (monitoring_priority IN ('NORMAL', 'ATTENTION', 'URGENT')),
            CONSTRAINT ck_case_record_precision CHECK (location_precision IS NULL OR location_precision IN ('COORDINATE', 'BUILDING', 'EUPMYEONDONG', 'SIGUNGU', 'SIDO')),
            CONSTRAINT ck_case_record_version CHECK (version > 0),
            CONSTRAINT ck_case_record_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_case_record_number CHECK (length(trim(case_number)) > 0),
            CONSTRAINT ck_case_record_simulation CHECK ((is_simulated AND scenario_id IS NOT NULL) OR (NOT is_simulated AND scenario_id IS NULL)),
            CONSTRAINT ck_case_record_close_time CHECK ((status = 'CLOSED' AND closed_at IS NOT NULL) OR (status <> 'CLOSED' AND closed_at IS NULL)),
            CONSTRAINT ck_case_record_resolved_time CHECK (source_resolved_at IS NULL OR source_resolved_at >= opened_at),
            CONSTRAINT ck_case_record_location CHECK (location IS NULL OR (NOT ST_IsEmpty(location) AND ST_IsValid(location)))
        );
        CREATE INDEX ix_case_record_status_updated ON case_record (status, updated_at DESC);
        CREATE INDEX ix_case_record_type_opened ON case_record (case_type, opened_at DESC);
        CREATE INDEX ix_case_record_region ON case_record (primary_region_code, updated_at DESC);
        CREATE INDEX ix_case_record_priority ON case_record (monitoring_priority, updated_at DESC) WHERE status IN ('DETECTED', 'ACTIVE', 'ON_HOLD', 'SOURCE_RESOLVED_REVIEW');
        CREATE INDEX ix_case_record_location_gist ON case_record USING gist (location) WHERE location IS NOT NULL;

        CREATE TABLE work_item (
            work_item_id uuid PRIMARY KEY,
            work_type varchar(64) NOT NULL,
            case_id uuid REFERENCES case_record(case_id) ON DELETE CASCADE,
            status varchar(32) NOT NULL,
            priority varchar(16) NOT NULL DEFAULT 'NORMAL',
            title text NOT NULL,
            input_version varchar(128),
            output_version varchar(128),
            due_at timestamptz,
            progress smallint NOT NULL DEFAULT 0,
            error_class varchar(64),
            retry_count integer NOT NULL DEFAULT 0,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_work_item_status CHECK (status IN ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'ON_HOLD', 'COMPLETED', 'DISCARDED', 'FAILED')),
            CONSTRAINT ck_work_item_priority CHECK (priority IN ('NORMAL', 'HIGH', 'URGENT')),
            CONSTRAINT ck_work_item_progress CHECK (progress BETWEEN 0 AND 100),
            CONSTRAINT ck_work_item_retry_count CHECK (retry_count >= 0),
            CONSTRAINT ck_work_item_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_work_item_key CHECK (length(trim(idempotency_key)) > 0),
            CONSTRAINT ck_work_item_completion CHECK ((status = 'COMPLETED' AND completed_at IS NOT NULL) OR status <> 'COMPLETED')
        );
        CREATE INDEX ix_work_item_status_due ON work_item (status, due_at, created_at);
        CREATE INDEX ix_work_item_case_updated ON work_item (case_id, updated_at DESC) WHERE case_id IS NOT NULL;
        CREATE INDEX ix_work_item_active_priority ON work_item (priority, due_at, created_at) WHERE status IN ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'ON_HOLD', 'FAILED');
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE IF EXISTS work_item;
        DROP TABLE IF EXISTS case_record;
        DROP TABLE IF EXISTS source_health;
        """
    )