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
        except Exception as exc:  # The public response intentionally hides dependency details.
            return {"status": "DOWN", "reason": type(exc).__name__}

    database, redis = await asyncio.gather(run_check(database_check), run_check(redis_check))
    return {"database": database, "redis": redis}
