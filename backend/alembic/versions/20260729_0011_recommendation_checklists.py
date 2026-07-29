"""Add validated checklist templates to recommendation actions.

Revision ID: 20260729_0011
Revises: 20260729_0010
"""

from alembic import op

revision = "20260729_0011"
down_revision = "20260729_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE recommendation_action
        ADD COLUMN checklist_template jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE recommendation_action
        ADD CONSTRAINT ck_recommendation_action_checklist
        CHECK (
            jsonb_typeof(checklist_template) = 'array'
            AND jsonb_array_length(checklist_template) <= 12
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_recommendation_input
        ON recommendation (case_id, input_sha256, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_recommendation_input")
    op.execute(
        "ALTER TABLE recommendation_action "
        "DROP CONSTRAINT IF EXISTS ck_recommendation_action_checklist"
    )
    op.execute(
        "ALTER TABLE recommendation_action "
        "DROP COLUMN IF EXISTS checklist_template"
    )
