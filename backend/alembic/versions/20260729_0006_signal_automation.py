# ruff: noqa: E501
"""Create lossless signal ingestion and deterministic automation records.

Revision ID: 20260729_0006
Revises: 20260729_0005
Create Date: 2026-07-29 09:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE source_poll (
            poll_id uuid PRIMARY KEY,
            source varchar(32) NOT NULL,
            execution_mode varchar(16) NOT NULL,
            result varchar(24) NOT NULL,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            http_status integer,
            received_count integer NOT NULL DEFAULT 0,
            new_count integer NOT NULL DEFAULT 0,
            updated_count integer NOT NULL DEFAULT 0,
            parser_version varchar(64) NOT NULL,
            response_sha256 char(64),
            error_class varchar(64),
            next_allowed_at timestamptz,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            CONSTRAINT ck_source_poll_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_source_poll_mode CHECK (execution_mode IN ('EXTERNAL', 'FIXTURE')),
            CONSTRAINT ck_source_poll_result CHECK (result IN ('RUNNING', 'SUCCESS', 'EMPTY', 'DELAYED', 'FAILED', 'DISABLED')),
            CONSTRAINT ck_source_poll_http CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
            CONSTRAINT ck_source_poll_counts CHECK (received_count >= 0 AND new_count >= 0 AND updated_count >= 0),
            CONSTRAINT ck_source_poll_hash CHECK (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_source_poll_finished CHECK ((result = 'RUNNING' AND finished_at IS NULL) OR (result <> 'RUNNING' AND finished_at IS NOT NULL))
        );
        CREATE INDEX ix_source_poll_source_started ON source_poll (source, started_at DESC);
        CREATE INDEX ix_source_poll_failures ON source_poll (source, result, started_at DESC) WHERE result IN ('DELAYED', 'FAILED');

        CREATE TABLE raw_signal (
            raw_signal_id uuid PRIMARY KEY,
            poll_id uuid NOT NULL REFERENCES source_poll(poll_id) ON DELETE RESTRICT,
            source varchar(32) NOT NULL,
            external_id text NOT NULL,
            payload_format varchar(16) NOT NULL,
            payload_sha256 char(64) NOT NULL,
            payload_json jsonb,
            payload_text text,
            source_published_at timestamptz,
            fetched_at timestamptz NOT NULL,
            parser_version varchar(64) NOT NULL,
            license_note varchar(256),
            is_simulated boolean NOT NULL DEFAULT false,
            scenario_id uuid,
            CONSTRAINT uq_raw_signal_version UNIQUE (source, external_id, payload_sha256),
            CONSTRAINT ck_raw_signal_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_raw_signal_format CHECK (payload_format IN ('JSON', 'XML', 'HTML')),
            CONSTRAINT ck_raw_signal_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_raw_signal_payload CHECK ((payload_json IS NOT NULL)::integer + (payload_text IS NOT NULL)::integer = 1),
            CONSTRAINT ck_raw_signal_simulation CHECK ((is_simulated AND scenario_id IS NOT NULL) OR (NOT is_simulated AND scenario_id IS NULL))
        );
        CREATE INDEX ix_raw_signal_source_external ON raw_signal (source, external_id, fetched_at DESC);
        CREATE INDEX ix_raw_signal_poll ON raw_signal (poll_id, raw_signal_id);

        CREATE TABLE signal_event (
            signal_event_id uuid PRIMARY KEY,
            source varchar(32) NOT NULL,
            external_id text NOT NULL,
            event_type varchar(32) NOT NULL,
            event_subtype varchar(64),
            severity varchar(32),
            source_status varchar(32) NOT NULL,
            title text NOT NULL,
            summary text,
            source_published_at timestamptz,
            effective_at timestamptz,
            expires_at timestamptz,
            address text,
            normalized_address text,
            region_codes varchar(10)[] NOT NULL DEFAULT '{}',
            region_names text[] NOT NULL DEFAULT '{}',
            location geometry(Point, 4326),
            location_precision varchar(20),
            latest_raw_signal_id uuid NOT NULL REFERENCES raw_signal(raw_signal_id) ON DELETE RESTRICT,
            is_relevant boolean NOT NULL,
            relevance_reason jsonb NOT NULL DEFAULT '{}'::jsonb,
            is_simulated boolean NOT NULL DEFAULT false,
            scenario_id uuid,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_signal_event_source_external UNIQUE (source, external_id),
            CONSTRAINT ck_signal_event_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_signal_event_type CHECK (event_type IN ('FIRE_DISPATCH', 'WEATHER_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_signal_event_status CHECK (source_status IN ('ACTIVE', 'UPDATED', 'RESOLVED', 'UNKNOWN')),
            CONSTRAINT ck_signal_event_precision CHECK (location_precision IS NULL OR location_precision IN ('COORDINATE', 'BUILDING', 'EUPMYEONDONG', 'SIGUNGU', 'SIDO')),
            CONSTRAINT ck_signal_event_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_signal_event_version CHECK (version > 0),
            CONSTRAINT ck_signal_event_region_codes CHECK (cardinality(region_codes) > 0 OR NOT is_relevant),
            CONSTRAINT ck_signal_event_simulation CHECK ((is_simulated AND scenario_id IS NOT NULL) OR (NOT is_simulated AND scenario_id IS NULL)),
            CONSTRAINT ck_signal_event_location CHECK (location IS NULL OR (NOT ST_IsEmpty(location) AND ST_IsValid(location)))
        );
        CREATE INDEX ix_signal_event_source_time ON signal_event (source, source_published_at DESC NULLS LAST, signal_event_id);
        CREATE INDEX ix_signal_event_relevant_active ON signal_event (event_type, updated_at DESC) WHERE is_relevant AND source_status <> 'RESOLVED';
        CREATE INDEX ix_signal_event_regions_gin ON signal_event USING gin (region_codes);
        CREATE INDEX ix_signal_event_location_gist ON signal_event USING gist (location) WHERE location IS NOT NULL;

        CREATE TABLE source_checkpoint (
            source varchar(32) PRIMARY KEY,
            cursor_value text,
            cursor_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_poll_id uuid REFERENCES source_poll(poll_id) ON DELETE SET NULL,
            last_success_at timestamptz,
            last_failure_at timestamptz,
            consecutive_failures integer NOT NULL DEFAULT 0,
            backoff_until timestamptz,
            parser_version varchar(64) NOT NULL,
            contract_version varchar(64) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_source_checkpoint_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_source_checkpoint_failures CHECK (consecutive_failures >= 0)
        );

        CREATE TABLE case_signal_link (
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            signal_event_id uuid NOT NULL REFERENCES signal_event(signal_event_id) ON DELETE RESTRICT,
            link_type varchar(24) NOT NULL,
            is_automated boolean NOT NULL,
            rule_version varchar(64) NOT NULL,
            decision_reason jsonb NOT NULL DEFAULT '{}'::jsonb,
            linked_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (case_id, signal_event_id),
            CONSTRAINT ck_case_signal_link_type CHECK (link_type IN ('PRIMARY', 'UPDATE', 'RELATED', 'MERGED_SOURCE'))
        );
        CREATE INDEX ix_case_signal_event ON case_signal_link (signal_event_id, case_id);

        CREATE TABLE case_relation (
            case_relation_id uuid PRIMARY KEY,
            source_case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            target_case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            relation_type varchar(32) NOT NULL,
            evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_by uuid REFERENCES app_user(user_id) ON DELETE SET NULL,
            resolved_by uuid REFERENCES app_user(user_id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at timestamptz,
            CONSTRAINT uq_case_relation_pair UNIQUE (source_case_id, target_case_id, relation_type),
            CONSTRAINT ck_case_relation_type CHECK (relation_type IN ('POSSIBLE_SAME_EVENT', 'MERGED_INTO', 'RELATED')),
            CONSTRAINT ck_case_relation_not_self CHECK (source_case_id <> target_case_id),
            CONSTRAINT ck_case_relation_resolution CHECK ((resolved_at IS NULL AND resolved_by IS NULL) OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL))
        );
        CREATE INDEX ix_case_relation_target ON case_relation (target_case_id, relation_type, resolved_at);

        CREATE TABLE case_impact_scope (
            impact_scope_id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            scope_type varchar(24) NOT NULL,
            center geometry(Point, 4326),
            radius_m integer,
            region_codes varchar(10)[] NOT NULL DEFAULT '{}',
            precision_warning text,
            rule_version varchar(64) NOT NULL,
            calculated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_case_impact_scope_type CHECK (scope_type IN ('EXACT_BUILDING', 'RADIUS', 'ADMIN_REGION')),
            CONSTRAINT ck_case_impact_scope_radius CHECK ((scope_type = 'RADIUS' AND center IS NOT NULL AND radius_m IN (500, 1000, 3000, 5000)) OR (scope_type <> 'RADIUS' AND radius_m IS NULL)),
            CONSTRAINT ck_case_impact_scope_region CHECK (scope_type <> 'ADMIN_REGION' OR cardinality(region_codes) > 0),
            CONSTRAINT ck_case_impact_scope_center CHECK (center IS NULL OR (NOT ST_IsEmpty(center) AND ST_IsValid(center)))
        );
        CREATE INDEX ix_case_impact_scope_case ON case_impact_scope (case_id, calculated_at DESC);
        CREATE INDEX ix_case_impact_scope_center_gist ON case_impact_scope USING gist (center) WHERE center IS NOT NULL;

        CREATE TABLE case_building (
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            building_id uuid NOT NULL REFERENCES building(building_id) ON DELETE CASCADE,
            risk_snapshot_id uuid NOT NULL REFERENCES building_risk_snapshot(risk_snapshot_id) ON DELETE RESTRICT,
            match_reason varchar(32) NOT NULL,
            distance_m double precision,
            is_incident_building boolean NOT NULL DEFAULT false,
            is_high_risk boolean NOT NULL,
            priority_order integer NOT NULL,
            rule_version varchar(64) NOT NULL,
            calculated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (case_id, building_id),
            CONSTRAINT uq_case_building_priority UNIQUE (case_id, priority_order),
            CONSTRAINT ck_case_building_reason CHECK (match_reason IN ('EXACT', 'RADIUS', 'ADMIN_REGION')),
            CONSTRAINT ck_case_building_distance CHECK (distance_m IS NULL OR distance_m >= 0),
            CONSTRAINT ck_case_building_priority CHECK (priority_order > 0),
            CONSTRAINT ck_case_building_incident_order CHECK (NOT is_incident_building OR priority_order = 1)
        );
        CREATE INDEX ix_case_building_priority ON case_building (case_id, priority_order, building_id);
        CREATE INDEX ix_case_building_high_risk ON case_building (case_id, is_high_risk, priority_order) WHERE is_high_risk;

        CREATE TABLE automation_run (
            automation_run_id uuid PRIMARY KEY,
            profile varchar(8) NOT NULL,
            run_type varchar(64) NOT NULL,
            trigger_type varchar(24) NOT NULL,
            status varchar(24) NOT NULL,
            source varchar(32),
            case_id uuid REFERENCES case_record(case_id) ON DELETE SET NULL,
            work_item_id uuid REFERENCES work_item(work_item_id) ON DELETE SET NULL,
            input_version varchar(128),
            output_version varchar(128),
            rule_version varchar(64) NOT NULL,
            retry_count integer NOT NULL DEFAULT 0,
            error_class varchar(64),
            idempotency_key varchar(160) NOT NULL UNIQUE,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_automation_run_profile CHECK (profile IN ('LIVE', 'DEMO')),
            CONSTRAINT ck_automation_run_trigger CHECK (trigger_type IN ('SCHEDULED', 'EVENT', 'USER', 'RETRY')),
            CONSTRAINT ck_automation_run_status CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
            CONSTRAINT ck_automation_run_source CHECK (source IS NULL OR source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_automation_run_retry CHECK (retry_count >= 0),
            CONSTRAINT ck_automation_run_finished CHECK ((status = 'RUNNING' AND finished_at IS NULL) OR (status <> 'RUNNING' AND finished_at IS NOT NULL))
        );
        CREATE INDEX ix_automation_run_started ON automation_run (started_at DESC, automation_run_id);
        CREATE INDEX ix_automation_run_case ON automation_run (case_id, started_at DESC) WHERE case_id IS NOT NULL;
        CREATE INDEX ix_automation_run_failure ON automation_run (run_type, started_at DESC) WHERE status = 'FAILED';

        CREATE TABLE audit_event (
            audit_event_id uuid PRIMARY KEY,
            profile varchar(8) NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor_type varchar(16) NOT NULL,
            actor_user_id uuid REFERENCES app_user(user_id) ON DELETE SET NULL,
            action varchar(64) NOT NULL,
            target_type varchar(64) NOT NULL,
            target_id text NOT NULL,
            target_version integer,
            before_state jsonb,
            after_state jsonb,
            reason jsonb NOT NULL DEFAULT '{}'::jsonb,
            correlation_id uuid NOT NULL,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            input_sha256 char(64),
            output_sha256 char(64),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_audit_event_profile CHECK (profile IN ('LIVE', 'DEMO')),
            CONSTRAINT ck_audit_event_actor CHECK (actor_type IN ('SYSTEM', 'USER')),
            CONSTRAINT ck_audit_event_actor_user CHECK ((actor_type = 'USER' AND actor_user_id IS NOT NULL) OR actor_type = 'SYSTEM'),
            CONSTRAINT ck_audit_event_target CHECK (length(trim(target_type)) > 0 AND length(trim(target_id)) > 0),
            CONSTRAINT ck_audit_event_input_hash CHECK (input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_audit_event_output_hash CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$')
        );
        CREATE INDEX ix_audit_event_target ON audit_event (target_type, target_id, occurred_at DESC);
        CREATE INDEX ix_audit_event_correlation ON audit_event (correlation_id, occurred_at);
        CREATE INDEX ix_audit_event_occurred ON audit_event (occurred_at DESC, audit_event_id);
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE IF EXISTS audit_event;
        DROP TABLE IF EXISTS automation_run;
        DROP TABLE IF EXISTS case_building;
        DROP TABLE IF EXISTS case_impact_scope;
        DROP TABLE IF EXISTS case_relation;
        DROP TABLE IF EXISTS case_signal_link;
        DROP TABLE IF EXISTS source_checkpoint;
        DROP TABLE IF EXISTS signal_event;
        DROP TABLE IF EXISTS raw_signal;
        DROP TABLE IF EXISTS source_poll;
        """
    )
