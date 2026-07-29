from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.documents import (
    _artifact_relative_path,
    _resolve_storage_path,
    document_library,
)


def test_artifact_path_is_profile_local_and_filename_safe(tmp_path: Path) -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")
    relative = _artifact_relative_path(
        document_draft_id=draft_id,
        version=3,
        stage="REVIEW",
        format_name="HWPX",
        case_number="../../민감 경로",
    )
    resolved = _resolve_storage_path(tmp_path, relative)

    assert ".." not in relative.parts
    assert resolved.is_relative_to(tmp_path.resolve())
    assert resolved.name == f"{draft_id}_v3_review.hwpx"
    assert relative.parts[:3] == (str(draft_id), "v3", "review")


@pytest.mark.parametrize(
    "value",
    (
        Path("/absolute/path"),
        Path("../escape"),
        Path("safe/../../escape"),
    ),
)
def test_storage_path_rejects_escape(tmp_path: Path, value: Path) -> None:
    with pytest.raises(RuntimeError, match="DOCUMENT_STORAGE_PATH"):
        _resolve_storage_path(tmp_path, value)  # type: ignore[arg-type]


class _EmptyMappings:
    def all(self) -> list[object]:
        return []


class _EmptyResult:
    def mappings(self) -> _EmptyMappings:
        return _EmptyMappings()


class _CaptureConnection:
    statement = ""
    parameters: dict[str, object] = {}

    async def __aenter__(self) -> _CaptureConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object],
    ) -> _EmptyResult:
        self.statement = str(statement)
        self.parameters = parameters
        return _EmptyResult()


class _CaptureEngine:
    def __init__(self) -> None:
        self.connection = _CaptureConnection()

    def connect(self) -> _CaptureConnection:
        return self.connection


@pytest.mark.asyncio
async def test_document_library_types_optional_postgres_parameters() -> None:
    engine = _CaptureEngine()

    result = await document_library(
        engine,  # type: ignore[arg-type]
        status=None,
        family=None,
        page=1,
        page_size=20,
        timeout_seconds=1,
    )

    assert result == {
        "items": [],
        "pagination": {
            "page": 1,
            "pageSize": 20,
            "total": 0,
            "totalPages": 0,
        },
    }
    assert "CAST(:status AS varchar)" in engine.connection.statement
    assert "CAST(:family AS varchar)" in engine.connection.statement
    assert engine.connection.parameters == {
        "status": None,
        "family": None,
        "limit": 20,
        "offset": 0,
    }
