from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from array import array
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from app.ai_control import AiCostGate
from app.config import Settings
from app.upstage import (
    EMBEDDING_DIMENSION,
    UpstageEmbeddingClient,
    embedding_cost,
    embedding_request_hash,
)

REFERENCE_NAMESPACE = uuid.UUID("963b5245-20a9-5500-80ab-ac380507d08f")
INDEX_IMPORT_VERSION = "rag-index-import-v1"
BUNDLE_VERSION = "rag-embedding-bundle-v1"
BATCH_SIZE = 100
EXPECTED_DOCUMENTS = 241
EXPECTED_CHUNKS = 14_311


@dataclass(frozen=True, slots=True)
class ChunkInput:
    chunk_id: str
    document_id: str
    ordinal: int
    input_sha256: str
    text: str


def compact_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_uuid(kind: str, source_key: str) -> uuid.UUID:
    return uuid.uuid5(REFERENCE_NAMESPACE, f"{kind}:{source_key}")


def vector_bytes(vectors: list[list[float]]) -> bytes:
    flattened = array("f", (value for vector in vectors for value in vector))
    if sys.byteorder != "little":
        flattened.byteswap()
    return flattened.tobytes()


def atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def load_inputs(root: Path, model: str) -> tuple[dict[str, Any], str, list[ChunkInput]]:
    manifest_path = root / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    metrics = manifest.get("metrics")
    if not isinstance(documents, list) or not isinstance(metrics, dict):
        raise ValueError("RAG_DERIVED_MANIFEST_INVALID")
    primary = [item for item in documents if item.get("source_status") == "PRIMARY"]
    if (
        len(primary) != EXPECTED_DOCUMENTS
        or int(metrics.get("chunk_count", -1)) != EXPECTED_CHUNKS
        or int(metrics.get("masked_finding_count", 0)) <= 0
        or int(metrics.get("failed_count", -1)) != 0
        or int(metrics.get("review_required_count", -1)) != 0
    ):
        raise ValueError("RAG_DERIVED_COUNTS_INVALID")
    source_manifest_sha256 = str(manifest.get("source_manifest_sha256", ""))
    if len(source_manifest_sha256) != 64:
        raise ValueError("RAG_SOURCE_MANIFEST_HASH_INVALID")
    index_key = ":".join(
        (
            source_manifest_sha256,
            str(manifest["parser_version"]),
            str(manifest["privacy_version"]),
            str(manifest["chunk_version"]),
            model,
            INDEX_IMPORT_VERSION,
        )
    )
    index_version_id = str(stable_uuid("rag-index", index_key))
    chunks: list[ChunkInput] = []
    seen: set[str] = set()
    for document in primary:
        if (
            document.get("parse_status") != "PARSED"
            or document.get("privacy_status") not in {"PUBLIC_SAFE", "MASKED_VERIFIED"}
            or document.get("failure_reason") is not None
            or document.get("parse_summary", {}).get("residual_counts")
        ):
            raise ValueError("RAG_DOCUMENT_PRIVACY_NOT_VERIFIED")
        relative = PurePosixPath(str(document.get("safe_copy_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("RAG_SAFE_PATH_INVALID")
        document_path = root / Path(*relative.parts)
        if sha256_file(document_path) != document.get("safe_copy_sha256"):
            raise ValueError("RAG_SAFE_COPY_HASH_MISMATCH")
        artifact = json.loads(document_path.read_text(encoding="utf-8"))
        document_id = str(document["document_id"])
        if (
            artifact.get("document_id") != document_id
            or artifact.get("privacy_status") not in {"PUBLIC_SAFE", "MASKED_VERIFIED"}
            or artifact.get("privacy_version") != manifest["privacy_version"]
            or artifact.get("chunk_version") != manifest["chunk_version"]
        ):
            raise ValueError("RAG_SAFE_COPY_CONTRACT_INVALID")
        for chunk in artifact.get("chunks", []):
            text = str(chunk.get("text", ""))
            ordinal = int(chunk.get("ordinal", 0))
            if not text.strip() or ordinal <= 0:
                raise ValueError("RAG_CHUNK_INVALID")
            chunk_id = str(
                stable_uuid(
                    "rag-chunk",
                    f"{index_version_id}:{document_id}:{ordinal}",
                )
            )
            if chunk_id in seen:
                raise ValueError("RAG_CHUNK_DUPLICATE")
            seen.add(chunk_id)
            chunks.append(
                ChunkInput(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    ordinal=ordinal,
                    input_sha256=sha256_bytes(text.encode("utf-8")),
                    text=text,
                )
            )
    if len(chunks) != EXPECTED_CHUNKS:
        raise ValueError("RAG_CHUNK_COUNT_INVALID")
    return manifest, index_version_id, chunks


def validate_completed_batch(
    metadata_path: Path,
    vectors_path: Path,
    items: list[ChunkInput],
    model: str,
) -> dict[str, Any] | None:
    if not metadata_path.exists() and not vectors_path.exists():
        return None
    if not metadata_path.is_file() or not vectors_path.is_file():
        raise ValueError("RAG_EMBEDDING_BATCH_INCOMPLETE")
    metadata_value = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata_value, dict):
        raise ValueError("RAG_EMBEDDING_BATCH_INVALID")
    metadata = cast(dict[str, Any], metadata_value)
    expected_entries = [
        {
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "ordinal": item.ordinal,
            "input_sha256": item.input_sha256,
        }
        for item in items
    ]
    if (
        metadata.get("model") != model
        or metadata.get("dimension") != EMBEDDING_DIMENSION
        or metadata.get("request_sha256")
        != embedding_request_hash(model, [item.text for item in items])
        or metadata.get("entries") != expected_entries
        or int(metadata.get("vector_bytes", -1))
        != len(items) * EMBEDDING_DIMENSION * 4
        or metadata.get("vector_sha256") != sha256_file(vectors_path)
        or vectors_path.stat().st_size != len(items) * EMBEDDING_DIMENSION * 4
    ):
        raise ValueError("RAG_EMBEDDING_BATCH_INVALID")
    return metadata


async def build_embedding_bundle(settings: Settings) -> dict[str, Any]:
    derived_root = Path(os.getenv("RAG_DERIVED_ROOT", "/srv/esafe/reference/rag"))
    output_root = Path(
        os.getenv("RAG_EMBEDDING_OUTPUT_ROOT", "/srv/esafe/reference/rag-embeddings")
    )
    manifest, index_version_id, chunks = load_inputs(
        derived_root,
        settings.upstage_embed_passage_model,
    )
    bundle_key = ":".join(
        (
            BUNDLE_VERSION,
            str(manifest["source_manifest_sha256"]),
            index_version_id,
            settings.upstage_embed_passage_model,
            str(EMBEDDING_DIMENSION),
        )
    )
    bundle_id = sha256_bytes(bundle_key.encode("utf-8"))
    final_root = output_root / bundle_id
    if (final_root / "manifest.json").is_file():
        return {
            "status": "SKIPPED",
            "bundleId": bundle_id,
            "chunkCount": len(chunks),
        }
    working_root = output_root / f".{bundle_id}.building"
    batch_root = working_root / "batches"
    batch_root.mkdir(parents=True, exist_ok=True)
    gate = AiCostGate(settings)
    client = UpstageEmbeddingClient(settings, gate)
    batch_summaries: list[dict[str, Any]] = []
    total_tokens = 0
    try:
        for start in range(0, len(chunks), BATCH_SIZE):
            batch_index = start // BATCH_SIZE
            items = chunks[start : start + BATCH_SIZE]
            metadata_name = f"{batch_index:05d}.json"
            vectors_name = f"{batch_index:05d}.f32"
            metadata_path = batch_root / metadata_name
            vectors_path = batch_root / vectors_name
            metadata = validate_completed_batch(
                metadata_path,
                vectors_path,
                items,
                settings.upstage_embed_passage_model,
            )
            if metadata is None:
                result = await client.embed_passages(
                    [item.text for item in items],
                    feature_name=f"rag-corpus-{bundle_id[:12]}-{batch_index:05d}",
                    privacy_verified=True,
                )
                binary = vector_bytes(result.vectors)
                atomic_write(vectors_path, binary)
                metadata = {
                    "batch_index": batch_index,
                    "model": settings.upstage_embed_passage_model,
                    "dimension": EMBEDDING_DIMENSION,
                    "request_sha256": embedding_request_hash(
                        settings.upstage_embed_passage_model,
                        [item.text for item in items],
                    ),
                    "reservation_id": result.reservation_id,
                    "embedding_tokens": result.embedding_tokens,
                    "vector_file": vectors_name,
                    "vector_bytes": len(binary),
                    "vector_sha256": sha256_bytes(binary),
                    "entries": [
                        {
                            "chunk_id": item.chunk_id,
                            "document_id": item.document_id,
                            "ordinal": item.ordinal,
                            "input_sha256": item.input_sha256,
                        }
                        for item in items
                    ],
                }
                atomic_write(metadata_path, compact_json(metadata))
            total_tokens += int(metadata["embedding_tokens"])
            batch_summaries.append(
                {
                    "batch_index": batch_index,
                    "item_count": len(items),
                    "metadata_file": f"batches/{metadata_name}",
                    "metadata_sha256": sha256_file(metadata_path),
                    "vector_file": f"batches/{vectors_name}",
                    "vector_sha256": str(metadata["vector_sha256"]),
                    "embedding_tokens": int(metadata["embedding_tokens"]),
                    "reservation_id": str(metadata["reservation_id"]),
                }
            )
            print(
                compact_json(
                    {
                        "status": "BATCH_OK",
                        "batch": batch_index + 1,
                        "batchCount": (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE,
                        "itemCount": len(items),
                    }
                ).decode(),
                flush=True,
            )
    finally:
        await gate.close()
    bundle_manifest = {
        "bundle_version": BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "parser_version": manifest["parser_version"],
        "privacy_version": manifest["privacy_version"],
        "chunk_version": manifest["chunk_version"],
        "index_version_id": index_version_id,
        "model": settings.upstage_embed_passage_model,
        "dimension": EMBEDDING_DIMENSION,
        "document_count": EXPECTED_DOCUMENTS,
        "chunk_count": len(chunks),
        "batch_size": BATCH_SIZE,
        "batch_count": len(batch_summaries),
        "embedding_tokens": total_tokens,
        "estimated_cost_usd": str(embedding_cost(total_tokens)),
        "batches": batch_summaries,
    }
    atomic_write(working_root / "manifest.json", compact_json(bundle_manifest))
    os.replace(working_root, final_root)
    atomic_write(output_root / "CURRENT", f"{bundle_id}\n".encode())
    return {
        "status": "SUCCESS",
        "bundleId": bundle_id,
        "documentCount": EXPECTED_DOCUMENTS,
        "chunkCount": len(chunks),
        "batchCount": len(batch_summaries),
        "embeddingTokens": total_tokens,
        "estimatedCostUsd": str(embedding_cost(total_tokens)),
    }
