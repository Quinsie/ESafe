from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.config import Settings


def envelope(
    request: Request, data: Any, *, error: dict[str, str] | None = None
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "data": data,
        "meta": {
            "requestId": request.state.request_id,
            "profile": settings.profile,
            "asOf": datetime.now(UTC).isoformat(),
            "sourceStatus": [],
        },
        "error": error,
    }
