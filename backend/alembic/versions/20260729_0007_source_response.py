# ruff: noqa: E501
"""Preserve each upstream response once before record extraction.

Revision ID: 20260729_0007
Revises: 20260729_0006
Create Date: 2026-07-29 09:40:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0007"
down_revision: str | None = "20260729_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE source_response (
            source_response_id uuid PRIMARY KEY,
            poll_id uuid NOT NULL REFERENCES source_poll(poll_id) ON DELETE RESTRICT,
            source varchar(32) NOT NULL,
            response_label varchar(160) NOT NULL,
            payload_format varchar(16) NOT NULL,
            payload_sha256 char(64) NOT NULL,
            payload_json jsonb,
            payload_text text,
            content_type varchar(160),
            request_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            fetched_at timestamptz NOT NULL,
            CONSTRAINT uq_source_response_poll_label UNIQUE (poll_id, response_label),
            CONSTRAINT ck_source_response_source CHECK (source IN ('NFDS', 'KMA_WARNING', 'DISASTER_MESSAGE')),
            CONSTRAINT ck_source_response_format CHECK (payload_format IN ('JSON', 'HTML')),
            CONSTRAINT ck_source_response_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_source_response_payload CHECK ((payload_json IS NOT NULL)::integer + (payload_text IS NOT NULL)::integer = 1)
        );
        CREATE INDEX ix_source_response_source_time ON source_response (source, fetched_at DESC);
        ALTER TABLE raw_signal ADD COLUMN source_response_id uuid REFERENCES source_response(source_response_id) ON DELETE RESTRICT;
        CREATE INDEX ix_raw_signal_response ON raw_signal (source_response_id, raw_signal_id) WHERE source_response_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP INDEX IF EXISTS ix_raw_signal_response;
        ALTER TABLE raw_signal DROP COLUMN IF EXISTS source_response_id;
        DROP TABLE IF EXISTS source_response;
        """
    )
