import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.workflow import WorkflowContractError


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def require_demo_profile(profile: str) -> None:
    if profile != "DEMO":
        raise WorkflowContractError(
            403,
            "DEMO_PROFILE_REQUIRED",
            "시나리오 제어는 체험 데이터 환경에서만 사용할 수 있습니다.",
        )


async def scenario_catalog(
    engine: AsyncEngine,
    *,
    profile: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    require_demo_profile(profile)

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT scenario.demo_scenario_id, scenario.code,
                                   scenario.name, scenario.description,
                                   scenario.scenario_version, playback.demo_playback_id,
                                   playback.status, playback.current_step,
                                   playback.generation, playback.version,
                                   playback.updated_at
                            FROM demo_scenario scenario
                            LEFT JOIN demo_playback playback
                              ON playback.demo_scenario_id =
                                 scenario.demo_scenario_id
                             AND playback.status IN (
                                 'READY', 'RUNNING', 'PAUSED'
                             )
                            WHERE scenario.enabled
                            ORDER BY scenario.ordinal
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        return {
            "items": [
                {
                    "scenarioId": str(row["demo_scenario_id"]),
                    "code": row["code"],
                    "name": row["name"],
                    "description": row["description"],
                    "scenarioVersion": int(row["scenario_version"]),
                    "playback": (
                        {
                            "playbackId": str(row["demo_playback_id"]),
                            "status": row["status"],
                            "currentStep": int(row["current_step"]),
                            "generation": int(row["generation"]),
                            "version": int(row["version"]),
                            "updatedAt": _iso(row["updated_at"]),
                        }
                        if row["demo_playback_id"] is not None
                        else None
                    ),
                }
                for row in rows
            ]
        }

    try:
        return await asyncio.wait_for(query(), timeout=timeout_seconds)
    except TimeoutError as error:
        raise WorkflowContractError(
            503,
            "DEMO_SCENARIOS_TIMEOUT",
            "체험 시나리오 목록을 제한 시간 안에 불러오지 못했습니다.",
        ) from error
