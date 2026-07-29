from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.ai_control import AiCostGate
from app.config import Settings
from app.rag_search import (
    RETRIEVAL_VERSION,
    _search_channels,
    fuse_candidates,
    run_case_retrieval,
)
from app.recommendations import (
    GENERATION_VERSION,
    PROMPT_VERSION,
    run_case_recommendation,
)
from app.upstage import UpstageEmbeddingClient

EVALUATION_VERSION = "rag-evaluation-runner-v1"
TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z]{2,}")
NUMBER_PATTERN = re.compile(r"(?<!\d)\d+(?:[.,]\d+)*(?!\d)")
STOP_WORDS = frozenset(
    {
        "관련",
        "근거",
        "공식",
        "현재",
        "상황",
        "현장",
        "대응",
        "조치",
        "확인",
        "필요",
        "수행",
        "기록",
        "사용자",
        "합니다",
        "해야",
        "대한",
        "있는",
        "따라",
    }
)


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[position]


def _tokens(value: str) -> set[str]:
    return {
        token.lower() for token in TOKEN_PATTERN.findall(value) if token.lower() not in STOP_WORDS
    }


def _unique_documents(candidates: Iterable[Any], limit: int) -> list[str]:
    result: list[str] = []
    for candidate in candidates:
        document_id = str(candidate.row["document_id"])
        if document_id not in result:
            result.append(document_id)
        if len(result) == limit:
            break
    return result


def _question_contract(question: dict[str, Any]) -> None:
    required = {
        "id",
        "category",
        "question",
        "caseType",
        "regionCode",
        "expectedDocumentIds",
        "expectedChunkIds",
        "supportTerms",
        "rationale",
    }
    missing = sorted(required - set(question))
    if missing:
        raise ValueError(f"{question.get('id', 'UNKNOWN')}: missing {missing}")
    for key in ("expectedDocumentIds", "expectedChunkIds"):
        for value in question[key]:
            UUID(str(value))


async def _insert_case(
    engine: AsyncEngine,
    question: dict[str, Any],
    ordinal: int,
    run_token: str,
) -> UUID:
    case_id = uuid4()
    case_number = f"EVAL-{run_token}-{ordinal:02d}"
    async with engine.begin() as connection:
        region_exists = (
            await connection.execute(
                text("SELECT 1 FROM admin_region WHERE region_code = :region_code"),
                {"region_code": question["regionCode"]},
            )
        ).scalar_one_or_none()
        if region_exists is None:
            raise RuntimeError(f"{question['id']}: region {question['regionCode']} not found")
        await connection.execute(
            text(
                """
                INSERT INTO case_record (
                    case_id, case_number, case_type, title, status,
                    source_status, monitoring_priority, primary_region_code,
                    opened_at, updated_at, is_simulated, version
                )
                VALUES (
                    :case_id, :case_number, :case_type, :title, 'ACTIVE',
                    'RAG_EVALUATION', 'ATTENTION', :region_code,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, false, 1
                )
                """
            ),
            {
                "case_id": case_id,
                "case_number": case_number,
                "case_type": question["caseType"],
                "title": question["question"],
                "region_code": question["regionCode"],
            },
        )
    return case_id


async def _cleanup_case(engine: AsyncEngine, case_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                DELETE FROM recommendation
                WHERE case_id = :case_id
                """
            ),
            {"case_id": case_id},
        )
        await connection.execute(
            text(
                """
                DELETE FROM evidence_bundle
                WHERE case_id = :case_id
                """
            ),
            {"case_id": case_id},
        )
        await connection.execute(
            text("DELETE FROM rag_search_run WHERE case_id = :case_id"),
            {"case_id": case_id},
        )
        await connection.execute(
            text("DELETE FROM case_record WHERE case_id = :case_id"),
            {"case_id": case_id},
        )


async def _latest_query(connection: AsyncConnection, case_id: UUID) -> str:
    return str(
        (
            await connection.execute(
                text(
                    """
                    SELECT query_text
                    FROM rag_search_run
                    WHERE case_id = :case_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"case_id": case_id},
            )
        ).scalar_one()
    )


