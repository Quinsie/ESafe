from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import psycopg
from psycopg import Cursor
from psycopg.types.json import Jsonb

from esafe_importer.config import required_environment, sha256_file
from esafe_importer.domain import stable_uuid
from esafe_importer.rag_sources import detect_privacy
from esafe_importer.similarity import parse_report_date

EMBEDDING_MODEL = "solar-embedding-2-passage"
EMBEDDING_DIMENSION = 1024
INDEX_IMPORT_VERSION = "rag-index-import-v1"

_DISASTER_TERMS = (
    "화재",
    "감전",
    "정전",
    "호우",
    "폭염",
    "태풍",
    "강풍",
    "지진",
    "지진해일",
    "산사태",
    "산불",
    "이안류",
    "전기재난",
)
_REGION_ALIASES = (
    ("광주광역시", ("광주광역시", "광주")),
    ("전라남도", ("전라남도", "전남")),
    ("서울특별시", ("서울특별시", "서울")),
    ("부산광역시", ("부산광역시", "부산")),
    ("대구광역시", ("대구광역시", "대구")),
    ("인천광역시", ("인천광역시", "인천")),
    ("대전광역시", ("대전광역시", "대전")),
    ("울산광역시", ("울산광역시", "울산")),
    ("세종특별자치시", ("세종특별자치시", "세종")),
    ("경기도", ("경기도", "경기")),
    ("강원특별자치도", ("강원특별자치도", "강원도", "강원")),
    ("충청북도", ("충청북도", "충북")),
    ("충청남도", ("충청남도", "충남")),
    ("전북특별자치도", ("전북특별자치도", "전라북도", "전북")),
    ("경상북도", ("경상북도", "경북")),
    ("경상남도", ("경상남도", "경남")),
    ("제주특별자치도", ("제주특별자치도", "제주도", "제주")),
)


