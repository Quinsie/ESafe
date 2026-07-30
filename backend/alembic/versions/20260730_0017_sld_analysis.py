"""Add Upstage-only single-line diagram analyses.

Revision ID: 20260730_0017
Revises: 20260729_0016
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0017"
down_revision: str | None = "20260729_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(sql: str) -> None:
    for statement in sql.split(chr(59)):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE sld_analysis (
            sld_analysis_id uuid PRIMARY KEY,
            building_id uuid NOT NULL
                REFERENCES building(building_id) ON DELETE RESTRICT,
            profile varchar(8) NOT NULL,
            status varchar(24) NOT NULL,
            source_file_name text NOT NULL,
            source_mime_type varchar(80) NOT NULL,
            source_size_bytes bigint NOT NULL,
            source_sha256 char(64) NOT NULL,
            source_storage_path text NOT NULL,
            ocr_provider varchar(32) NOT NULL DEFAULT 'UPSTAGE_DOCUMENT_OCR',
            ocr_model varchar(80) NOT NULL,
            grammar_version varchar(80) NOT NULL,
            explanation_model varchar(80),
            result_json jsonb,
            error_code varchar(80),
            error_message text,
            idempotency_key varchar(160) NOT NULL,
            created_by uuid NOT NULL
                REFERENCES app_user(user_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT uq_sld_analysis_idempotency UNIQUE (profile, idempotency_key),
            CONSTRAINT ck_sld_analysis_profile CHECK (profile IN ('LIVE', 'DEMO')),
            CONSTRAINT ck_sld_analysis_status CHECK (
                status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'REVIEW_REQUIRED', 'FAILED')
            ),
            CONSTRAINT ck_sld_analysis_source CHECK (
                source_size_bytes > 0
                AND source_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_sld_analysis_provider CHECK (
                ocr_provider = 'UPSTAGE_DOCUMENT_OCR'
            ),
            CONSTRAINT ck_sld_analysis_result CHECK (
                result_json IS NULL OR jsonb_typeof(result_json) = 'object'
            ),
            CONSTRAINT ck_sld_analysis_error CHECK (
                (status = 'FAILED' AND error_code IS NOT NULL AND error_message IS NOT NULL)
                OR (status <> 'FAILED' AND error_code IS NULL AND error_message IS NULL)
            ),
            CONSTRAINT ck_sld_analysis_version CHECK (version > 0)
        );
        CREATE INDEX ix_sld_analysis_building
        ON sld_analysis (building_id, created_at DESC);
        CREATE INDEX ix_sld_analysis_status
        ON sld_analysis (status, updated_at);
        CREATE INDEX ix_sld_analysis_source_hash
        ON sld_analysis (profile, building_id, source_sha256, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sld_analysis")
