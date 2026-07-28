import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.responses import envelope
from app.auth import (
    AuthenticatedSession,
    auth_fingerprints,
    authenticate_credentials,
    clear_login_failures,
    create_session_with_audit,
    is_login_rate_limited,
    load_session,
    login_rate_key,
    record_auth_event,
    register_login_failure,
    revoke_session,
)
from app.config import Settings
from app.security import tokens_match

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_GENERIC_LOGIN_ERROR = "아이디 또는 비밀번호를 확인해 주세요."


class AuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class LoginBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId", min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    display_name: str = Field(alias="displayName")


def _request_id(request: Request) -> UUID:
    return UUID(request.state.request_id)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def validate_request_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site not in (None, "same-origin", "none"):
        raise AuthError(403, "ORIGIN_NOT_ALLOWED", "허용되지 않은 요청 출처입니다.")
    if origin is not None and origin.rstrip("/") not in settings.public_origins:
        raise AuthError(403, "ORIGIN_NOT_ALLOWED", "허용되지 않은 요청 출처입니다.")


async def require_session(request: Request) -> AuthenticatedSession:
    settings: Settings = request.app.state.settings
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise AuthError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")
    _, client_fingerprint, _ = auth_fingerprints(
        settings,
        "session",
        _client_ip(request),
        request.headers.get("user-agent", ""),
    )
    session = await load_session(
        request.app.state.db_engine,
        settings,
        raw_token,
        _request_id(request),
        client_fingerprint,
    )
    if session is None:
        raise AuthError(401, "SESSION_EXPIRED", "세션이 만료되었습니다.")
    request.state.auth_session = session
    return session


async def require_csrf(
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(require_session)],
) -> AuthenticatedSession:
    validate_request_origin(request)
    settings: Settings = request.app.state.settings
    header_token = request.headers.get("x-csrf-token")
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if (
        not header_token
        or not cookie_token
        or header_token != cookie_token
        or not tokens_match(session.csrf_token_hash, header_token)
    ):
        raise AuthError(403, "CSRF_INVALID", "요청 검증에 실패했습니다.")
    return session


@router.post("/login")
async def login(request: Request, body: LoginBody) -> JSONResponse:
    validate_request_origin(request)
    settings: Settings = request.app.state.settings
    client_ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    username_fp, client_fp, user_agent_fp = auth_fingerprints(
        settings, body.user_id, client_ip, user_agent
    )
    rate_key = login_rate_key(settings, body.user_id, client_ip)
    if await is_login_rate_limited(
        request.app.state.redis, rate_key, settings.login_rate_limit_attempts
    ):
        await record_auth_event(
            request.app.state.db_engine,
            "LOGIN_RATE_LIMITED",
            _request_id(request),
            username_fp,
            client_fp,
        )
        raise AuthError(429, "LOGIN_RATE_LIMITED", "잠시 후 다시 시도해 주세요.")

    user = await authenticate_credentials(
        request.app.state.db_engine, body.user_id, body.password
    )
    if user is None:
        await register_login_failure(
            request.app.state.redis,
            rate_key,
            settings.login_rate_limit_window_seconds,
        )
        await record_auth_event(
            request.app.state.db_engine,
            "LOGIN_FAILURE",
            _request_id(request),
            username_fp,
            client_fp,
        )
        await asyncio.sleep(0.2)
        raise AuthError(401, "INVALID_CREDENTIALS", _GENERIC_LOGIN_ERROR)

    await clear_login_failures(request.app.state.redis, rate_key)
    new_session = await create_session_with_audit(
        request.app.state.db_engine,
        settings,
        user,
        _request_id(request),
        username_fp,
        client_fp,
        user_agent_fp,
    )
    response = JSONResponse(
        content=envelope(
            request,
            {
                "user": LoginUser(
                    userId=user.username,
                    displayName=user.display_name,
                ).model_dump(by_alias=True),
                "expiresAt": new_session.expires_at.isoformat(),
            },
        )
    )
    response.set_cookie(
        settings.session_cookie_name,
        new_session.session_token,
        max_age=settings.session_absolute_seconds,
        path=settings.session_cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        new_session.csrf_token,
        max_age=settings.session_absolute_seconds,
        path=settings.session_cookie_path,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )
    return response


@router.get("/session")
async def session_info(
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(require_session)],
) -> dict[str, object]:
    return envelope(
        request,
        {
            "user": {
                "userId": session.username,
                "displayName": session.display_name,
            },
            "expiresAt": session.expires_at.isoformat(),
        },
    )


@router.post("/logout")
async def logout(
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(require_csrf)],
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    username_fp, client_fp, _ = auth_fingerprints(
        settings,
        session.username,
        _client_ip(request),
        request.headers.get("user-agent", ""),
    )
    await revoke_session(
        request.app.state.db_engine,
        session,
        _request_id(request),
        username_fp,
        client_fp,
    )
    response = JSONResponse(content=envelope(request, {"loggedOut": True}))
    response.delete_cookie(
        settings.session_cookie_name,
        path=settings.session_cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path=settings.session_cookie_path,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )
    return response