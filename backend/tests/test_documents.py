from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.documents import (
    _artifact_relative_path,
    _resolve_storage_path,
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
