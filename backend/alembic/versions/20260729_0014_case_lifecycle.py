"""Add transaction-safe human Case number counters.

Revision ID: 20260729_0014
Revises: 20260729_0013
Create Date: 2026-07-29 20:05:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0014"
down_revision: str | None = "20260729_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE case_number_counter (
            business_date date PRIMARY KEY,
            last_value integer NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_case_number_counter_positive CHECK (last_value > 0)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE case_record
        ADD CONSTRAINT ck_case_record_number_format CHECK (
            case_number ~ '^(ES|DEMO)-[0-9]{8}-[0-9]{6}$'
        ) NOT VALID
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE case_record DROP CONSTRAINT IF EXISTS ck_case_record_number_format"
    )
    op.execute("DROP TABLE IF EXISTS case_number_counter")
