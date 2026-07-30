from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.sld_analysis import SldContractError

DEMO_FIRE_BUILDING_SOURCE_KEY = "27971838"
DEMO_FIXTURE_FILE_NAME = "본사 사옥 수변전 설비 단선 결선도 -1.pdf"
DEMO_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "demo"
    / "fixtures"
    / "ds01_headquarters_single_line_diagram.pdf"
)


def _resolve_storage_path(storage_root: Path, relative_path: str) -> tuple[Path, Path]:
    root = storage_root.resolve()
    target = (root / relative_path).resolve()
    return root, target


def _payload(row: Any) -> dict[str, Any]:
    return {
        "documentId": str(row["building_sld_document_id"]),
        "buildingId": str(row["building_id"]),
        "sourceFileName": row["source_file_name"],
        "sourceMimeType": row["source_mime_type"],
        "sourceSizeBytes": int(row["source_size_bytes"]),
        "sourceSha256": row["source_sha256"],
        "documentOrigin": row["document_origin"],
        "uploadedBy": str(row["uploaded_by"]) if row["uploaded_by"] else None,
        "createdAt": row["created_at"].isoformat(),
        "updatedAt": row["updated_at"].isoformat(),
        "version": int(row["version"]),
    }


async def building_sld_document(
    engine: AsyncEngine,
    *,
    profile: str,
    building_id: UUID,
) -> dict[str, Any] | None:
    async with engine.connect() as connection:
        building_exists = (
            await connection.execute(
                text("SELECT 1 FROM building WHERE building_id = :building_id"),
                {"building_id": building_id},
            )
        ).scalar_one_or_none()
        if building_exists is None:
            raise SldContractError(404, "BUILDING_NOT_FOUND", "건물을 찾을 수 없습니다.")
        row = (
            await connection.execute(
                text(
                    """
                    SELECT *
                    FROM building_sld_document
                    WHERE profile = :profile AND building_id = :building_id
                    """
                ),
                {"profile": profile, "building_id": building_id},
            )
        ).mappings().one_or_none()
    return _payload(row) if row is not None else None


async def upsert_building_sld_document(
    engine: AsyncEngine,
    *,
    document_id: UUID,
    profile: str,
    building_id: UUID,
    source_file_name: str,
    source_mime_type: str,
    source_size_bytes: int,
    source_sha256: str,
    source_storage_path: str,
    user_id: UUID | None,
    document_origin: str = "MANAGER_UPLOAD",
) -> tuple[dict[str, Any], str | None, bool]:
    async with engine.begin() as connection:
        building_exists = (
            await connection.execute(
                text("SELECT 1 FROM building WHERE building_id = :building_id"),
                {"building_id": building_id},
            )
        ).scalar_one_or_none()
        if building_exists is None:
            raise SldContractError(404, "BUILDING_NOT_FOUND", "건물을 찾을 수 없습니다.")
        previous_path = (
            await connection.execute(
                text(
                    """
                    SELECT source_storage_path
                    FROM building_sld_document
                    WHERE profile = :profile AND building_id = :building_id
                    FOR UPDATE
                    """
                ),
                {"profile": profile, "building_id": building_id},
            )
        ).scalar_one_or_none()
        if document_origin == "DEMO_FIXTURE" and previous_path is not None:
            existing = (
                await connection.execute(
                    text(
                        """
                        SELECT *
                        FROM building_sld_document
                        WHERE profile = :profile AND building_id = :building_id
                        """
                    ),
                    {"profile": profile, "building_id": building_id},
                )
            ).mappings().one()
            return _payload(existing), None, False
        row = (
            await connection.execute(
                text(
                    """
                    INSERT INTO building_sld_document (
                        building_sld_document_id, building_id, profile,
                        source_file_name, source_mime_type, source_size_bytes,
                        source_sha256, source_storage_path, document_origin, uploaded_by
                    )
                    VALUES (
                        :document_id, :building_id, :profile,
                        :source_file_name, :source_mime_type, :source_size_bytes,
                        :source_sha256, :source_storage_path, :document_origin, :user_id
                    )
                    ON CONFLICT (profile, building_id) DO UPDATE
                    SET building_sld_document_id = EXCLUDED.building_sld_document_id,
                        source_file_name = EXCLUDED.source_file_name,
                        source_mime_type = EXCLUDED.source_mime_type,
                        source_size_bytes = EXCLUDED.source_size_bytes,
                        source_sha256 = EXCLUDED.source_sha256,
                        source_storage_path = EXCLUDED.source_storage_path,
                        document_origin = EXCLUDED.document_origin,
                        uploaded_by = EXCLUDED.uploaded_by,
                        updated_at = CURRENT_TIMESTAMP,
                        version = building_sld_document.version + 1
                    RETURNING *
                    """
                ),
                {
                    "document_id": document_id,
                    "building_id": building_id,
                    "profile": profile,
                    "source_file_name": source_file_name,
                    "source_mime_type": source_mime_type,
                    "source_size_bytes": source_size_bytes,
                    "source_sha256": source_sha256,
                    "source_storage_path": source_storage_path,
                    "document_origin": document_origin,
                    "user_id": user_id,
                },
            )
        ).mappings().one()
    return _payload(row), str(previous_path) if previous_path is not None else None, True


