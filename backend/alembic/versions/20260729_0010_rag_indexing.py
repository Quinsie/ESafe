# ruff: noqa: E501
"""Constrain embeddings and track source lineage and retrieval runs.

Revision ID: 20260729_0010
Revises: 20260729_0009
Create Date: 2026-07-29 12:50:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0010"
down_revision: str | None = "20260729_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        ALTER TABLE rag_chunk
        ALTER COLUMN embedding TYPE vector(1024)
        USING embedding::vector(1024);
        ALTER TABLE rag_chunk
        ADD COLUMN embedding_input_sha256 char(64),
        ADD COLUMN embedded_at timestamptz;
        ALTER TABLE rag_chunk
        ADD CONSTRAINT ck_rag_chunk_embedding_hash
        CHECK (
            embedding_input_sha256 IS NULL
            OR embedding_input_sha256 ~ '^[0-9a-f]{64}$'
        );
        ALTER TABLE rag_chunk
        ADD CONSTRAINT ck_rag_chunk_embedding_state
        CHECK (
            (embedding IS NULL AND embedding_input_sha256 IS NULL AND embedded_at IS NULL)
            OR
            (embedding IS NOT NULL AND embedding_input_sha256 IS NOT NULL AND embedded_at IS NOT NULL)
        );
        CREATE INDEX ix_rag_chunk_embedding_hnsw
        ON rag_chunk
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;

        CREATE TABLE rag_document_source (
            document_source_id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES rag_document(document_id) ON DELETE CASCADE,
            source_path text NOT NULL,
            source_sha256 char(64) NOT NULL,
            source_size bigint NOT NULL,
            source_status varchar(12) NOT NULL,
            duplicate_of_source_id uuid REFERENCES rag_document_source(document_source_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_rag_document_source UNIQUE (source_path, source_sha256),
            CONSTRAINT ck_rag_document_source_hash CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_rag_document_source_size CHECK (source_size > 0),
            CONSTRAINT ck_rag_document_source_status CHECK (source_status IN ('PRIMARY', 'DUPLICATE')),
            CONSTRAINT ck_rag_document_source_duplicate CHECK (
                (source_status = 'PRIMARY' AND duplicate_of_source_id IS NULL)
                OR
                (source_status = 'DUPLICATE' AND duplicate_of_source_id IS NOT NULL)
            )
        );
        CREATE INDEX ix_rag_document_source_document
        ON rag_document_source (document_id, source_status);

        CREATE TABLE rag_search_run (
            search_run_id uuid PRIMARY KEY,
            case_id uuid REFERENCES case_record(case_id) ON DELETE SET NULL,
            index_version_id uuid NOT NULL REFERENCES rag_index_version(index_version_id) ON DELETE RESTRICT,
            query_sha256 char(64) NOT NULL,
            query_text text NOT NULL,
            filters jsonb NOT NULL DEFAULT '{}'::jsonb,
            lexical_candidate_count integer NOT NULL DEFAULT 0,
            vector_candidate_count integer NOT NULL DEFAULT 0,
            fused_candidate_count integer NOT NULL DEFAULT 0,
            selected_count integer NOT NULL DEFAULT 0,
            retrieval_version varchar(64) NOT NULL,
            elapsed_ms integer,
            status varchar(16) NOT NULL,
            error_type varchar(80),
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_rag_search_query_hash CHECK (query_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_rag_search_query CHECK (length(trim(query_text)) > 0),
            CONSTRAINT ck_rag_search_counts CHECK (
                lexical_candidate_count >= 0
                AND vector_candidate_count >= 0
                AND fused_candidate_count >= 0
                AND selected_count >= 0
                AND selected_count <= fused_candidate_count
            ),
            CONSTRAINT ck_rag_search_elapsed CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
            CONSTRAINT ck_rag_search_status CHECK (status IN ('SUCCESS', 'INSUFFICIENT', 'FAILED')),
            CONSTRAINT ck_rag_search_error CHECK (
                (status = 'FAILED' AND error_type IS NOT NULL)
                OR
                (status <> 'FAILED' AND error_type IS NULL)
            )
        );
        CREATE INDEX ix_rag_search_case_created
        ON rag_search_run (case_id, created_at DESC);
        CREATE INDEX ix_rag_search_index_created
        ON rag_search_run (index_version_id, created_at DESC)
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE rag_search_run;
        DROP TABLE rag_document_source;
        DROP INDEX ix_rag_chunk_embedding_hnsw;
        ALTER TABLE rag_chunk DROP CONSTRAINT ck_rag_chunk_embedding_state;
        ALTER TABLE rag_chunk DROP CONSTRAINT ck_rag_chunk_embedding_hash;
        ALTER TABLE rag_chunk
        DROP COLUMN embedded_at,
        DROP COLUMN embedding_input_sha256;
        ALTER TABLE rag_chunk
        ALTER COLUMN embedding TYPE vector
        USING embedding::vector
        """
    )
