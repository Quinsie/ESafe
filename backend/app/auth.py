import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.security import (
    hash_password,
    new_opaque_token,
    request_fingerprint,
    token_hash,
    verify_password,
)

_DUMMY_PASSWORD_HASH = hash_password(new_opaque_token())
_LOGIN_RATE_SCRIPT = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return value
"""


@dataclass(frozen=True)
class UserCredential:
    user_id: UUID
    username: str
    display_name: str
    password_hash: str


@dataclass(frozen=True)
class AuthenticatedSession:
    session_id_hash: str
    user_id: UUID
    username: str
    display_name: str
    csrf_token_hash: str
    expires_at: datetime


@dataclass(frozen=True)
class NewSession:
    session_token: str
    csrf_token: str
    expires_at: datetime


def auth_fingerprints(
    settings: Settings, username: str, client_ip: str, user_agent: str
) -> tuple[str, str, str]:
    normalized_username = username.strip().casefold()
    return (
        request_fingerprint(settings.session_secret, normalized_username),
        request_fingerprint(settings.session_secret, client_ip),
        request_fingerprint(settings.session_secret, user_agent[:512]),
    )


def login_rate_key(settings: Settings, username: str, client_ip: str) -> str:
    username_fp, client_fp, _ = auth_fingerprints(settings, username, client_ip, "")
    combined = request_fingerprint(settings.session_secret, f"{client_fp}:{username_fp}")
    return f"auth:login:{settings.profile.lower()}:{combined}"


async def is_login_rate_limited(redis_client: Redis, key: str, limit: int) -> bool:
    value = await redis_client.get(key)
    return value is not None and int(value) >= limit


async def register_login_failure(redis_client: Redis, key: str, window_seconds: int) -> int:
    result = await redis_client.eval(_LOGIN_RATE_SCRIPT, 1, key, window_seconds)
    return int(result)


async def clear_login_failures(redis_client: Redis, key: str) -> None:
    await redis_client.delete(key)


async def authenticate_credentials(
    engine: AsyncEngine, username: str, password: str
) -> UserCredential | None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT user_id, username, display_name, password_hash
                FROM app_user
                WHERE username = :username AND is_active
                """
            ),
            {"username": username.strip()},
        )
        row = result.mappings().one_or_none()

    password_hash = str(row["password_hash"]) if row is not None else _DUMMY_PASSWORD_HASH
    password_matches = await asyncio.to_thread(verify_password, password_hash, password)
    if row is None or not password_matches:
        return None
    return UserCredential(
        user_id=row["user_id"],
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        password_hash=password_hash,
    )


