from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.ai_control import AiCostGate
from app.config import Settings
from app.upstage import UpstageEmbeddingClient

RETRIEVAL_VERSION = "rag-hybrid-rrf-v2"
RRF_K = 60
MAX_CANDIDATES_PER_CHANNEL = 40
MAX_SELECTED = 12
CASE_QUERY_TERMS = {
    "FIRE": "화재 소방",
    "WEATHER_WARNING": "기상특보 태풍 호우 폭염",
    "DISASTER_MESSAGE": "재난 안전 전기사고 감전",
}


@dataclass(slots=True)
class FusedCandidate:
    row: dict[str, Any]
    lexical_rank: int | None = None
    vector_rank: int | None = None
    vector_similarity: float | None = None
    fused_score: float = 0.0
    group: str = "OFFICIAL"
    selection_reason: dict[str, Any] | None = None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


def _authority_weight(level: int) -> float:
    return {1: 1.25, 2: 1.18, 3: 1.10, 4: 0.85, 5: 0.75}[level]


def _candidate_group(row: dict[str, Any]) -> str:
    family = str(row["document_family"])
    if family == "INCIDENT_CASE":
        return "PAST_INCIDENT"
    if family == "OTHER_REGION_REFERENCE":
        return "OTHER_REGION"
    return "OFFICIAL"


def _region_weight(row: dict[str, Any], primary_region_code: str | None) -> float:
    regions = [str(value) for value in row.get("regions") or []]
    if not regions:
        return 1.08
    if primary_region_code and primary_region_code.startswith("29"):
        return 1.12 if any("광주" in value for value in regions) else 0.88
    if primary_region_code and primary_region_code.startswith("46"):
        return (
            1.12
            if any("전남" in value or "전라남도" in value for value in regions)
            else 0.88
        )
    return 1.0


def _freshness_weight(row: dict[str, Any], today: date) -> float:
    published_at = row.get("published_at")
    if not isinstance(published_at, date):
        return 1.0
    age_days = max(0, (today - published_at).days)
    if age_days <= 365 * 3:
        return 1.06
    if age_days <= 365 * 7:
        return 1.0
    return 0.94


def fuse_candidates(
    lexical_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    *,
    primary_region_code: str | None,
    today: date,
) -> list[FusedCandidate]:
    fused: dict[str, FusedCandidate] = {}
    for rank, row in enumerate(lexical_rows, start=1):
        candidate = fused.setdefault(
            str(row["chunk_id"]),
            FusedCandidate(row=row),
        )
        candidate.lexical_rank = rank
    for rank, row in enumerate(vector_rows, start=1):
        candidate = fused.setdefault(
            str(row["chunk_id"]),
            FusedCandidate(row=row),
        )
        candidate.vector_rank = rank
        candidate.vector_similarity = 1.0 - float(row["vector_distance"])
    accepted: list[FusedCandidate] = []
    for candidate in fused.values():
        if (
            candidate.lexical_rank is None
            and (candidate.vector_similarity is None or candidate.vector_similarity < 0.20)
        ):
            continue
        base = 0.0
        if candidate.lexical_rank is not None:
            base += 1.0 / (RRF_K + candidate.lexical_rank)
        if candidate.vector_rank is not None:
            base += 1.0 / (RRF_K + candidate.vector_rank)
        authority = _authority_weight(int(candidate.row["authority_level"]))
        freshness = _freshness_weight(candidate.row, today)
        region = _region_weight(candidate.row, primary_region_code)
        candidate.fused_score = base * authority * freshness * region
        candidate.group = _candidate_group(candidate.row)
        candidate.selection_reason = {
            "rrfK": RRF_K,
            "authorityWeight": authority,
            "freshnessWeight": freshness,
            "regionWeight": region,
            "vectorSimilarity": candidate.vector_similarity,
        }
        accepted.append(candidate)
    accepted.sort(
        key=lambda item: (
            -item.fused_score,
            int(item.row["authority_level"]),
            str(item.row["chunk_id"]),
        )
    )
    return accepted


