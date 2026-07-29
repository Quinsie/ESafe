from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import Cursor

from esafe_importer.config import required_environment, sha256_file

BUNDLE_VERSION = "rag-embedding-bundle-v1"
EXPECTED_DIMENSION = 1024
EXPECTED_DOCUMENTS = 241
EXPECTED_CHUNKS = 14_311
_BUNDLE_ID = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EmbeddingImportConfig:
    database_url: str
    bundle_root: Path

    @classmethod
    def from_environment(cls) -> EmbeddingImportConfig:
        return cls(
            database_url=required_environment("DATABASE_URL"),
            bundle_root=Path(
                os.getenv(
                    "RAG_EMBEDDING_BUNDLE_ROOT",
                    "/reference/rag-embeddings",
                )
            ),
        )


def discover_bundle(root: Path) -> tuple[Path, dict[str, Any]]:
    bundle_id = (root / "CURRENT").read_text(encoding="utf-8").strip()
    if not _BUNDLE_ID.fullmatch(bundle_id):
        raise ValueError("RAG embedding CURRENT pointer is invalid")
    bundle_path = root / bundle_id
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("bundle_version") != BUNDLE_VERSION
        or manifest.get("bundle_id") != bundle_id
        or manifest.get("dimension") != EXPECTED_DIMENSION
        or manifest.get("document_count") != EXPECTED_DOCUMENTS
        or manifest.get("chunk_count") != EXPECTED_CHUNKS
        or not isinstance(manifest.get("batches"), list)
        or len(manifest["batches"]) != manifest.get("batch_count")
    ):
        raise ValueError("RAG embedding manifest contract is invalid")
    return bundle_path, manifest


def load_vectors(path: Path, item_count: int) -> list[list[float]]:
    payload = path.read_bytes()
    if len(payload) != item_count * EXPECTED_DIMENSION * 4:
        raise ValueError("RAG embedding vector byte count is invalid")
    values = array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if not all(math.isfinite(value) for value in values):
        raise ValueError("RAG embedding vector contains a non-finite value")
    return [
        list(values[offset : offset + EXPECTED_DIMENSION])
        for offset in range(0, len(values), EXPECTED_DIMENSION)
    ]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