@dataclass(frozen=True, slots=True)
class RagIndexConfig:
    database_url: str
    derived_root: Path

    @classmethod
    def from_environment(cls) -> RagIndexConfig:
        return cls(
            database_url=required_environment("DATABASE_URL"),
            derived_root=Path(os.getenv("RAG_DERIVED_ROOT", "/reference/rag")),
        )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_verified_bundle(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = root / "build-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("RAG derived manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    metrics = manifest.get("metrics")
    if not isinstance(documents, list) or not isinstance(metrics, dict):
        raise ValueError("RAG derived manifest structure is invalid")
    if len(documents) != 246:
        raise ValueError("RAG source count must be 246")
    primary = [item for item in documents if item.get("source_status") == "PRIMARY"]
    duplicates = [item for item in documents if item.get("source_status") == "DUPLICATE"]
    if len(primary) != 241 or len(duplicates) != 5:
        raise ValueError("RAG unique/duplicate source counts are invalid")
    seen_documents: set[str] = set()
    chunk_count = 0
    for document in primary:
        document_id = str(document.get("document_id", ""))
        if not re.fullmatch(r"[0-9a-f-]{36}", document_id) or document_id in seen_documents:
            raise ValueError("RAG primary document identity is invalid")
        seen_documents.add(document_id)
        if (
            document.get("parse_status") != "PARSED"
            or document.get("privacy_status") not in {"PUBLIC_SAFE", "MASKED_VERIFIED"}
            or document.get("failure_reason") is not None
        ):
            raise ValueError("RAG document is not indexable")
        safe_relative = PurePosixPath(str(document.get("safe_copy_path", "")))
        if safe_relative.is_absolute() or ".." in safe_relative.parts:
            raise ValueError("RAG safe copy path is unsafe")
        safe_path = root / Path(*safe_relative.parts)
        if not safe_path.is_file() or sha256_file(safe_path) != document.get("safe_copy_sha256"):
            raise ValueError("RAG safe copy hash mismatch")
        artifact = json.loads(safe_path.read_text(encoding="utf-8"))
        chunks = artifact.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("RAG safe copy has no chunks")
        safe_text = "\n".join(
            [str(artifact.get("title", "")), *(str(item.get("text", "")) for item in chunks)]
        )
        if detect_privacy(safe_text):
            raise ValueError("RAG safe copy has a privacy residual")
        document["_artifact"] = artifact
        chunk_count += len(chunks)
    for duplicate in duplicates:
        if (
            duplicate.get("document_id") not in seen_documents
            or duplicate.get("duplicate_of_document_id") != duplicate.get("document_id")
        ):
            raise ValueError("RAG duplicate source linkage is invalid")
    if chunk_count != int(metrics.get("chunk_count", -1)):
        raise ValueError("RAG chunk count mismatch")
    return manifest, documents


def extract_disaster_types(value: str) -> list[str]:
    return [term for term in _DISASTER_TERMS if term in value]


def extract_regions(value: str) -> list[str]:
    return [
        canonical
        for canonical, aliases in _REGION_ALIASES
        if any(alias in value for alias in aliases)
    ]


def source_date(value: str) -> date | None:
    return parse_report_date(value)


class RagIndexImporter:
    def __init__(self, config: RagIndexConfig) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        manifest, sources = load_verified_bundle(self.config.derived_root)
        source_manifest_hash = str(manifest["source_manifest_sha256"])
        index_key = ":".join(
            (
                source_manifest_hash,
                str(manifest["parser_version"]),
                str(manifest["privacy_version"]),
                str(manifest["chunk_version"]),
                EMBEDDING_MODEL,
                INDEX_IMPORT_VERSION,
            )
        )
        index_version_id = stable_uuid("rag-index", index_key)
        with psycopg.connect(
            self.config.database_url,
            application_name="esafe-rag-index-importer",
        ) as connection, connection.transaction():
            cursor = connection.cursor()
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('esafe-rag-index-import'))")
            cursor.execute("SET LOCAL lock_timeout = '30s'")
            cursor.execute("SET LOCAL statement_timeout = '0'")
            cursor.execute(
                """
                SELECT document_count, chunk_count
                FROM rag_index_version
                WHERE index_version_id = %s
                """,
                (index_version_id,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if (int(existing[0]), int(existing[1])) != (241, 14_311):
                    raise ValueError("existing RAG index counts do not match")
                return {
                    "status": "SKIPPED",
                    "index_version_id": str(index_version_id),
                    "document_count": int(existing[0]),
                    "chunk_count": int(existing[1]),
                }
            self._insert_index(cursor, index_version_id, manifest, sources)
            self._validate(cursor, index_version_id)
            cursor.execute("ANALYZE rag_document")
            cursor.execute("ANALYZE rag_document_source")
            cursor.execute("ANALYZE rag_chunk")
        return {
            "status": "SUCCESS",
            "index_version_id": str(index_version_id),
            "document_count": 241,
            "source_count": 246,
            "chunk_count": 14_311,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }

    def _insert_index(
        self,
        cursor: Cursor[Any],
        index_version_id: Any,
        manifest: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO rag_index_version (
                index_version_id, status, source_manifest_sha256,
                parser_version, privacy_version, embedding_model,
                embedding_dimension, document_count, chunk_count, failure_summary
            )
            VALUES (%s, 'BUILDING', %s, %s, %s, %s, %s, 241, 14311, '{}'::jsonb)
            """,
            (
                index_version_id,
                manifest["source_manifest_sha256"],
                manifest["parser_version"],
                manifest["privacy_version"],
                EMBEDDING_MODEL,
                EMBEDDING_DIMENSION,
            ),
        )
        primary_source_ids: dict[str, Any] = {}
        for source in sources:
            if source["source_status"] != "PRIMARY":
                continue
            artifact = source["_artifact"]
            source_path = str(source["source_path"])
            searchable_metadata = f"{source_path} {artifact['title']}"
            published_at = source_date(source_path)
            contains_personal_data = (
                source["confidentiality"] == "RESTRICTED"
                or sum(int(value) for value in artifact.get("mask_counts", {}).values()) > 0
            )
            cursor.execute(
                """
                INSERT INTO rag_document (
                    document_id, logical_key, version, document_family, title,
                    published_at, disaster_types, regions, authority_level,
                    confidentiality, privacy_status, contains_personal_data,
                    source_format, source_path, source_sha256,
                    safe_copy_path, safe_copy_sha256, parser_version,
                    parse_status, parse_summary, is_current
                )
                VALUES (
                    %s, %s, 1, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    'PARSED', %s, false
                )
                """,
                (
                    source["document_id"],
                    f"initial:{source['source_sha256']}",
                    source["document_family"],
                    artifact["title"],
                    published_at,
                    extract_disaster_types(searchable_metadata),
                    extract_regions(searchable_metadata),
                    source["authority_level"],
                    source["confidentiality"],
                    source["privacy_status"],
                    contains_personal_data,
                    source["source_format"],
                    source_path,
                    source["source_sha256"],
                    f"rag/{source['safe_copy_path']}",
                    source["safe_copy_sha256"],
                    manifest["parser_version"],
                    Jsonb(source["parse_summary"]),
                ),
            )
            document_source_id = stable_uuid(
                "rag-document-source",
                f"{source_path}:{source['source_sha256']}",
            )
            primary_source_ids[str(source["document_id"])] = document_source_id
            self._insert_source(cursor, source, document_source_id, None)
            chunk_rows = []
            for chunk in artifact["chunks"]:
                text_content = str(chunk["text"])
                ordinal = int(chunk["ordinal"])
                chunk_rows.append(
                    (
                        stable_uuid(
                            "rag-chunk",
                            f"{index_version_id}:{source['document_id']}:{ordinal}",
                        ),
                        source["document_id"],
                        index_version_id,
                        ordinal,
                        chunk["locator"],
                        chunk.get("heading_path", []),
                        None,
                        text_content,
                        Jsonb(chunk["table_context"])
                        if chunk.get("table_context") is not None
                        else None,
                        len(text_content),
                    )
                )
            cursor.executemany(
                """
                INSERT INTO rag_chunk (
                    chunk_id, document_id, index_version_id, ordinal,
                    page_or_section, heading_path, paragraph_index,
                    text_content, table_context, character_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                chunk_rows,
            )
        for source in sources:
            if source["source_status"] != "DUPLICATE":
                continue
            document_source_id = stable_uuid(
                "rag-document-source",
                f"{source['source_path']}:{source['source_sha256']}",
            )
            self._insert_source(
                cursor,
                source,
                document_source_id,
                primary_source_ids[str(source["document_id"])],
            )

    @staticmethod
    def _insert_source(
        cursor: Cursor[Any],
        source: dict[str, Any],
        document_source_id: Any,
        duplicate_of_source_id: Any | None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO rag_document_source (
                document_source_id, document_id, source_path, source_sha256,
                source_size, source_status, duplicate_of_source_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document_source_id,
                source["document_id"],
                source["source_path"],
                source["source_sha256"],
                source["source_size"],
                source["source_status"],
                duplicate_of_source_id,
            ),
        )

    @staticmethod
    def _validate(cursor: Cursor[Any], index_version_id: Any) -> None:
        checks = (
            ("document count", "SELECT count(*) FROM rag_document", 241),
            ("source count", "SELECT count(*) FROM rag_document_source", 246),
            (
                "duplicate source count",
                "SELECT count(*) FROM rag_document_source WHERE source_status = 'DUPLICATE'",
                5,
            ),
            (
                "chunk count",
                "SELECT count(*) FROM rag_chunk WHERE index_version_id = %s",
                14_311,
            ),
            (
                "privacy status",
                """
                SELECT count(*) FROM rag_document
                WHERE privacy_status NOT IN ('PUBLIC_SAFE', 'MASKED_VERIFIED')
                   OR parse_status <> 'PARSED'
                """,
                0,
            ),
            (
                "embedding before external call",
                "SELECT count(*) FROM rag_chunk WHERE embedding IS NOT NULL",
                0,
            ),
        )
        for label, query, expected in checks:
            params = (index_version_id,) if "%s" in query else ()
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"RAG import validation returned no row: {label}")
            actual = int(row[0])
            if actual != expected:
                raise ValueError(f"RAG import validation failed: {label} ({actual} != {expected})")


def main(argv: Sequence[str] | None = None) -> None:
    if argv:
        raise ValueError("rag index importer does not accept arguments")
    result = RagIndexImporter(RagIndexConfig.from_environment()).run()
    print(compact_json(result))


if __name__ == "__main__":
    main()
