import argparse
import asyncio
from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.security import hash_password


async def seed_system_metadata() -> None:
    settings = get_settings()
    if settings.public_user_password is None:
        raise RuntimeError("ESAFE_PUBLIC_USER_PASSWORD is required for seed")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO system_metadata (key, value)
                    VALUES ('bootstrap_profile', :profile)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"profile": settings.profile},
            )
            existing = await connection.execute(
                text("SELECT username FROM app_user ORDER BY created_at LIMIT 1")
            )
            existing_username = existing.scalar_one_or_none()
            if existing_username is None:
                password_hash = await asyncio.to_thread(
                    hash_password,
                    settings.public_user_password.get_secret_value(),
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO app_user (
                            user_id, username, display_name, password_hash, is_active
                        )
                        VALUES (:user_id, :username, '사용자', :password_hash, true)
                        """
                    ),
                    {
                        "user_id": uuid4(),
                        "username": settings.public_user_id,
                        "password_hash": password_hash,
                    },
                )
            elif existing_username != settings.public_user_id:
                raise RuntimeError(
                    "The configured public user ID differs from the initialized account"
                )
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=("seed",))
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "seed":
        asyncio.run(seed_system_metadata())


if __name__ == "__main__":
    main()
