# ruff: noqa: E501
"""Create the evidence, recommendation, task-decision, and closure workflow.

Revision ID: 20260729_0009
Revises: 20260729_0008
Create Date: 2026-07-29 12:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0009"
down_revision: str | None = "20260729_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(script: str) -> None:
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE rag_index_version (
            index_version_id uuid PRIMARY KEY,
            status varchar(20) NOT NULL,
            source_manifest_sha256 char(64) NOT NULL,
            parser_version varchar(64) NOT NULL,
            privacy_version varchar(64) NOT NULL,
            embedding_model varchar(64),
            embedding_dimension integer,
            document_count integer NOT NULL DEFAULT 0,
            chunk_count integer NOT NULL DEFAULT 0,
            failure_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            activated_at timestamptz,
            CONSTRAINT ck_rag_index_status CHECK (status IN ('BUILDING', 'ACTIVE', 'FAILED', 'SUPERSEDED')),
            CONSTRAINT ck_rag_index_manifest CHECK (source_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_rag_index_counts CHECK (document_count >= 0 AND chunk_count >= 0),
            CONSTRAINT ck_rag_index_dimension CHECK (embedding_dimension IS NULL OR embedding_dimension > 0),
            CONSTRAINT ck_rag_index_activation CHECK ((status = 'ACTIVE' AND activated_at IS NOT NULL) OR status <> 'ACTIVE')
        );
        CREATE UNIQUE INDEX ux_rag_index_active
        ON rag_index_version ((true))
        WHERE status = 'ACTIVE';

        CREATE TABLE rag_document (
            document_id uuid PRIMARY KEY,
            logical_key varchar(200) NOT NULL,
            version integer NOT NULL,
            document_family varchar(32) NOT NULL,
            title text NOT NULL,
            issuing_agency text,
            recipient_agencies text[] NOT NULL DEFAULT '{}',
            document_number varchar(160),
            published_at date,
            effective_from date,
            effective_to date,
            revision varchar(128),
            supersedes_document_id uuid REFERENCES rag_document(document_id) ON DELETE RESTRICT,
            disaster_types text[] NOT NULL DEFAULT '{}',
            regions text[] NOT NULL DEFAULT '{}',
            authority_level smallint NOT NULL,
            confidentiality varchar(24) NOT NULL,
            privacy_status varchar(24) NOT NULL,
            contains_personal_data boolean,
            source_format varchar(12) NOT NULL,
            source_path text NOT NULL,
            source_sha256 char(64) NOT NULL,
            safe_copy_path text,
            safe_copy_sha256 char(64),
            parser_version varchar(64),
            parse_status varchar(24) NOT NULL,
            parse_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
            is_current boolean NOT NULL DEFAULT false,
            ingested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            activated_at timestamptz,
            deactivated_at timestamptz,
            CONSTRAINT uq_rag_document_version UNIQUE (logical_key, version),
            CONSTRAINT ck_rag_document_version CHECK (version > 0),
            CONSTRAINT ck_rag_document_family CHECK (document_family IN ('AUTHORITATIVE_MANUAL', 'OFFICIAL_NOTICE', 'PLAN_POLICY', 'INCIDENT_CASE', 'OTHER_REGION_REFERENCE')),
            CONSTRAINT ck_rag_document_authority CHECK (authority_level BETWEEN 1 AND 5),
            CONSTRAINT ck_rag_document_confidentiality CHECK (confidentiality IN ('PUBLIC', 'RESTRICTED')),
            CONSTRAINT ck_rag_document_privacy CHECK (privacy_status IN ('UNKNOWN', 'SCANNED', 'PUBLIC_SAFE', 'MASKED_VERIFIED', 'REVIEW_REQUIRED')),
            CONSTRAINT ck_rag_document_format CHECK (source_format IN ('PDF', 'HWPX', 'HWP', 'JSON')),
            CONSTRAINT ck_rag_document_parse CHECK (parse_status IN ('PENDING', 'PARSED', 'FAILED', 'REVIEW_REQUIRED')),
            CONSTRAINT ck_rag_document_hash CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_rag_document_safe_hash CHECK (safe_copy_sha256 IS NULL OR safe_copy_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_rag_document_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_rag_document_indexable CHECK (
                NOT is_current OR (
                    parse_status = 'PARSED'
                    AND privacy_status IN ('PUBLIC_SAFE', 'MASKED_VERIFIED')
                    AND activated_at IS NOT NULL
                )
            ),
            CONSTRAINT ck_rag_document_dates CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from)
        );
        CREATE UNIQUE INDEX ux_rag_document_current
        ON rag_document (logical_key)
        WHERE is_current;
        CREATE INDEX ix_rag_document_search_scope
        ON rag_document (is_current, document_family, authority_level, published_at DESC);
        CREATE INDEX ix_rag_document_disaster_types
        ON rag_document USING gin (disaster_types);
        CREATE INDEX ix_rag_document_regions
        ON rag_document USING gin (regions);

        CREATE TABLE rag_chunk (
            chunk_id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES rag_document(document_id) ON DELETE CASCADE,
            index_version_id uuid NOT NULL REFERENCES rag_index_version(index_version_id) ON DELETE RESTRICT,
            ordinal integer NOT NULL,
            page_or_section varchar(240) NOT NULL,
            heading_path text[] NOT NULL DEFAULT '{}',
            paragraph_index integer,
            text_content text NOT NULL,
            table_context jsonb,
            character_count integer NOT NULL,
            token_count integer,
            embedding_model varchar(64),
            embedding_version varchar(64),
            embedding vector,
            text_search tsvector GENERATED ALWAYS AS (
                to_tsvector('simple'::regconfig, text_content)
            ) STORED,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_rag_chunk_ordinal UNIQUE (document_id, index_version_id, ordinal),
            CONSTRAINT ck_rag_chunk_ordinal CHECK (ordinal > 0),
            CONSTRAINT ck_rag_chunk_paragraph CHECK (paragraph_index IS NULL OR paragraph_index >= 0),
            CONSTRAINT ck_rag_chunk_text CHECK (length(trim(text_content)) > 0),
            CONSTRAINT ck_rag_chunk_characters CHECK (character_count > 0),
            CONSTRAINT ck_rag_chunk_tokens CHECK (token_count IS NULL OR token_count > 0)
        );
        CREATE INDEX ix_rag_chunk_document
        ON rag_chunk (document_id, index_version_id, ordinal);
        CREATE INDEX ix_rag_chunk_text_search
        ON rag_chunk USING gin (text_search);

        CREATE TABLE evidence_bundle (
            evidence_bundle_id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            version integer NOT NULL,
            status varchar(16) NOT NULL,
            index_version_id uuid REFERENCES rag_index_version(index_version_id) ON DELETE RESTRICT,
            factual_snapshot jsonb NOT NULL,
            query_text text NOT NULL,
            retrieval_version varchar(64) NOT NULL,
            candidate_count integer NOT NULL DEFAULT 0,
            selected_count integer NOT NULL DEFAULT 0,
            direct_citation_count integer NOT NULL DEFAULT 0,
            warning text,
            is_current boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_evidence_bundle_version UNIQUE (case_id, version),
            CONSTRAINT ck_evidence_bundle_version CHECK (version > 0),
            CONSTRAINT ck_evidence_bundle_status CHECK (status IN ('SUFFICIENT', 'INSUFFICIENT', 'CONFLICT')),
            CONSTRAINT ck_evidence_bundle_counts CHECK (
                candidate_count >= 0
                AND selected_count >= 0
                AND direct_citation_count >= 0
                AND selected_count <= candidate_count
            ),
            CONSTRAINT ck_evidence_bundle_query CHECK (length(trim(query_text)) > 0),
            CONSTRAINT ck_evidence_bundle_warning CHECK (
                status = 'SUFFICIENT' OR warning IS NOT NULL
            )
        );
        CREATE UNIQUE INDEX ux_evidence_bundle_current
        ON evidence_bundle (case_id)
        WHERE is_current;
        CREATE INDEX ix_evidence_bundle_case_created
        ON evidence_bundle (case_id, created_at DESC);

        CREATE TABLE evidence_item (
            evidence_item_id uuid PRIMARY KEY,
            evidence_bundle_id uuid NOT NULL REFERENCES evidence_bundle(evidence_bundle_id) ON DELETE CASCADE,
            chunk_id uuid NOT NULL REFERENCES rag_chunk(chunk_id) ON DELETE RESTRICT,
            evidence_group varchar(24) NOT NULL,
            rank integer NOT NULL,
            lexical_rank integer,
            vector_rank integer,
            fused_score double precision NOT NULL,
            authority_level smallint NOT NULL,
            current_status varchar(20) NOT NULL,
            selection_reason jsonb NOT NULL DEFAULT '{}'::jsonb,
            excerpt text NOT NULL,
            locator varchar(240) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_evidence_item_chunk UNIQUE (evidence_bundle_id, chunk_id),
            CONSTRAINT uq_evidence_item_rank UNIQUE (evidence_bundle_id, evidence_group, rank),
            CONSTRAINT ck_evidence_item_group CHECK (evidence_group IN ('OFFICIAL', 'PAST_INCIDENT', 'OTHER_REGION')),
            CONSTRAINT ck_evidence_item_rank CHECK (rank > 0 AND (lexical_rank IS NULL OR lexical_rank > 0) AND (vector_rank IS NULL OR vector_rank > 0)),
            CONSTRAINT ck_evidence_item_score CHECK (fused_score >= 0),
            CONSTRAINT ck_evidence_item_authority CHECK (authority_level BETWEEN 1 AND 5),
            CONSTRAINT ck_evidence_item_current CHECK (current_status IN ('CURRENT', 'EXPIRED', 'SUPERSEDED', 'UNKNOWN')),
            CONSTRAINT ck_evidence_item_excerpt CHECK (length(trim(excerpt)) > 0),
            CONSTRAINT ck_evidence_item_locator CHECK (length(trim(locator)) > 0)
        );
        CREATE INDEX ix_evidence_item_bundle
        ON evidence_item (evidence_bundle_id, evidence_group, rank);

        CREATE TABLE recommendation (
            recommendation_id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE CASCADE,
            evidence_bundle_id uuid NOT NULL REFERENCES evidence_bundle(evidence_bundle_id) ON DELETE RESTRICT,
            version integer NOT NULL,
            status varchar(16) NOT NULL,
            generation_mode varchar(12) NOT NULL,
            factual_snapshot jsonb NOT NULL,
            situation_summary text NOT NULL,
            required_checks jsonb NOT NULL DEFAULT '[]'::jsonb,
            uncertainties jsonb NOT NULL DEFAULT '[]'::jsonb,
            conflicts jsonb NOT NULL DEFAULT '[]'::jsonb,
            warning text,
            model varchar(64),
            prompt_version varchar(64),
            generation_version varchar(64) NOT NULL,
            input_sha256 char(64) NOT NULL,
            output_sha256 char(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            superseded_at timestamptz,
            CONSTRAINT uq_recommendation_version UNIQUE (case_id, version),
            CONSTRAINT ck_recommendation_version CHECK (version > 0),
            CONSTRAINT ck_recommendation_status CHECK (status IN ('DRAFT', 'READY', 'SUPERSEDED')),
            CONSTRAINT ck_recommendation_mode CHECK (generation_mode IN ('RULE', 'AI', 'USER')),
            CONSTRAINT ck_recommendation_summary CHECK (length(trim(situation_summary)) > 0),
            CONSTRAINT ck_recommendation_input_hash CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_recommendation_output_hash CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_recommendation_superseded CHECK ((status = 'SUPERSEDED' AND superseded_at IS NOT NULL) OR status <> 'SUPERSEDED')
        );
        CREATE UNIQUE INDEX ux_recommendation_current
        ON recommendation (case_id)
        WHERE status IN ('DRAFT', 'READY');
        CREATE INDEX ix_recommendation_case_created
        ON recommendation (case_id, created_at DESC);

        CREATE TABLE recommendation_action (
            recommendation_action_id uuid PRIMARY KEY,
            recommendation_id uuid NOT NULL REFERENCES recommendation(recommendation_id) ON DELETE CASCADE,
            ordinal integer NOT NULL,
            title text NOT NULL,
            description text NOT NULL,
            due_guidance varchar(160),
            evidence_status varchar(16) NOT NULL,
            warning text,
            status varchar(16) NOT NULL DEFAULT 'PROPOSED',
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_recommendation_action_ordinal UNIQUE (recommendation_id, ordinal),
            CONSTRAINT ck_recommendation_action_ordinal CHECK (ordinal > 0),
            CONSTRAINT ck_recommendation_action_evidence CHECK (evidence_status IN ('SUFFICIENT', 'INSUFFICIENT', 'CONFLICT')),
            CONSTRAINT ck_recommendation_action_status CHECK (status IN ('PROPOSED', 'ACCEPTED', 'DISCARDED')),
            CONSTRAINT ck_recommendation_action_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_recommendation_action_description CHECK (length(trim(description)) > 0),
            CONSTRAINT ck_recommendation_action_warning CHECK (evidence_status = 'SUFFICIENT' OR warning IS NOT NULL)
        );

        CREATE TABLE evidence_citation (
            citation_id uuid PRIMARY KEY,
            recommendation_action_id uuid NOT NULL REFERENCES recommendation_action(recommendation_action_id) ON DELETE CASCADE,
            evidence_item_id uuid NOT NULL REFERENCES evidence_item(evidence_item_id) ON DELETE RESTRICT,
            support_type varchar(16) NOT NULL,
            quote_text text NOT NULL,
            locator varchar(240) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_evidence_citation UNIQUE (recommendation_action_id, evidence_item_id, quote_text),
            CONSTRAINT ck_evidence_citation_support CHECK (support_type IN ('DIRECT', 'CONTEXT', 'CASE_EXAMPLE')),
            CONSTRAINT ck_evidence_citation_quote CHECK (length(trim(quote_text)) > 0),
            CONSTRAINT ck_evidence_citation_locator CHECK (length(trim(locator)) > 0)
        );
        CREATE INDEX ix_evidence_citation_action
        ON evidence_citation (recommendation_action_id, citation_id);

        ALTER TABLE work_item
        ADD COLUMN recommendation_action_id uuid REFERENCES recommendation_action(recommendation_action_id) ON DELETE SET NULL;
        ALTER TABLE work_item
        ADD COLUMN version integer NOT NULL DEFAULT 1;
        ALTER TABLE work_item
        ADD CONSTRAINT ck_work_item_version CHECK (version > 0);
        CREATE UNIQUE INDEX ux_work_item_recommendation_action
        ON work_item (recommendation_action_id)
        WHERE recommendation_action_id IS NOT NULL;

        CREATE TABLE work_item_checklist (
            checklist_item_id uuid PRIMARY KEY,
            work_item_id uuid NOT NULL REFERENCES work_item(work_item_id) ON DELETE CASCADE,
            ordinal integer NOT NULL,
            label text NOT NULL,
            status varchar(12) NOT NULL DEFAULT 'PENDING',
            note text,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_work_item_checklist_ordinal UNIQUE (work_item_id, ordinal),
            CONSTRAINT ck_work_item_checklist_ordinal CHECK (ordinal > 0),
            CONSTRAINT ck_work_item_checklist_status CHECK (status IN ('PENDING', 'DONE', 'SKIPPED')),
            CONSTRAINT ck_work_item_checklist_label CHECK (length(trim(label)) > 0),
            CONSTRAINT ck_work_item_checklist_completion CHECK ((status = 'DONE' AND completed_at IS NOT NULL) OR status <> 'DONE')
        );
        CREATE INDEX ix_work_item_checklist
        ON work_item_checklist (work_item_id, ordinal);

        CREATE TABLE approval_request (
            approval_request_id uuid PRIMARY KEY,
            case_id uuid REFERENCES case_record(case_id) ON DELETE CASCADE,
            target_type varchar(32) NOT NULL,
            target_id uuid NOT NULL,
            target_version integer NOT NULL,
            title text NOT NULL,
            status varchar(24) NOT NULL,
            content_sha256 char(64) NOT NULL,
            evidence_status varchar(16),
            warning text,
            requested_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            decided_at timestamptz,
            version integer NOT NULL DEFAULT 1,
            CONSTRAINT ck_approval_request_target CHECK (target_type IN ('RECOMMENDATION', 'WORK_ITEM', 'DOCUMENT_DRAFT', 'CLOSURE')),
            CONSTRAINT ck_approval_request_target_version CHECK (target_version > 0),
            CONSTRAINT ck_approval_request_status CHECK (status IN ('APPROVAL_PENDING', 'APPROVED', 'ON_HOLD', 'DISCARDED', 'SUPERSEDED')),
            CONSTRAINT ck_approval_request_hash CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_approval_request_evidence CHECK (evidence_status IS NULL OR evidence_status IN ('SUFFICIENT', 'INSUFFICIENT', 'CONFLICT')),
            CONSTRAINT ck_approval_request_title CHECK (length(trim(title)) > 0),
            CONSTRAINT ck_approval_request_version CHECK (version > 0),
            CONSTRAINT ck_approval_request_decision_time CHECK ((status = 'APPROVAL_PENDING' AND decided_at IS NULL) OR (status <> 'APPROVAL_PENDING' AND decided_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_approval_request_pending_target
        ON approval_request (target_type, target_id, target_version)
        WHERE status = 'APPROVAL_PENDING';
        CREATE INDEX ix_approval_request_case
        ON approval_request (case_id, status, requested_at DESC);

        CREATE TABLE approval_decision (
            approval_decision_id uuid PRIMARY KEY,
            approval_request_id uuid NOT NULL REFERENCES approval_request(approval_request_id) ON DELETE RESTRICT,
            decision varchar(12) NOT NULL,
            decided_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            reason text NOT NULL,
            warning_acknowledged boolean NOT NULL,
            content_sha256 char(64) NOT NULL,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            decided_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_approval_decision_request UNIQUE (approval_request_id),
            CONSTRAINT ck_approval_decision CHECK (decision IN ('APPROVED', 'ON_HOLD', 'DISCARDED')),
            CONSTRAINT ck_approval_decision_reason CHECK (length(trim(reason)) > 0),
            CONSTRAINT ck_approval_decision_hash CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE case_closure (
            case_closure_id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES case_record(case_id) ON DELETE RESTRICT,
            version integer NOT NULL,
            status varchar(12) NOT NULL,
            close_reason varchar(32) NOT NULL,
            summary text NOT NULL,
            incomplete_work_item_count integer NOT NULL,
            evidence_status varchar(16) NOT NULL,
            warning_acknowledged boolean NOT NULL,
            snapshot jsonb NOT NULL,
            requested_by uuid NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at timestamptz,
            CONSTRAINT uq_case_closure_version UNIQUE (case_id, version),
            CONSTRAINT ck_case_closure_version CHECK (version > 0),
            CONSTRAINT ck_case_closure_status CHECK (status IN ('DRAFT', 'COMPLETED')),
            CONSTRAINT ck_case_closure_reason CHECK (close_reason IN ('RESOLVED', 'FALSE_ALARM', 'DUPLICATE', 'OTHER')),
            CONSTRAINT ck_case_closure_summary CHECK (length(trim(summary)) > 0),
            CONSTRAINT ck_case_closure_work_count CHECK (incomplete_work_item_count >= 0),
            CONSTRAINT ck_case_closure_evidence CHECK (evidence_status IN ('SUFFICIENT', 'INSUFFICIENT', 'CONFLICT')),
            CONSTRAINT ck_case_closure_completed CHECK ((status = 'COMPLETED' AND completed_at IS NOT NULL) OR status <> 'COMPLETED')
        );
        CREATE UNIQUE INDEX ux_case_closure_completed
        ON case_closure (case_id)
        WHERE status = 'COMPLETED';

        CREATE TABLE ai_usage_ledger (
            ai_usage_id uuid PRIMARY KEY,
            profile varchar(8) NOT NULL,
            provider varchar(24) NOT NULL,
            operation varchar(32) NOT NULL,
            model varchar(64) NOT NULL,
            endpoint varchar(160) NOT NULL,
            request_sha256 char(64) NOT NULL,
            cache_key varchar(160),
            input_units integer NOT NULL DEFAULT 0,
            output_units integer NOT NULL DEFAULT 0,
            unit_type varchar(16) NOT NULL,
            input_price_per_million_usd numeric(12,6) NOT NULL DEFAULT 0,
            output_price_per_million_usd numeric(12,6) NOT NULL DEFAULT 0,
            estimated_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
            status varchar(12) NOT NULL,
            error_class varchar(64),
            case_id uuid REFERENCES case_record(case_id) ON DELETE SET NULL,
            work_item_id uuid REFERENCES work_item(work_item_id) ON DELETE SET NULL,
            request_id uuid NOT NULL,
            started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at timestamptz,
            CONSTRAINT ck_ai_usage_profile CHECK (profile IN ('LIVE', 'DEMO')),
            CONSTRAINT ck_ai_usage_provider CHECK (provider = 'UPSTAGE'),
            CONSTRAINT ck_ai_usage_units CHECK (input_units >= 0 AND output_units >= 0),
            CONSTRAINT ck_ai_usage_unit_type CHECK (unit_type IN ('TOKEN', 'CHARACTER')),
            CONSTRAINT ck_ai_usage_cost CHECK (
                input_price_per_million_usd >= 0
                AND output_price_per_million_usd >= 0
                AND estimated_cost_usd >= 0
            ),
            CONSTRAINT ck_ai_usage_status CHECK (status IN ('RESERVED', 'SUCCEEDED', 'FAILED', 'CACHED', 'BLOCKED')),
            CONSTRAINT ck_ai_usage_hash CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_ai_usage_finished CHECK ((status = 'RESERVED' AND finished_at IS NULL) OR (status <> 'RESERVED' AND finished_at IS NOT NULL))
        );
        CREATE INDEX ix_ai_usage_started
        ON ai_usage_ledger (started_at DESC, ai_usage_id);
        CREATE INDEX ix_ai_usage_cost
        ON ai_usage_ledger (status, estimated_cost_usd)
        WHERE status IN ('RESERVED', 'SUCCEEDED');
        CREATE UNIQUE INDEX ux_ai_usage_cache_success
        ON ai_usage_ledger (profile, cache_key)
        WHERE cache_key IS NOT NULL AND status = 'SUCCEEDED';
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE IF EXISTS ai_usage_ledger;
        DROP TABLE IF EXISTS case_closure;
        DROP TABLE IF EXISTS approval_decision;
        DROP TABLE IF EXISTS approval_request;
        DROP TABLE IF EXISTS work_item_checklist;
        DROP INDEX IF EXISTS ux_work_item_recommendation_action;
        ALTER TABLE work_item DROP CONSTRAINT IF EXISTS ck_work_item_version;
        ALTER TABLE work_item DROP COLUMN IF EXISTS version;
        ALTER TABLE work_item DROP COLUMN IF EXISTS recommendation_action_id;
        DROP TABLE IF EXISTS evidence_citation;
        DROP TABLE IF EXISTS recommendation_action;
        DROP TABLE IF EXISTS recommendation;
        DROP TABLE IF EXISTS evidence_item;
        DROP TABLE IF EXISTS evidence_bundle;
        DROP TABLE IF EXISTS rag_chunk;
        DROP TABLE IF EXISTS rag_document;
        DROP TABLE IF EXISTS rag_index_version;
        """
    )