def select_context(candidates: list[FusedCandidate]) -> list[FusedCandidate]:
    caps = {"OFFICIAL": 6, "PAST_INCIDENT": 4, "OTHER_REGION": 2}
    selected: list[FusedCandidate] = []
    per_document: dict[str, int] = {}
    for group, cap in caps.items():
        for candidate in candidates:
            document_id = str(candidate.row["document_id"])
            if (
                candidate.group != group
                or per_document.get(document_id, 0) >= 2
                or sum(item.group == group for item in selected) >= cap
            ):
                continue
            selected.append(candidate)
            per_document[document_id] = per_document.get(document_id, 0) + 1
    if len(selected) < MAX_SELECTED:
        selected_ids = {str(item.row["chunk_id"]) for item in selected}
        for candidate in candidates:
            document_id = str(candidate.row["document_id"])
            if (
                str(candidate.row["chunk_id"]) in selected_ids
                or per_document.get(document_id, 0) >= 2
            ):
                continue
            selected.append(candidate)
            selected_ids.add(str(candidate.row["chunk_id"]))
            per_document[document_id] = per_document.get(document_id, 0) + 1
            if len(selected) == MAX_SELECTED:
                break
    selected.sort(
        key=lambda item: (
            {"OFFICIAL": 0, "PAST_INCIDENT": 1, "OTHER_REGION": 2}[item.group],
            -item.fused_score,
        )
    )
    return selected


