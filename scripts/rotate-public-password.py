from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.security import hash_password


async def rotate() -> None:
    password = sys.stdin.read()
    if len(password) < 12 or "\n" in password or "\r" in password:
        raise RuntimeError("PUBLIC_PASSWORD_INPUT_INVALID")

    password_hash = await asyncio.to_thread(hash_password, password)
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(
                text("UPDATE app_user SET password_hash = :password_hash"),
                {"password_hash": password_hash},
            )
            if result.rowcount != 1:
                raise RuntimeError("PUBLIC_USER_COUNT_INVALID")
            await connection.execute(text("DELETE FROM user_session"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(rotate())
