"""Allow the 100 metre fire impact radius.

Revision ID: 20260730_0019
Revises: 20260730_0018
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0019"
down_revision: str | None = "20260730_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE case_impact_scope
        DROP CONSTRAINT ck_case_impact_scope_radius
        """
    )
    op.execute(
        """
        ALTER TABLE case_impact_scope
        ADD CONSTRAINT ck_case_impact_scope_radius
        CHECK (
            (
                scope_type = 'RADIUS'
                AND center IS NOT NULL
                AND radius_m IN (100, 500, 1000, 3000, 5000)
            )
            OR (scope_type <> 'RADIUS' AND radius_m IS NULL)
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE case_impact_scope
        DROP CONSTRAINT ck_case_impact_scope_radius
        """
    )
    op.execute(
        """
        ALTER TABLE case_impact_scope
        ADD CONSTRAINT ck_case_impact_scope_radius
        CHECK (
            (
                scope_type = 'RADIUS'
                AND center IS NOT NULL
                AND radius_m IN (500, 1000, 3000, 5000)
            )
            OR (scope_type <> 'RADIUS' AND radius_m IS NULL)
        )
        """
    )
