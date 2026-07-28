import asyncio
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def dependency_health(
    engine: AsyncEngine,
    redis_client: Redis,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    async def database_check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def redis_check() -> None:
        await redis_client.ping()

    async def run_check(check: Any) -> dict[str, str]:
        try:
            await asyncio.wait_for(check(), timeout=timeout_seconds)
            return {"status": "UP"}
        except (
            Exception
        ) as exc:  # The public response intentionally hides dependency details.
            return {"status": "DOWN", "reason": type(exc).__name__}

    database, redis = await asyncio.gather(
        run_check(database_check), run_check(redis_check)
    )
    return {"database": database, "redis": redis}


async def reference_dataset_metadata(
    engine: AsyncEngine, timeout_seconds: float
) -> dict[str, Any] | None:
    async def query() -> dict[str, Any] | None:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT s.active_import_id AS "importId",
                           i.source_manifest_sha256 AS "manifestHash",
                           i.source_version AS "sourceVersion",
                           i.building_count AS "buildingCount",
                           i.risk_count AS "riskCount",
                           i.facility_count AS "facilityCount",
                           i.facility_link_count AS "facilityLinkCount",
                           i.quality_summary AS "qualitySummary",
                           s.activated_at AS "activatedAt"
                    FROM reference_dataset_state s
                    JOIN reference_import i ON i.import_id = s.active_import_id
                    WHERE s.state_id = true
                    """
                )
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            metadata = dict(row)
            metadata["activatedAt"] = metadata["activatedAt"].isoformat()
            return metadata

    return await asyncio.wait_for(query(), timeout=timeout_seconds)
