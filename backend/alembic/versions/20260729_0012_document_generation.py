"""Create versioned document generation and manual delivery records.

Revision ID: 20260729_0012
Revises: 20260729_0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0012"
down_revision: str | None = "20260729_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_draft (
            document_draft_id uuid PRIMARY KEY,
            case_id uuid REFERENCES case_record(case_id) ON DELETE RESTRICT,
            family varchar(32) NOT NULL,
            variant varchar(32) NOT NULL,
            title text NOT NULL,
            status varchar(24) NOT NULL,
            current_version integer NOT NULL,
            created_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT ck_document_draft_family CHECK (
                family IN ('SITUATION_REPORT', 'OFFICIAL_NOTICE', 'RESPONSE_PLAN')
            ),
            CONSTRAINT ck_document_draft_variant CHECK (
                variant IN (
                    'INCIDENT_REPORT',
                    'CRISIS_ASSESSMENT',
                    'BASIC_NOTICE',
                    'BASIC_PLAN'
                )
            ),
            CONSTRAINT ck_document_draft_family_variant CHECK (
                (family = 'SITUATION_REPORT'
                    AND variant IN ('INCIDENT_REPORT', 'CRISIS_ASSESSMENT'))
                OR (family = 'OFFICIAL_NOTICE' AND variant = 'BASIC_NOTICE')
                OR (family = 'RESPONSE_PLAN' AND variant = 'BASIC_PLAN')
            ),
            CONSTRAINT ck_document_draft_status CHECK (
                status IN (
                    'DRAFT', 'APPROVAL_PENDING', 'APPROVED',
                    'ON_HOLD', 'DISCARDED'
                )
            ),
            CONSTRAINT ck_document_draft_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_document_draft_versions CHECK (
                current_version > 0 AND version > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_draft_case
        ON document_draft (case_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_draft_library
        ON document_draft (family, status, updated_at DESC, document_draft_id)
        """
    )
    op.execute(
        """
        CREATE TABLE document_version (
            document_version_id uuid PRIMARY KEY,
            document_draft_id uuid NOT NULL
                REFERENCES document_draft(document_draft_id) ON DELETE RESTRICT,
            version integer NOT NULL,
            parent_version_id uuid
                REFERENCES document_version(document_version_id) ON DELETE RESTRICT,
            status varchar(24) NOT NULL,
            structured_payload jsonb NOT NULL,
            evidence_status varchar(16) NOT NULL,
            warning text,
            content_sha256 char(64) NOT NULL,
            template_key varchar(64) NOT NULL,
            template_version varchar(64) NOT NULL,
            template_sha256 char(64) NOT NULL,
            warning_acknowledged boolean NOT NULL DEFAULT false,
            approval_reason text,
            created_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_by uuid REFERENCES app_user(user_id) ON DELETE RESTRICT,
            approved_at timestamptz,
            superseded_at timestamptz,
            CONSTRAINT uq_document_version UNIQUE (document_draft_id, version),
            CONSTRAINT ck_document_version_number CHECK (version > 0),
            CONSTRAINT ck_document_version_status CHECK (
                status IN (
                    'DRAFT', 'APPROVAL_PENDING', 'APPROVED',
                    'ON_HOLD', 'DISCARDED', 'SUPERSEDED'
                )
            ),
            CONSTRAINT ck_document_version_payload CHECK (
                jsonb_typeof(structured_payload) = 'object'
            ),
            CONSTRAINT ck_document_version_evidence CHECK (
                evidence_status IN ('SUFFICIENT', 'INSUFFICIENT', 'CONFLICT')
            ),
            CONSTRAINT ck_document_version_hashes CHECK (
                content_sha256 ~ '^[0-9a-f]{64}$'
                AND template_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_document_version_template CHECK (
                length(trim(template_key)) > 0
                AND length(trim(template_version)) > 0
            ),
            CONSTRAINT ck_document_version_approval CHECK (
                (
                    status = 'APPROVED'
                    AND approved_by IS NOT NULL
                    AND approved_at IS NOT NULL
                    AND approval_reason IS NOT NULL
                    AND length(trim(approval_reason)) > 0
                )
                OR status <> 'APPROVED'
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_version_draft
        ON document_version (document_draft_id, version DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_document_version_approved
        ON document_version (document_draft_id)
        WHERE status = 'APPROVED'
        """
    )
    op.execute(
        """
        CREATE TABLE document_artifact (
            document_artifact_id uuid PRIMARY KEY,
            document_version_id uuid NOT NULL
                REFERENCES document_version(document_version_id) ON DELETE RESTRICT,
            format varchar(8) NOT NULL,
            stage varchar(12) NOT NULL,
            status varchar(16) NOT NULL,
            attempt_count integer NOT NULL DEFAULT 0,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            storage_path text,
            file_name text,
            mime_type varchar(80),
            size_bytes bigint,
            sha256 char(64),
            validation jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_code varchar(80),
            error_message text,
            queued_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT ck_document_artifact_format CHECK (
                format IN ('HWPX', 'PDF')
            ),
            CONSTRAINT ck_document_artifact_stage CHECK (
                stage IN ('REVIEW', 'FINAL')
            ),
            CONSTRAINT ck_document_artifact_status CHECK (
                status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')
            ),
            CONSTRAINT ck_document_artifact_attempt CHECK (
                attempt_count >= 0
            ),
            CONSTRAINT ck_document_artifact_validation CHECK (
                jsonb_typeof(validation) = 'object'
            ),
            CONSTRAINT ck_document_artifact_path CHECK (
                storage_path IS NULL
                OR (
                    storage_path !~ '(^/|(^|/)\\.\\.(/|$))'
                    AND storage_path !~ '\\\\'
                )
            ),
            CONSTRAINT ck_document_artifact_hash CHECK (
                sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_document_artifact_size CHECK (
                size_bytes IS NULL OR size_bytes > 0
            ),
            CONSTRAINT ck_document_artifact_success CHECK (
                (
                    status = 'SUCCEEDED'
                    AND storage_path IS NOT NULL
                    AND file_name IS NOT NULL
                    AND mime_type IS NOT NULL
                    AND size_bytes IS NOT NULL
                    AND sha256 IS NOT NULL
                    AND finished_at IS NOT NULL
                )
                OR status <> 'SUCCEEDED'
            ),
            CONSTRAINT ck_document_artifact_failure CHECK (
                (
                    status = 'FAILED'
                    AND error_code IS NOT NULL
                    AND error_message IS NOT NULL
                    AND finished_at IS NOT NULL
                )
                OR status <> 'FAILED'
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_document_artifact_success
        ON document_artifact (document_version_id, format, stage)
        WHERE status = 'SUCCEEDED'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_artifact_status
        ON document_artifact (status, queued_at, document_artifact_id)
        """
    )
    op.execute(
        """
        CREATE TABLE document_manual_delivery (
            document_manual_delivery_id uuid PRIMARY KEY,
            document_version_id uuid NOT NULL
                REFERENCES document_version(document_version_id) ON DELETE RESTRICT,
            recipient text NOT NULL,
            delivered_at timestamptz NOT NULL,
            method varchar(24) NOT NULL,
            memo text,
            recorded_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            CONSTRAINT ck_document_manual_delivery_recipient CHECK (
                length(trim(recipient)) > 0
            ),
            CONSTRAINT ck_document_manual_delivery_method CHECK (
                method IN (
                    'EMAIL', 'MESSENGER', 'E_DOCUMENT',
                    'IN_PERSON', 'OTHER'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_manual_delivery_version
        ON document_manual_delivery (document_version_id, delivered_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_manual_delivery")
    op.execute("DROP TABLE IF EXISTS document_artifact")
    op.execute("DROP TABLE IF EXISTS document_version")
    op.execute("DROP TABLE IF EXISTS document_draft")
