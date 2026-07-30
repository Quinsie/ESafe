"""Add managed single-line diagrams for buildings.

Revision ID: 20260730_0018
Revises: 20260730_0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0018"
down_revision: str | None = "20260730_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(sql: str) -> None:
    for statement in sql.split(chr(59)):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE building_sld_document (
            building_sld_document_id uuid PRIMARY KEY,
            building_id uuid NOT NULL
                REFERENCES building(building_id) ON DELETE CASCADE,
            profile varchar(8) NOT NULL,
            source_file_name text NOT NULL,
            source_mime_type varchar(80) NOT NULL,
            source_size_bytes bigint NOT NULL,
            source_sha256 char(64) NOT NULL,
            source_storage_path text NOT NULL,
            document_origin varchar(24) NOT NULL DEFAULT 'MANAGER_UPLOAD',
            uploaded_by uuid
                REFERENCES app_user(user_id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT uq_building_sld_document UNIQUE (profile, building_id),
            CONSTRAINT ck_building_sld_document_profile
                CHECK (profile IN ('LIVE', 'DEMO')),
            CONSTRAINT ck_building_sld_document_source CHECK (
                source_size_bytes > 0
                AND source_sha256 ~ '^[0-9a-f]{64}$'
                AND source_mime_type IN ('application/pdf', 'image/png', 'image/jpeg')
            ),
            CONSTRAINT ck_building_sld_document_origin
                CHECK (document_origin IN ('MANAGER_UPLOAD', 'DEMO_FIXTURE')),
            CONSTRAINT ck_building_sld_document_version CHECK (version > 0)
        );
        CREATE INDEX ix_building_sld_document_building
        ON building_sld_document (building_id, updated_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS building_sld_document")
