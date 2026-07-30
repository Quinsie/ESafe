"""Allow standalone region, building, and inspection documents.

Revision ID: 20260729_0016
Revises: 20260729_0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0016"
down_revision: str | None = "20260729_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_draft DROP CONSTRAINT ck_document_draft_family_variant"
    )
    op.execute("ALTER TABLE document_draft DROP CONSTRAINT ck_document_draft_variant")
    op.execute(
        """
        ALTER TABLE document_draft ADD CONSTRAINT ck_document_draft_variant CHECK (
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
        ALTER TABLE document_draft ADD CONSTRAINT ck_document_draft_family_variant CHECK (
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


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM document_draft
                WHERE variant IN (
                    'REGION_ANALYSIS',
                    'BUILDING_ANALYSIS',
                    'INSPECTION_REQUEST'
                )
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade while standalone document drafts exist';
            END IF;
        END
        $$
        """
    )
    op.execute(
        "ALTER TABLE document_draft DROP CONSTRAINT ck_document_draft_family_variant"
    )
    op.execute("ALTER TABLE document_draft DROP CONSTRAINT ck_document_draft_variant")
    op.execute(
        """
        ALTER TABLE document_draft ADD CONSTRAINT ck_document_draft_variant CHECK (
            variant IN (
                'INCIDENT_REPORT',
                'CRISIS_ASSESSMENT',
                'BASIC_NOTICE',
                'BASIC_PLAN'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE document_draft ADD CONSTRAINT ck_document_draft_family_variant CHECK (
            (
                family = 'SITUATION_REPORT'
                AND variant IN ('INCIDENT_REPORT', 'CRISIS_ASSESSMENT')
            )
            OR (family = 'OFFICIAL_NOTICE' AND variant = 'BASIC_NOTICE')
            OR (family = 'RESPONSE_PLAN' AND variant = 'BASIC_PLAN')
        )
        """
    )