def verified_rows(
    bundle_path: Path,
    manifest: dict[str, Any],
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for expected_index, summary in enumerate(manifest["batches"]):
        if summary.get("batch_index") != expected_index:
            raise ValueError("RAG embedding batch order is invalid")
        metadata_path = bundle_path / str(summary["metadata_file"])
        vectors_path = bundle_path / str(summary["vector_file"])
        if (
            sha256_file(metadata_path) != summary.get("metadata_sha256")
            or sha256_file(vectors_path) != summary.get("vector_sha256")
        ):
            raise ValueError("RAG embedding batch hash mismatch")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        entries = metadata.get("entries")
        if (
            not isinstance(entries, list)
            or len(entries) != summary.get("item_count")
            or metadata.get("model") != manifest["model"]
            or metadata.get("dimension") != EXPECTED_DIMENSION
            or metadata.get("vector_sha256") != summary.get("vector_sha256")
        ):
            raise ValueError("RAG embedding batch metadata is invalid")
        vectors = load_vectors(vectors_path, len(entries))
        for entry, vector in zip(entries, vectors, strict=True):
            chunk_id = str(entry.get("chunk_id", ""))
            input_sha256 = str(entry.get("input_sha256", ""))
            if (
                chunk_id in seen
                or not _BUNDLE_ID.fullmatch(input_sha256)
                or not re.fullmatch(r"[0-9a-f-]{36}", chunk_id)
            ):
                raise ValueError("RAG embedding chunk metadata is invalid")
            seen.add(chunk_id)
            rows.append((chunk_id, input_sha256, vector_literal(vector)))
    if len(rows) != EXPECTED_CHUNKS:
        raise ValueError("RAG embedding row count is invalid")
    return rows


def verify_database_text(
    cursor: Cursor[Any],
    index_version_id: str,
    expected: dict[str, str],
) -> None:
    cursor.execute(
        """
        SELECT chunk_id, text_content
        FROM rag_chunk
        WHERE index_version_id = %s
        """,
        (index_version_id,),
    )
    rows = cursor.fetchall()
    if len(rows) != EXPECTED_CHUNKS:
        raise ValueError("RAG database chunk count does not match the bundle")
    for chunk_id, text_content in rows:
        actual = hashlib.sha256(str(text_content).encode("utf-8")).hexdigest()
        if expected.get(str(chunk_id)) != actual:
            raise ValueError("RAG database chunk text hash mismatch")


class RagEmbeddingImporter:
    def __init__(self, config: EmbeddingImportConfig) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        bundle_path, manifest = discover_bundle(self.config.bundle_root)
        rows = verified_rows(bundle_path, manifest)
        index_version_id = str(manifest["index_version_id"])
        expected_hashes = {row[0]: row[1] for row in rows}
        with psycopg.connect(
            self.config.database_url,
            application_name="esafe-rag-embedding-importer",
        ) as connection, connection.transaction():
            cursor = connection.cursor()
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext('esafe-rag-embedding-import'))"
            )
            cursor.execute("SET LOCAL lock_timeout = '30s'")
            cursor.execute("SET LOCAL statement_timeout = '0'")
            cursor.execute(
                """
                SELECT status, source_manifest_sha256, embedding_model,
                       embedding_dimension, document_count, chunk_count
                FROM rag_index_version
                WHERE index_version_id = %s
                FOR UPDATE
                """,
                (index_version_id,),
            )
            index_row = cursor.fetchone()
            if index_row is None:
                raise ValueError("RAG index version is missing")
            if (
                str(index_row[1]) != manifest["source_manifest_sha256"]
                or index_row[2] != manifest["model"]
                or int(index_row[3]) != EXPECTED_DIMENSION
                or int(index_row[4]) != EXPECTED_DOCUMENTS
                or int(index_row[5]) != EXPECTED_CHUNKS
            ):
                raise ValueError("RAG index version does not match the bundle")
            cursor.execute(
                """
                SELECT count(*)
                FROM rag_chunk
                WHERE index_version_id = %s
                  AND embedding IS NOT NULL
                  AND embedding_input_sha256 IS NOT NULL
                """,
                (index_version_id,),
            )
            embedded_row = cursor.fetchone()
            if embedded_row is None:
                raise ValueError("RAG embedding count returned no row")
            embedded_count = int(embedded_row[0])
            if index_row[0] == "ACTIVE" and embedded_count == EXPECTED_CHUNKS:
                return {
                    "status": "SKIPPED",
                    "bundle_id": manifest["bundle_id"],
                    "index_version_id": index_version_id,
                    "chunk_count": embedded_count,
                }
            if index_row[0] != "BUILDING" or embedded_count != 0:
                raise ValueError("RAG index is not in a clean BUILDING state")
            verify_database_text(cursor, index_version_id, expected_hashes)
            cursor.executemany(
                """
                UPDATE rag_chunk
                SET embedding = %s::vector(1024),
                    embedding_input_sha256 = %s,
                    embedding_model = %s,
                    embedding_version = %s,
                    embedded_at = CURRENT_TIMESTAMP
                WHERE chunk_id = %s
                  AND index_version_id = %s
                """,
                (
                    (
                        vector,
                        input_sha256,
                        manifest["model"],
                        BUNDLE_VERSION,
                        chunk_id,
                        index_version_id,
                    )
                    for chunk_id, input_sha256, vector in rows
                ),
            )
            cursor.execute(
                """
                SELECT count(*)
                FROM rag_chunk
                WHERE index_version_id = %s
                  AND embedding IS NOT NULL
                  AND embedding_input_sha256 IS NOT NULL
                  AND embedding_model = %s
                  AND embedding_version = %s
                """,
                (index_version_id, manifest["model"], BUNDLE_VERSION),
            )
            imported_row = cursor.fetchone()
            if imported_row is None or int(imported_row[0]) != EXPECTED_CHUNKS:
                raise ValueError("RAG embedding import count validation failed")
            cursor.execute(
                """
                UPDATE rag_index_version
                SET status = 'SUPERSEDED'
                WHERE status = 'ACTIVE'
                  AND index_version_id <> %s
                """,
                (index_version_id,),
            )
            cursor.execute("UPDATE rag_document SET is_current = false WHERE is_current")
            cursor.execute(
                """
                UPDATE rag_document
                SET is_current = true
                WHERE document_id IN (
                    SELECT document_id
                    FROM rag_chunk
                    WHERE index_version_id = %s
                )
                """,
                (index_version_id,),
            )
            cursor.execute(
                """
                UPDATE rag_index_version
                SET status = 'ACTIVE',
                    activated_at = CURRENT_TIMESTAMP,
                    failure_summary = '{}'::jsonb
                WHERE index_version_id = %s
                  AND status = 'BUILDING'
                """,
                (index_version_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("RAG index activation failed")
            cursor.execute("ANALYZE rag_chunk")
            cursor.execute("ANALYZE rag_document")
        return {
            "status": "SUCCESS",
            "bundle_id": manifest["bundle_id"],
            "index_version_id": index_version_id,
            "chunk_count": EXPECTED_CHUNKS,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def main() -> None:
    result = RagEmbeddingImporter(EmbeddingImportConfig.from_environment()).run()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