async def _active_index(connection: AsyncConnection) -> dict[str, Any]:
    row = (
        (
            await connection.execute(
                text(
                    """
                    SELECT index_version_id, embedding_model,
                           embedding_dimension, document_count, chunk_count
                    FROM rag_index_version
                    WHERE status = 'ACTIVE'
                    """
                )
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _fetch_generation_result(
    connection: AsyncConnection,
    case_id: UUID,
) -> dict[str, Any]:
    recommendation = (
        (
            await connection.execute(
                text(
                    """
                    SELECT recommendation.recommendation_id,
                           recommendation.situation_summary,
                           recommendation.required_checks,
                           recommendation.uncertainties,
                           recommendation.conflicts,
                           recommendation.warning,
                           recommendation.model,
                           recommendation.prompt_version,
                           recommendation.generation_version,
                           bundle.status AS evidence_status
                    FROM recommendation
                    JOIN evidence_bundle AS bundle
                      ON bundle.evidence_bundle_id =
                         recommendation.evidence_bundle_id
                    WHERE recommendation.case_id = :case_id
                      AND recommendation.status = 'READY'
                    ORDER BY recommendation.version DESC
                    LIMIT 1
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .one()
    )
    action_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT recommendation_action_id, ordinal, title, description,
                           due_guidance, evidence_status, warning
                    FROM recommendation_action
                    WHERE recommendation_id = :recommendation_id
                    ORDER BY ordinal
                    """
                ),
                {"recommendation_id": recommendation["recommendation_id"]},
            )
        )
        .mappings()
        .all()
    )
    actions: list[dict[str, Any]] = []
    for action_row in action_rows:
        citations = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT citation.citation_id, citation.evidence_item_id,
                               citation.support_type, citation.quote_text,
                               citation.locator, item.evidence_group,
                               chunk.chunk_id, chunk.text_content,
                               document.document_id, document.title AS document_title,
                               document.document_number
                        FROM evidence_citation AS citation
                        JOIN evidence_item AS item
                          ON item.evidence_item_id = citation.evidence_item_id
                        JOIN rag_chunk AS chunk ON chunk.chunk_id = item.chunk_id
                        JOIN rag_document AS document
                          ON document.document_id = chunk.document_id
                        WHERE citation.recommendation_action_id = :action_id
                        ORDER BY citation.citation_id
                        """
                    ),
                    {"action_id": action_row["recommendation_action_id"]},
                )
            )
            .mappings()
            .all()
        )
        actions.append(
            {
                "ordinal": int(action_row["ordinal"]),
                "title": action_row["title"],
                "description": action_row["description"],
                "dueGuidance": action_row["due_guidance"],
                "evidenceStatus": action_row["evidence_status"],
                "warning": action_row["warning"],
                "citations": [
                    {
                        "citationId": str(row["citation_id"]),
                        "evidenceItemId": str(row["evidence_item_id"]),
                        "supportType": row["support_type"],
                        "quote": row["quote_text"],
                        "locator": row["locator"],
                        "evidenceGroup": row["evidence_group"],
                        "chunkId": str(row["chunk_id"]),
                        "sourceText": row["text_content"],
                        "documentId": str(row["document_id"]),
                        "documentTitle": row["document_title"],
                        "documentNumber": row["document_number"],
                    }
                    for row in citations
                ],
            }
        )
    evidence_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT item.excerpt, item.locator,
                           document.title AS document_title,
                           document.document_number
                    FROM evidence_item AS item
                    JOIN evidence_bundle AS bundle
                      ON bundle.evidence_bundle_id = item.evidence_bundle_id
                    JOIN rag_chunk AS chunk ON chunk.chunk_id = item.chunk_id
                    JOIN rag_document AS document
                      ON document.document_id = chunk.document_id
                    WHERE bundle.case_id = :case_id AND bundle.is_current
                    """
                ),
                {"case_id": case_id},
            )
        )
        .mappings()
        .all()
    )
    evidence_numbers = sorted(
        {
            number
            for row in evidence_rows
            for number in NUMBER_PATTERN.findall(
                " ".join(
                    (
                        str(row["excerpt"]),
                        str(row["locator"]),
                        str(row["document_title"]),
                        str(row["document_number"] or ""),
                    )
                )
            )
        }
    )
    return {
        "situationSummary": recommendation["situation_summary"],
        "requiredChecks": recommendation["required_checks"],
        "uncertainties": recommendation["uncertainties"],
        "conflicts": recommendation["conflicts"],
        "warning": recommendation["warning"],
        "classification": recommendation["evidence_status"],
        "evidenceNumbers": evidence_numbers,
        "model": recommendation["model"],
        "promptVersion": recommendation["prompt_version"],
        "generationVersion": recommendation["generation_version"],
        "actions": actions,
    }