async def _fetch_case_and_index(
    connection: AsyncConnection,
    case_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    case_row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT c.case_id, c.case_number, c.case_type, c.title,
                           c.monitoring_priority, c.primary_region_code,
                           region.full_name AS region_name, c.opened_at
                    FROM case_record c
                    LEFT JOIN admin_region region
                      ON region.region_code = c.primary_region_code
                    WHERE c.case_id = :case_id
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if case_row is None:
        return None
    index_row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT index_version_id, embedding_model, embedding_dimension
                    FROM rag_index_version
                    WHERE status = 'ACTIVE'
                    """
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if index_row is None:
        raise RuntimeError("RAG_ACTIVE_INDEX_NOT_FOUND")
    return dict(case_row), dict(index_row)


def _query_text(case_row: dict[str, Any]) -> str:
    parts = [
        str(case_row["title"]),
        str(case_row.get("region_name") or ""),
        CASE_QUERY_TERMS.get(
            str(case_row["case_type"]),
            str(case_row["case_type"]).replace("_", " "),
        ),
    ]
    return " ".join(part.strip() for part in parts if part.strip())


_CANDIDATE_COLUMNS = """
    chunk.chunk_id, chunk.document_id, chunk.page_or_section,
    chunk.heading_path, chunk.text_content, document.title,
    document.document_family, document.issuing_agency,
    document.document_number, document.published_at,
    document.effective_from, document.effective_to,
    document.revision, document.disaster_types, document.regions,
    document.authority_level, document.privacy_status
"""


async def _search_channels(
    connection: AsyncConnection,
    *,
    index_version_id: UUID,
    query_text: str,
    query_vector: list[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lexical = (
        (
            await connection.execute(
                text(
                    f"""
                    SELECT {_CANDIDATE_COLUMNS},
                           ts_rank_cd(
                               chunk.text_search ||
                               to_tsvector(
                                   'simple',
                                   document.title || ' ' ||
                                   coalesce(document.issuing_agency, '') || ' ' ||
                                   array_to_string(document.disaster_types, ' ')
                               ),
                               websearch_to_tsquery(
                                   'simple',
                                   regexp_replace(:query_text, '\\s+', ' OR ', 'g')
                               )
                           ) AS lexical_score
                    FROM rag_chunk chunk
                    JOIN rag_document document
                      ON document.document_id = chunk.document_id
                    WHERE chunk.index_version_id = :index_version_id
                      AND document.is_current
                      AND (
                          document.effective_from IS NULL
                          OR document.effective_from <= CURRENT_DATE
                      )
                      AND (
                          document.effective_to IS NULL
                          OR document.effective_to >= CURRENT_DATE
                      )
                      AND (
                          chunk.text_search ||
                          to_tsvector(
                              'simple',
                              document.title || ' ' ||
                              coalesce(document.issuing_agency, '') || ' ' ||
                              array_to_string(document.disaster_types, ' ')
                          )
                      ) @@ websearch_to_tsquery(
                          'simple',
                          regexp_replace(:query_text, '\\s+', ' OR ', 'g')
                      )
                    ORDER BY lexical_score DESC, chunk.chunk_id
                    LIMIT {MAX_CANDIDATES_PER_CHANNEL}
                    """
                ),
                {"query_text": query_text, "index_version_id": index_version_id},
            )
        )
        .mappings()
        .all()
    )
    vector = (
        (
            await connection.execute(
                text(
                    f"""
                    SELECT {_CANDIDATE_COLUMNS},
                           chunk.embedding <=> CAST(:query_vector AS vector(1024))
                               AS vector_distance
                    FROM rag_chunk chunk
                    JOIN rag_document document
                      ON document.document_id = chunk.document_id
                    WHERE chunk.index_version_id = :index_version_id
                      AND chunk.embedding IS NOT NULL
                      AND document.is_current
                      AND (
                          document.effective_from IS NULL
                          OR document.effective_from <= CURRENT_DATE
                      )
                      AND (
                          document.effective_to IS NULL
                          OR document.effective_to >= CURRENT_DATE
                      )
                    ORDER BY chunk.embedding <=> CAST(:query_vector AS vector(1024)),
                             chunk.chunk_id
                    LIMIT {MAX_CANDIDATES_PER_CHANNEL}
                    """
                ),
                {
                    "query_vector": _vector_literal(query_vector),
                    "index_version_id": index_version_id,
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in lexical], [dict(row) for row in vector]


async def run_case_retrieval(settings: Settings, case_id: UUID) -> dict[str, Any]:
    started = time.monotonic()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    gate = AiCostGate(settings)
    query_text = ""
    index_version_id: UUID | None = None
    try:
        async with engine.connect() as connection:
            context = await _fetch_case_and_index(connection, case_id)
        if context is None:
            raise ValueError("CASE_NOT_FOUND")
        case_row, index_row = context
        index_version_id = index_row["index_version_id"]
        query_text = _query_text(case_row)
        embedding = await UpstageEmbeddingClient(settings, gate).embed_query(
            query_text,
            feature_name="rag-case-query",
            privacy_verified=True,
            case_reference=case_id,
        )
        async with engine.begin() as connection:
            lexical, vector = await _search_channels(
                connection,
                index_version_id=index_version_id,
                query_text=query_text,
                query_vector=embedding.vectors[0],
            )
            candidates = fuse_candidates(
                lexical,
                vector,
                primary_region_code=case_row.get("primary_region_code"),
                today=date.today(),
            )
            selected = select_context(candidates)
            official_count = sum(item.group == "OFFICIAL" for item in selected)
            status = "SUFFICIENT" if official_count > 0 else "INSUFFICIENT"
            search_status = "SUCCESS" if status == "SUFFICIENT" else "INSUFFICIENT"
            warning = (
                None
                if status == "SUFFICIENT"
                else "공식 현행 근거가 부족합니다. 결과는 참고 의견이며 추가 확인이 필요합니다."
            )
            search_run_id = uuid4()
            await connection.execute(
                text(
                    """
                    INSERT INTO rag_search_run (
                        search_run_id, case_id, index_version_id, query_sha256,
                        query_text, filters, lexical_candidate_count,
                        vector_candidate_count, fused_candidate_count,
                        selected_count, retrieval_version, elapsed_ms, status
                    )
                    VALUES (
                        :search_run_id, :case_id, :index_version_id, :query_sha256,
                        :query_text, CAST(:filters AS jsonb), :lexical_count,
                        :vector_count, :fused_count, :selected_count,
                        :retrieval_version, :elapsed_ms, :status
                    )
                    """
                ),
                {
                    "search_run_id": search_run_id,
                    "case_id": case_id,
                    "index_version_id": index_version_id,
                    "query_sha256": hashlib.sha256(query_text.encode()).hexdigest(),
                    "query_text": query_text,
                    "filters": json.dumps(
                        {
                            "activeOnly": True,
                            "effectiveOn": date.today().isoformat(),
                            "primaryRegionCode": case_row.get("primary_region_code"),
                        },
                        ensure_ascii=False,
                    ),
                    "lexical_count": len(lexical),
                    "vector_count": len(vector),
                    "fused_count": len(candidates),
                    "selected_count": len(selected),
                    "retrieval_version": RETRIEVAL_VERSION,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "status": search_status,
                },
            )
            version = int(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT coalesce(max(version), 0) + 1
                            FROM evidence_bundle
                            WHERE case_id = :case_id
                            """
                        ),
                        {"case_id": case_id},
                    )
                ).scalar_one()
            )
            await connection.execute(
                text(
                    """
                    UPDATE evidence_bundle
                    SET is_current = false
                    WHERE case_id = :case_id AND is_current
                    """
                ),
                {"case_id": case_id},
            )
            bundle_id = uuid4()
            factual_snapshot = {
                "caseNumber": case_row["case_number"],
                "caseType": case_row["case_type"],
                "title": case_row["title"],
                "regionName": case_row.get("region_name"),
                "monitoringPriority": case_row["monitoring_priority"],
                "openedAt": case_row["opened_at"].isoformat(),
            }
            await connection.execute(
                text(
                    """
                    INSERT INTO evidence_bundle (
                        evidence_bundle_id, case_id, version, status,
                        index_version_id, factual_snapshot, query_text,
                        retrieval_version, candidate_count, selected_count,
                        direct_citation_count, warning, is_current
                    )
                    VALUES (
                        :bundle_id, :case_id, :version, :status,
                        :index_version_id, CAST(:snapshot AS jsonb), :query_text,
                        :retrieval_version, :candidate_count, :selected_count,
                        :direct_count, :warning, true
                    )
                    """
                ),
                {
                    "bundle_id": bundle_id,
                    "case_id": case_id,
                    "version": version,
                    "status": status,
                    "index_version_id": index_version_id,
                    "snapshot": json.dumps(factual_snapshot, ensure_ascii=False),
                    "query_text": query_text,
                    "retrieval_version": RETRIEVAL_VERSION,
                    "candidate_count": len(candidates),
                    "selected_count": len(selected),
                    "direct_count": official_count,
                    "warning": warning,
                },
            )
            ranks = {"OFFICIAL": 0, "PAST_INCIDENT": 0, "OTHER_REGION": 0}
            for candidate in selected:
                ranks[candidate.group] += 1
                row = candidate.row
                await connection.execute(
                    text(
                        """
                        INSERT INTO evidence_item (
                            evidence_item_id, evidence_bundle_id, chunk_id,
                            evidence_group, rank, lexical_rank, vector_rank,
                            fused_score, authority_level, current_status,
                            selection_reason, excerpt, locator
                        )
                        VALUES (
                            :item_id, :bundle_id, :chunk_id,
                            :group, :rank, :lexical_rank, :vector_rank,
                            :fused_score, :authority_level, 'CURRENT',
                            CAST(:selection_reason AS jsonb), :excerpt, :locator
                        )
                        """
                    ),
                    {
                        "item_id": uuid4(),
                        "bundle_id": bundle_id,
                        "chunk_id": row["chunk_id"],
                        "group": candidate.group,
                        "rank": ranks[candidate.group],
                        "lexical_rank": candidate.lexical_rank,
                        "vector_rank": candidate.vector_rank,
                        "fused_score": candidate.fused_score,
                        "authority_level": row["authority_level"],
                        "selection_reason": json.dumps(candidate.selection_reason),
                        "excerpt": row["text_content"],
                        "locator": row["page_or_section"],
                    },
                )
        return {
            "status": status,
            "caseId": str(case_id),
            "indexVersionId": str(index_version_id),
            "lexicalCandidateCount": len(lexical),
            "vectorCandidateCount": len(vector),
            "fusedCandidateCount": len(candidates),
            "selectedCount": len(selected),
            "officialCount": official_count,
            "queryEmbeddingCacheHit": embedding.cache_hit,
            "elapsedMs": int((time.monotonic() - started) * 1000),
        }
    except Exception as error:
        if index_version_id is not None and query_text:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO rag_search_run (
                            search_run_id, case_id, index_version_id,
                            query_sha256, query_text, filters,
                            retrieval_version, elapsed_ms, status, error_type
                        )
                        VALUES (
                            :run_id, :case_id, :index_version_id,
                            :query_sha256, :query_text, '{}'::jsonb,
                            :retrieval_version, :elapsed_ms, 'FAILED', :error_type
                        )
                        """
                    ),
                    {
                        "run_id": uuid4(),
                        "case_id": case_id,
                        "index_version_id": index_version_id,
                        "query_sha256": hashlib.sha256(query_text.encode()).hexdigest(),
                        "query_text": query_text,
                        "retrieval_version": RETRIEVAL_VERSION,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "error_type": type(error).__name__[:80],
                    },
                )
        raise
    finally:
        await gate.close()
        await engine.dispose()
