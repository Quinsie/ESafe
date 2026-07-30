"""Restore standalone document variant constraints.

Revision ID: 20260731_0020
Revises: 20260730_0019
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0020"
down_revision: str | None = "20260730_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restore_constraints() -> None:
    op.execute(
        """
        ALTER TABLE document_draft
        DROP CONSTRAINT IF EXISTS ck_document_draft_family_variant
        """
    )
    op.execute(
        """
        ALTER TABLE document_draft
        DROP CONSTRAINT IF EXISTS ck_document_draft_variant
        """
    )
    op.execute(
        """
        ALTER TABLE document_draft
        ADD CONSTRAINT ck_document_draft_variant CHECK (
            variant IN (
                'INCIDENT_REPORT',
                'CRISIS_ASSESSMENT',
                'BASIC_NOTICE',
                'BASIC_PLAN',
                'REGION_ANALYSIS',
                'BUILDING_ANALYSIS',
                'INSPECTION_REQUEST'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE document_draft
        ADD CONSTRAINT ck_document_draft_family_variant CHECK (
            (
                family = 'SITUATION_REPORT'
                AND variant IN (
                    'INCIDENT_REPORT',
                    'CRISIS_ASSESSMENT',
                    'REGION_ANALYSIS',
                    'BUILDING_ANALYSIS'
                )
            )
            OR (
                family = 'OFFICIAL_NOTICE'
                AND variant IN ('BASIC_NOTICE', 'INSPECTION_REQUEST')
            )
            OR (family = 'RESPONSE_PLAN' AND variant = 'BASIC_PLAN')
        )
        """
    )


def upgrade() -> None:
    _restore_constraints()


def downgrade() -> None:
    # Revision 20260729_0016 already defines these constraints. Keeping them is
    # the correct schema when downgrading to 20260730_0019.
    pass