def _evaluate_generation(
    question: dict[str, Any],
    generation: dict[str, Any],
) -> dict[str, Any]:
    citation_count = 0
    citation_integrity_errors: list[str] = []
    warning_errors: list[str] = []
    past_case_errors: list[str] = []
    unsupported_numbers: set[str] = set()
    supported_actions = 0
    action_count = len(generation["actions"])
    allowed_numbers = set(generation["evidenceNumbers"])
    allowed_numbers.update(NUMBER_PATTERN.findall(question["question"]))

    for action in generation["actions"]:
        action_text = f"{action['title']} {action['description']}"
        action_tokens = _tokens(action_text)
        direct_support = False
        for citation in action["citations"]:
            citation_count += 1
            quote = str(citation["quote"])
            source_text = str(citation["sourceText"])
            if quote not in source_text:
                citation_integrity_errors.append(f"{citation['citationId']}: quote mismatch")
            if not citation["locator"]:
                citation_integrity_errors.append(f"{citation['citationId']}: empty locator")
            if (
                citation["evidenceGroup"] == "PAST_INCIDENT"
                and citation["supportType"] != "CASE_EXAMPLE"
            ):
                past_case_errors.append(str(citation["citationId"]))
            quote_tokens = _tokens(quote)
            if citation["supportType"] == "DIRECT" and len(action_tokens & quote_tokens) >= 2:
                direct_support = True
        status = str(action["evidenceStatus"])
        if status != "SUFFICIENT" and not action["warning"]:
            warning_errors.append(f"action-{action['ordinal']}")
        if status == "SUFFICIENT":
            supported_actions += int(direct_support)
        elif action["warning"]:
            supported_actions += 1

    if generation["classification"] != "SUFFICIENT" and not generation["warning"]:
        warning_errors.append("recommendation")

    all_generated_text = " ".join(
        [
            str(generation["situationSummary"]),
            json.dumps(generation["requiredChecks"], ensure_ascii=False),
            json.dumps(generation["uncertainties"], ensure_ascii=False),
            json.dumps(generation["conflicts"], ensure_ascii=False),
            *[
                f"{action['title']} {action['description']} {action['dueGuidance'] or ''}"
                for action in generation["actions"]
            ],
        ]
    )
    for number in NUMBER_PATTERN.findall(all_generated_text):
        if number not in allowed_numbers:
            unsupported_numbers.add(number)

    expected_classification = question.get("expectedClassification")
    classification_correct = (
        expected_classification is None or generation["classification"] == expected_classification
    )
    return {
        "citationCount": citation_count,
        "citationIntegrityPassed": not citation_integrity_errors,
        "citationIntegrityErrors": citation_integrity_errors,
        "warningPassed": not warning_errors,
        "warningErrors": warning_errors,
        "pastCasesMarkedAsExamples": not past_case_errors,
        "pastCaseErrors": past_case_errors,
        "supportedActionCount": supported_actions,
        "actionCount": action_count,
        "actionSupportAccuracy": (supported_actions / action_count if action_count else 0.0),
        "unsupportedNumbers": sorted(unsupported_numbers),
        "noUnsupportedNumbers": not unsupported_numbers,
        "expectedClassification": expected_classification,
        "classificationCorrect": classification_correct,
    }


