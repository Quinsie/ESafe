"""Add database guarantees and indexes for deterministic Case automation.

Revision ID: 20260729_0008
Revises: 20260729_0007
Create Date: 2026-07-29 10:55:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0008"
down_revision: str | None = "20260729_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX ux_case_signal_owner
        ON case_signal_link (signal_event_id)
        WHERE link_type IN ('PRIMARY', 'UPDATE', 'MERGED_SOURCE')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_building_centroid_geography_gist
        ON building
        USING gist ((centroid::geography))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_building_centroid_geography_gist")
    op.execute("DROP INDEX IF EXISTS ux_case_signal_owner")
