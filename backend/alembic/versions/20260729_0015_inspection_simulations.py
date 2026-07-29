"""Create deterministic inspection simulations and approval targets.

Revision ID: 20260729_0015
Revises: 20260729_0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0015"
down_revision: str | None = "20260729_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(sql: str) -> None:
    for statement in sql.split(chr(59)):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE inspection_simulation (
            inspection_simulation_id uuid PRIMARY KEY,
            region_code varchar(10) REFERENCES admin_region(region_code),
            building_id uuid REFERENCES building(building_id) ON DELETE RESTRICT,
            case_id uuid REFERENCES case_record(case_id) ON DELETE RESTRICT,
            facility_types text[] NOT NULL DEFAULT ARRAY[]::text[],
            start_date date NOT NULL,
            end_date date NOT NULL,
            team_count integer NOT NULL,
            daily_capacity_per_team integer NOT NULL,
            inclusive_day_count integer NOT NULL,
            total_capacity integer NOT NULL,
            top_percentile double precision NOT NULL,
            minimum_score double precision NOT NULL,
            expanded_top_percentile double precision NOT NULL,
            expanded_minimum_score double precision NOT NULL,
            reference_month date NOT NULL,
            horizon_days smallint NOT NULL,
            lineage_version text NOT NULL,
            manifest_hash char(64) NOT NULL,
            algorithm_version varchar(64) NOT NULL,
            input_sha256 char(64) NOT NULL,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            status varchar(24) NOT NULL,
            selected_scenario_id uuid,
            error_code varchar(80),
            error_message text,
            created_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT ck_inspection_simulation_dates CHECK (end_date >= start_date),
            CONSTRAINT ck_inspection_simulation_capacity CHECK (
                team_count > 0 AND daily_capacity_per_team > 0
                AND inclusive_day_count > 0
                AND total_capacity = inclusive_day_count * team_count * daily_capacity_per_team
            ),
            CONSTRAINT ck_inspection_simulation_filters CHECK (
                top_percentile > 0 AND top_percentile <= 100
                AND minimum_score >= 0 AND minimum_score <= 1
                AND expanded_top_percentile >= top_percentile
                AND expanded_top_percentile <= 100
                AND expanded_minimum_score >= 0
                AND expanded_minimum_score <= minimum_score
            ),
            CONSTRAINT ck_inspection_simulation_snapshot CHECK (
                reference_month = DATE '2026-03-01'
                AND horizon_days = 60
                AND manifest_hash ~ '^[0-9a-f]{64}$'
                AND input_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_inspection_simulation_status CHECK (
                status IN (
                    'QUEUED', 'RUNNING', 'CALCULATED', 'APPROVAL_PENDING',
                    'APPROVED', 'ON_HOLD', 'DISCARDED', 'FAILED'
                )
            ),
            CONSTRAINT ck_inspection_simulation_version CHECK (version > 0),
            CONSTRAINT ck_inspection_simulation_error CHECK (
                (status = 'FAILED' AND error_code IS NOT NULL AND error_message IS NOT NULL)
                OR status <> 'FAILED'
            )
        );
        CREATE INDEX ix_inspection_simulation_created
        ON inspection_simulation (created_at DESC, inspection_simulation_id);

        CREATE TABLE inspection_scenario (
            inspection_scenario_id uuid PRIMARY KEY,
            inspection_simulation_id uuid NOT NULL
                REFERENCES inspection_simulation(inspection_simulation_id) ON DELETE CASCADE,
            scenario_type varchar(32) NOT NULL,
            ordinal smallint NOT NULL,
            status varchar(24) NOT NULL,
            candidate_count integer NOT NULL,
            selected_count integer NOT NULL,
            excluded_count integer NOT NULL,
            candidate_coverage_percent double precision NOT NULL,
            required_days integer NOT NULL,
            over_capacity boolean NOT NULL,
            confirmable boolean NOT NULL,
            explanation jsonb NOT NULL,
            content_sha256 char(64) NOT NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inspection_scenario_type UNIQUE (
                inspection_simulation_id, scenario_type
            ),
            CONSTRAINT uq_inspection_scenario_ordinal UNIQUE (
                inspection_simulation_id, ordinal
            ),
            CONSTRAINT ck_inspection_scenario_type CHECK (
                scenario_type IN (
                    'BALANCED', 'HIGH_RISK_FOCUSED', 'COVERAGE_EXPANDED'
                )
            ),
            CONSTRAINT ck_inspection_scenario_status CHECK (
                status IN (
                    'CALCULATED', 'APPROVAL_PENDING', 'APPROVED',
                    'ON_HOLD', 'DISCARDED'
                )
            ),
            CONSTRAINT ck_inspection_scenario_counts CHECK (
                candidate_count >= 0 AND selected_count >= 0 AND excluded_count >= 0
                AND candidate_count = selected_count + excluded_count
            ),
            CONSTRAINT ck_inspection_scenario_coverage CHECK (
                candidate_coverage_percent >= 0 AND candidate_coverage_percent <= 100
            ),
            CONSTRAINT ck_inspection_scenario_days CHECK (required_days >= 0),
            CONSTRAINT ck_inspection_scenario_confirmable CHECK (
                confirmable = (NOT over_capacity AND selected_count > 0)
            ),
            CONSTRAINT ck_inspection_scenario_explanation CHECK (
                jsonb_typeof(explanation) = 'object'
            ),
            CONSTRAINT ck_inspection_scenario_hash CHECK (
                content_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_inspection_scenario_version CHECK (version > 0)
        );
        CREATE INDEX ix_inspection_scenario_simulation
        ON inspection_scenario (inspection_simulation_id, ordinal);

        ALTER TABLE inspection_simulation
        ADD CONSTRAINT fk_inspection_selected_scenario
        FOREIGN KEY (selected_scenario_id)
        REFERENCES inspection_scenario(inspection_scenario_id) ON DELETE RESTRICT;

        CREATE TABLE inspection_target (
            inspection_target_id uuid PRIMARY KEY,
            inspection_scenario_id uuid NOT NULL
                REFERENCES inspection_scenario(inspection_scenario_id) ON DELETE CASCADE,
            building_id uuid NOT NULL REFERENCES building(building_id) ON DELETE RESTRICT,
            risk_snapshot_id uuid NOT NULL
                REFERENCES building_risk_snapshot(risk_snapshot_id) ON DELETE RESTRICT,
            included boolean NOT NULL,
            selection_order integer,
            team_number integer,
            selection_reason varchar(64),
            exclusion_reason varchar(64),
            region_code varchar(10) NOT NULL,
            region_name text NOT NULL,
            facility_type text NOT NULL,
            final_score double precision NOT NULL,
            regional_rank integer NOT NULL,
            top_percentile double precision NOT NULL,
            CONSTRAINT uq_inspection_target_building UNIQUE (
                inspection_scenario_id, building_id
            ),
            CONSTRAINT ck_inspection_target_order CHECK (
                (included AND selection_order > 0 AND team_number > 0
                    AND selection_reason IS NOT NULL AND exclusion_reason IS NULL)
                OR (NOT included AND selection_order IS NULL AND team_number IS NULL
                    AND selection_reason IS NULL AND exclusion_reason IS NOT NULL)
            ),
            CONSTRAINT ck_inspection_target_score CHECK (
                final_score >= 0 AND final_score <= 1
                AND regional_rank > 0
                AND top_percentile > 0 AND top_percentile <= 100
            )
        );
        CREATE UNIQUE INDEX ux_inspection_target_order
        ON inspection_target (inspection_scenario_id, selection_order)
        WHERE selection_order IS NOT NULL;
        CREATE INDEX ix_inspection_target_list
        ON inspection_target (
            inspection_scenario_id, included DESC,
            selection_order, final_score DESC, building_id
        );

        CREATE TABLE inspection_team_work_item (
            inspection_scenario_id uuid NOT NULL
                REFERENCES inspection_scenario(inspection_scenario_id) ON DELETE RESTRICT,
            team_number integer NOT NULL,
            work_item_id uuid NOT NULL REFERENCES work_item(work_item_id) ON DELETE RESTRICT,
            PRIMARY KEY (inspection_scenario_id, team_number),
            CONSTRAINT uq_inspection_team_work_item UNIQUE (work_item_id),
            CONSTRAINT ck_inspection_team_number CHECK (team_number > 0)
        );

        ALTER TABLE approval_request DROP CONSTRAINT ck_approval_request_target;
        ALTER TABLE approval_request ADD CONSTRAINT ck_approval_request_target CHECK (
            target_type IN (
                'RECOMMENDATION', 'WORK_ITEM', 'DOCUMENT_DRAFT',
                'CLOSURE', 'INSPECTION_SCENARIO'
            )
        );
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        ALTER TABLE approval_request DROP CONSTRAINT ck_approval_request_target;
        ALTER TABLE approval_request ADD CONSTRAINT ck_approval_request_target CHECK (
            target_type IN ('RECOMMENDATION', 'WORK_ITEM', 'DOCUMENT_DRAFT', 'CLOSURE')
        );
        DROP TABLE IF EXISTS inspection_team_work_item;
        DROP TABLE IF EXISTS inspection_target;
        ALTER TABLE inspection_simulation
            DROP CONSTRAINT IF EXISTS fk_inspection_selected_scenario;
        DROP TABLE IF EXISTS inspection_scenario;
        DROP TABLE IF EXISTS inspection_simulation;
        """
    )