async def _cost_snapshot(settings: Settings) -> dict[str, Any]:
    if settings.ai_control_database_url is None:
        raise RuntimeError("AI_CONTROL_DATABASE_URL_REQUIRED")
    engine = create_async_engine(settings.ai_control_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT count(*) FILTER (WHERE status = 'SUCCESS') AS calls,
                                   coalesce(
                                     sum(actual_cost_usd)
                                     FILTER (WHERE status = 'SUCCESS'),
                                     0
                                   ) AS estimated_cost
                            FROM ai_cost_entry
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )
        return {
            "successfulCalls": int(row["calls"]),
            "estimatedCostUsd": str(Decimal(row["estimated_cost"])),
        }
    finally:
        await engine.dispose()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def run(fixture_path: Path, output_path: Path) -> int:
    fixture = json.loads(await asyncio.to_thread(fixture_path.read_text, encoding="utf-8"))
    questions = fixture["questions"]
    if len(questions) != 30:
        raise ValueError(f"expected 30 questions, got {len(questions)}")
    if len({question["id"] for question in questions}) != len(questions):
        raise ValueError("question IDs must be unique")
    for question in questions:
        _question_contract(question)

    settings = Settings()
    if settings.profile != "DEMO":
        raise RuntimeError("RAG evaluation is restricted to the DEMO profile")
    if settings.upstage_api_key is None:
        raise RuntimeError("UPSTAGE_API_KEY_REQUIRED")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    gate = AiCostGate(settings)
    started_at = datetime.now(UTC)
    run_token = started_at.strftime("%H%M%S")
    before_cost = await _cost_snapshot(settings)
    async with engine.connect() as connection:
        index = await _active_index(connection)
    report: dict[str, Any] = {
        "evaluationVersion": EVALUATION_VERSION,
        "fixtureVersion": fixture["version"],
        "startedAt": started_at.isoformat(),
        "status": "RUNNING",
        "profile": settings.profile,
        "index": index,
        "retrievalVersion": RETRIEVAL_VERSION,
        "embeddingModel": settings.upstage_embed_query_model,
        "chatModel": settings.upstage_chat_model,
        "promptVersion": PROMPT_VERSION,
        "generationVersion": GENERATION_VERSION,
        "costBefore": before_cost,
        "questions": [],
    }
    _write_report(output_path, report)

    try:
        for ordinal, question in enumerate(questions, start=1):
            question_started = time.monotonic()
            case_id: UUID | None = None
            result: dict[str, Any] = {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                "rationale": question["rationale"],
                "status": "RUNNING",
            }
            try:
                case_id = await _insert_case(engine, question, ordinal, run_token)
                retrieval = await run_case_retrieval(settings, case_id)
                async with engine.connect() as connection:
                    query_text = await _latest_query(connection, case_id)
                embedding = await UpstageEmbeddingClient(settings, gate).embed_query(
                    query_text,
                    feature_name="rag-evaluation-query-v1",
                    privacy_verified=True,
                    case_reference=case_id,
                )
                async with engine.connect() as connection:
                    lexical, vector = await _search_channels(
                        connection,
                        index_version_id=UUID(str(index["index_version_id"])),
                        query_text=query_text,
                        query_vector=embedding.vectors[0],
                    )
                candidates = fuse_candidates(
                    lexical,
                    vector,
                    primary_region_code=question["regionCode"],
                    today=started_at.date(),
                )
                ranking_group = (
                    "PAST_INCIDENT"
                    if question["category"]
                    in {"NORMAL_INCIDENT", "MAJOR_INCIDENT"}
                    else "OFFICIAL"
                )
                grouped_candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.group == ranking_group
                ]
                top_documents = _unique_documents(grouped_candidates, 5)
                top_chunks = [
                    str(candidate.row["chunk_id"])
                    for candidate in grouped_candidates[:10]
                ]
                expected_documents = [str(value) for value in question["expectedDocumentIds"]]
                expected_chunks = [str(value) for value in question["expectedChunkIds"]]
                if question["category"] == "CONFLICT":
                    document_hit = set(expected_documents).issubset(top_documents)
                else:
                    document_hit = not expected_documents or bool(
                        set(expected_documents) & set(top_documents)
                    )
                location_hit = not expected_chunks or bool(set(expected_chunks) & set(top_chunks))

                generation_started = time.monotonic()
                recommendation_result = await run_case_recommendation(settings, case_id)
                generation_elapsed_ms = int((time.monotonic() - generation_started) * 1000)
                async with engine.connect() as connection:
                    generation = await _fetch_generation_result(connection, case_id)
                generation_checks = _evaluate_generation(question, generation)

                authority_passed = True
                if question["category"] == "AUTHORITY_PRIORITY":
                    first_incident = next(
                        (
                            index
                            for index, candidate in enumerate(candidates)
                            if candidate.group == "PAST_INCIDENT"
                        ),
                        len(candidates),
                    )
                    first_expected = next(
                        (
                            index
                            for index, candidate in enumerate(candidates)
                            if str(candidate.row["document_id"]) in expected_documents
                        ),
                        len(candidates),
                    )
                    authority_passed = first_expected < first_incident

                result.update(
                    {
                        "status": "SUCCESS",
                        "queryText": query_text,
                        "retrieval": retrieval,
                        "queryEmbeddingCacheHit": embedding.cache_hit,
                        "rankingGroup": ranking_group,
                        "globalTop5DocumentIds": _unique_documents(candidates, 5),
                        "top5DocumentIds": top_documents,
                        "top10ChunkIds": top_chunks,
                        "expectedDocumentIds": expected_documents,
                        "expectedChunkIds": expected_chunks,
                        "documentRecallHit": document_hit,
                        "locationRecallHit": location_hit,
                        "authorityPriorityPassed": authority_passed,
                        "recommendationRun": recommendation_result,
                        "generationElapsedMs": generation_elapsed_ms,
                        "generation": generation,
                        "generationChecks": generation_checks,
                    }
                )
            except Exception as error:
                result.update(
                    {
                        "status": "FAILED",
                        "errorType": type(error).__name__,
                        "error": str(error)[:600],
                    }
                )
            finally:
                if case_id is not None:
                    try:
                        await _cleanup_case(engine, case_id)
                    except Exception as cleanup_error:
                        result["cleanupError"] = (
                            f"{type(cleanup_error).__name__}: {str(cleanup_error)[:400]}"
                        )
                result["elapsedMs"] = int((time.monotonic() - question_started) * 1000)
                report["questions"].append(result)
                _write_report(output_path, report)
                print(
                    f"[{ordinal:02d}/30] {question['id']} "
                    f"{result['status']} {result['elapsedMs']}ms",
                    flush=True,
                )
    finally:
        await gate.close()
        await engine.dispose()

    successful = [item for item in report["questions"] if item["status"] == "SUCCESS"]
    retrieval_times = [int(item["retrieval"]["elapsedMs"]) for item in successful]
    generation_times = [int(item["generationElapsedMs"]) for item in successful]
    document_questions = [item for item in successful if item["expectedDocumentIds"]]
    location_questions = [item for item in successful if item["expectedChunkIds"]]
    classification_questions = [
        item
        for item in successful
        if item["generationChecks"]["expectedClassification"] is not None
    ]
    action_count = sum(item["generationChecks"]["actionCount"] for item in successful)
    supported_actions = sum(item["generationChecks"]["supportedActionCount"] for item in successful)
    metrics: dict[str, Any] = {
        "questionSuccess": len(successful) / len(questions),
        "documentRecallAt5": (
            sum(item["documentRecallHit"] for item in document_questions) / len(document_questions)
            if document_questions
            else 0.0
        ),
        "locationRecallAt10": (
            sum(item["locationRecallHit"] for item in location_questions) / len(location_questions)
            if location_questions
            else 0.0
        ),
        "citationIntegrity": all(
            item["generationChecks"]["citationIntegrityPassed"] for item in successful
        ),
        "actionSupportAccuracy": (supported_actions / action_count if action_count else 0.0),
        "authorityPriority": all(
            item["authorityPriorityPassed"]
            for item in successful
            if item["category"] == "AUTHORITY_PRIORITY"
        ),
        "classificationAccuracy": (
            sum(
                item["generationChecks"]["classificationCorrect"]
                for item in classification_questions
            )
            / len(classification_questions)
            if classification_questions
            else 0.0
        ),
        "warningOmissions": sum(
            len(item["generationChecks"]["warningErrors"]) for item in successful
        ),
        "unsupportedNumberCount": sum(
            len(item["generationChecks"]["unsupportedNumbers"]) for item in successful
        ),
        "pastCaseMislabelCount": sum(
            len(item["generationChecks"]["pastCaseErrors"]) for item in successful
        ),
        "searchP50Ms": int(statistics.median(retrieval_times)) if retrieval_times else None,
        "searchP95Ms": _percentile(retrieval_times, 0.95),
        "generationP50Ms": int(statistics.median(generation_times)) if generation_times else None,
        "generationP95Ms": _percentile(generation_times, 0.95),
    }
    thresholds = {
        "questionSuccess": 1.0,
        "documentRecallAt5": 0.80,
        "locationRecallAt10": 0.80,
        "citationIntegrity": True,
        "actionSupportAccuracy": 0.90,
        "authorityPriority": True,
        "classificationAccuracy": 0.90,
        "warningOmissions": 0,
        "unsupportedNumberCount": 0,
        "pastCaseMislabelCount": 0,
        "searchP95MsMaximum": 10_000,
    }
    passed = (
        metrics["questionSuccess"] == 1.0
        and metrics["documentRecallAt5"] >= 0.80
        and metrics["locationRecallAt10"] >= 0.80
        and metrics["citationIntegrity"] is True
        and metrics["actionSupportAccuracy"] >= 0.90
        and metrics["authorityPriority"] is True
        and metrics["classificationAccuracy"] >= 0.90
        and metrics["warningOmissions"] == 0
        and metrics["unsupportedNumberCount"] == 0
        and metrics["pastCaseMislabelCount"] == 0
        and metrics["searchP95Ms"] is not None
        and metrics["searchP95Ms"] <= 10_000
    )
    after_cost = await _cost_snapshot(settings)
    report.update(
        {
            "status": "PASSED" if passed else "FAILED",
            "finishedAt": datetime.now(UTC).isoformat(),
            "metrics": metrics,
            "thresholds": thresholds,
            "costAfter": after_cost,
            "estimatedEvaluationCostUsd": str(
                Decimal(after_cost["estimatedCostUsd"]) - Decimal(before_cost["estimatedCostUsd"])
            ),
        }
    )
    _write_report(output_path, report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments.fixture, arguments.output)))


if __name__ == "__main__":
    main()