async def create_session_with_audit(
    engine: AsyncEngine,
    settings: Settings,
    user: UserCredential,
    request_id: UUID,
    username_fingerprint: str,
    client_fingerprint: str,
    user_agent_fingerprint: str,
) -> NewSession:
    session_token = new_opaque_token()
    csrf_token = new_opaque_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_absolute_seconds)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO user_session (
                    session_id_hash, user_id, csrf_token_hash, profile,
                    client_fingerprint, user_agent_fingerprint, expires_at
                )
                VALUES (
                    :session_id_hash, :user_id, :csrf_token_hash, :profile,
                    :client_fingerprint, :user_agent_fingerprint, :expires_at
                )
                """
            ),
            {
                "session_id_hash": token_hash(session_token),
                "user_id": user.user_id,
                "csrf_token_hash": token_hash(csrf_token),
                "profile": settings.profile,
                "client_fingerprint": client_fingerprint,
                "user_agent_fingerprint": user_agent_fingerprint,
                "expires_at": expires_at,
            },
        )
        await _insert_audit(
            connection,
            "LOGIN_SUCCESS",
            request_id,
            username_fingerprint,
            client_fingerprint,
            user.user_id,
        )
    return NewSession(session_token=session_token, csrf_token=csrf_token, expires_at=expires_at)


async def load_session(
    engine: AsyncEngine,
    settings: Settings,
    raw_session_token: str,
    request_id: UUID,
    client_fingerprint: str,
) -> AuthenticatedSession | None:
    session_id_hash = token_hash(raw_session_token)
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                """
                SELECT s.session_id_hash, s.user_id, u.username, u.display_name,
                       s.csrf_token_hash, s.expires_at, s.last_seen_at
                FROM user_session s
                JOIN app_user u ON u.user_id = s.user_id
                WHERE s.session_id_hash = :session_id_hash
                  AND s.profile = :profile
                  AND s.revoked_at IS NULL
                  AND s.expires_at > CURRENT_TIMESTAMP
                  AND s.last_seen_at > CURRENT_TIMESTAMP - make_interval(secs => :idle_seconds)
                  AND u.is_active
                """
            ),
            {
                "session_id_hash": session_id_hash,
                "profile": settings.profile,
                "idle_seconds": settings.session_idle_seconds,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            expired = await connection.execute(
                text(
                    """
                    UPDATE user_session
                    SET revoked_at = CURRENT_TIMESTAMP, revoke_reason = 'EXPIRED'
                    WHERE session_id_hash = :session_id_hash
                      AND profile = :profile
                      AND revoked_at IS NULL
                      AND (
                        expires_at <= CURRENT_TIMESTAMP OR
                        last_seen_at <= CURRENT_TIMESTAMP - make_interval(secs => :idle_seconds)
                      )
                    RETURNING user_id
                    """
                ),
                {
                    "session_id_hash": session_id_hash,
                    "profile": settings.profile,
                    "idle_seconds": settings.session_idle_seconds,
                },
            )
            expired_user_id = expired.scalar_one_or_none()
            if expired_user_id is not None:
                await _insert_audit(
                    connection,
                    "SESSION_EXPIRED",
                    request_id,
                    request_fingerprint(settings.session_secret, "expired-session"),
                    client_fingerprint,
                    expired_user_id,
                )
            return None

        last_seen_at: datetime = row["last_seen_at"]
        if datetime.now(UTC) - last_seen_at >= timedelta(minutes=5):
            await connection.execute(
                text(
                    """
                    UPDATE user_session
                    SET last_seen_at = CURRENT_TIMESTAMP
                    WHERE session_id_hash = :session_id_hash
                    """
                ),
                {"session_id_hash": session_id_hash},
            )
        return AuthenticatedSession(
            session_id_hash=str(row["session_id_hash"]),
            user_id=row["user_id"],
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            csrf_token_hash=str(row["csrf_token_hash"]),
            expires_at=row["expires_at"],
        )


async def record_auth_event(
    engine: AsyncEngine,
    event_type: str,
    request_id: UUID,
    username_fingerprint: str,
    client_fingerprint: str,
    user_id: UUID | None = None,
) -> None:
    async with engine.begin() as connection:
        await _insert_audit(
            connection,
            event_type,
            request_id,
            username_fingerprint,
            client_fingerprint,
            user_id,
        )


async def revoke_session(
    engine: AsyncEngine,
    session: AuthenticatedSession,
    request_id: UUID,
    username_fingerprint: str,
    client_fingerprint: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE user_session
                SET revoked_at = CURRENT_TIMESTAMP, revoke_reason = 'LOGOUT'
                WHERE session_id_hash = :session_id_hash AND revoked_at IS NULL
                """
            ),
            {"session_id_hash": session.session_id_hash},
        )
        await _insert_audit(
            connection,
            "LOGOUT",
            request_id,
            username_fingerprint,
            client_fingerprint,
            session.user_id,
        )


async def _insert_audit(
    connection: Any,
    event_type: str,
    request_id: UUID,
    username_fingerprint: str,
    client_fingerprint: str,
    user_id: UUID | None,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO auth_audit (
                audit_id, event_type, user_id, username_fingerprint,
                client_fingerprint, request_id, metadata
            )
            VALUES (
                :audit_id, :event_type, :user_id, :username_fingerprint,
                :client_fingerprint, :request_id, '{}'::jsonb
            )
            """
        ),
        {
            "audit_id": uuid4(),
            "event_type": event_type,
            "user_id": user_id,
            "username_fingerprint": username_fingerprint,
            "client_fingerprint": client_fingerprint,
            "request_id": request_id,
        },
    )