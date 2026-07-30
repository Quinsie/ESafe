from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.demo.playback import _pause_failed_step
from app.signals.contracts import SignalSource
from app.signals.ingestion import run_demo_fixture_step


class _Rows:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def mappings(self) -> "_Rows":
        return self

    def one(self) -> dict[str, Any]:
        return self.row


@pytest.mark.asyncio
async def test_failed_step_returns_playback_to_previous_ordinal() -> None:
    playback_id = uuid4()
    captured: dict[str, Any] = {}
    row = {
        "demo_playback_id": playback_id,
        "status": "PAUSED",
        "current_step": 1,
        "version": 9,
    }

    class Connection:
        async def execute(self, statement: Any, parameters: dict[str, Any]) -> _Rows:
            captured["sql"] = str(statement)
            captured["parameters"] = parameters
            return _Rows(row)

    failed = await _pause_failed_step(
        Connection(),  # type: ignore[arg-type]
        playback_id=playback_id,
        previous_step=1,
        now=datetime.now(UTC),
    )

    assert failed == row
    assert captured["parameters"]["previous_step"] == 1
    assert captured["parameters"]["id"] == playback_id
    assert "current_step = :previous_step" in captured["sql"]
    assert "version = version + 1" in captured["sql"]


@pytest.mark.asyncio
async def test_failed_demo_fixture_discards_incomplete_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poll_id = uuid4()
    captured: dict[str, Any] = {}

    class Connection:
        async def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
            captured["sql"] = str(statement)
            captured["parameters"] = parameters

    class Transaction:
        async def __aenter__(self) -> Connection:
            return Connection()

        async def __aexit__(self, *_: object) -> None:
            return None

    class Engine:
        def begin(self) -> Transaction:
            return Transaction()

    monkeypatch.setattr(
        "app.signals.ingestion._begin_poll",
        AsyncMock(return_value=(poll_id, frozenset())),
    )
    monkeypatch.setattr("app.signals.ingestion.load_named_fixture_batch", lambda *_: object())
    monkeypatch.setattr(
        "app.signals.ingestion._store_success",
        AsyncMock(side_effect=RuntimeError("failed")),
    )

    with pytest.raises(RuntimeError, match="failed"):
        await run_demo_fixture_step(
            Engine(),  # type: ignore[arg-type]
            Settings(
                ESAFE_PROFILE="DEMO",
                ESAFE_SESSION_SECRET="x" * 32,
            ),
            source=SignalSource.NFDS,
            fixture_name="ds01_nfds_updated.json",
            scenario_id=UUID("89ec1b9e-6dc2-5f49-95bf-971098c85101"),
            generation=2,
            step_ordinal=2,
            source_time=datetime.now(UTC),
        )

    assert captured["parameters"] == {"poll_id": poll_id}
    assert "DELETE FROM source_poll" in captured["sql"]
    assert "result = 'RUNNING'" in captured["sql"]