async def sld_document_source(
    engine: AsyncEngine,
    *,
    profile: str,
    building_id: UUID,
) -> tuple[str, str, str]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT source_storage_path, source_file_name, source_mime_type
                    FROM building_sld_document
                    WHERE profile = :profile AND building_id = :building_id
                    """
                ),
                {"profile": profile, "building_id": building_id},
            )
        ).one_or_none()
    if row is None:
        raise SldContractError(
            404,
            "SLD_DOCUMENT_NOT_FOUND",
            "등록된 단선결선도가 없습니다.",
        )
    return str(row[0]), str(row[1]), str(row[2])


async def ensure_demo_fire_building_document(
    engine: AsyncEngine,
    *,
    profile: str,
    building_id: UUID,
    storage_root: Path,
) -> None:
    if profile != "DEMO":
        return
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT b.source_building_key,
                           d.building_sld_document_id IS NOT NULL AS has_document
                    FROM building b
                    LEFT JOIN building_sld_document d
                      ON d.building_id = b.building_id AND d.profile = :profile
                    WHERE b.building_id = :building_id
                    """
                ),
                {"profile": profile, "building_id": building_id},
            )
        ).mappings().one_or_none()
    if (
        row is None
        or row["source_building_key"] != DEMO_FIRE_BUILDING_SOURCE_KEY
        or bool(row["has_document"])
    ):
        return
    if not await asyncio.to_thread(DEMO_FIXTURE_PATH.is_file):
        raise SldContractError(
            500,
            "SLD_DEMO_FIXTURE_MISSING",
            "DEMO 단선결선도 원본을 찾을 수 없습니다.",
        )

    content = await asyncio.to_thread(DEMO_FIXTURE_PATH.read_bytes)
    source_sha256 = hashlib.sha256(content).hexdigest()
    document_id = uuid4()
    relative_path = f"documents/{document_id}/source.pdf"
    root, target = await asyncio.to_thread(_resolve_storage_path, storage_root, relative_path)
    if root not in target.parents:
        raise SldContractError(500, "SLD_STORAGE_PATH_INVALID", "저장 경로가 올바르지 않습니다.")
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=False)
    await asyncio.to_thread(target.write_bytes, content)
    try:
        _, previous_path, stored = await upsert_building_sld_document(
            engine,
            document_id=document_id,
            profile=profile,
            building_id=building_id,
            source_file_name=DEMO_FIXTURE_FILE_NAME,
            source_mime_type="application/pdf",
            source_size_bytes=len(content),
            source_sha256=source_sha256,
            source_storage_path=relative_path,
            user_id=None,
            document_origin="DEMO_FIXTURE",
        )
    except Exception:
        await asyncio.to_thread(target.unlink, missing_ok=True)
        raise
    if not stored:
        await asyncio.to_thread(target.unlink, missing_ok=True)
        return
    if previous_path is not None and previous_path != relative_path:
        _, previous_target = await asyncio.to_thread(
            _resolve_storage_path,
            storage_root,
            previous_path,
        )
        if root in previous_target.parents:
            await asyncio.to_thread(previous_target.unlink, missing_ok=True)
