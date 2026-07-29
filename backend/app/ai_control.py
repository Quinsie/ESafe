from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings

CONTROL_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CostControlError(RuntimeError):
    pass


class CostLimitReached(CostControlError):
    pass


class DuplicateCostRequest(CostControlError):
    pass


@dataclass(frozen=True, slots=True)
class CostReservation:
    reservation_id: UUID
    reserved_cost_usd: Decimal


def check_cost_headroom(current: Decimal, requested: Decimal, hard_stop: Decimal) -> None:
    if requested <= 0:
        raise ValueError("reserved cost must be positive")
    if hard_stop <= 0:
        raise ValueError("hard stop must be positive")
    if current < 0:
        raise ValueError("current cost cannot be negative")
    if current + requested > hard_stop:
        raise CostLimitReached("AI_COST_HARD_STOP")


async def initialize_ai_control(settings: Settings) -> None:
    database_url = settings.ai_control_database_url
    if database_url is None:
        raise CostControlError("AI_CONTROL_DATABASE_URL_REQUIRED")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ai_control_schema (
                        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                        version integer NOT NULL CHECK (version > 0),
                        updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ai_control_schema (singleton, version)
                    VALUES (true, :version)
                    ON CONFLICT (singleton) DO NOTHING
                    """
                ),
                {"version": CONTROL_SCHEMA_VERSION},
            )
            version_result = await connection.execute(
                text("SELECT version FROM ai_control_schema WHERE singleton")
            )
            if version_result.scalar_one() != CONTROL_SCHEMA_VERSION:
                raise CostControlError("AI_CONTROL_SCHEMA_VERSION_MISMATCH")
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ai_cost_entry (
                        reservation_id uuid PRIMARY KEY,
                        profile varchar(8) NOT NULL,
                        feature_name varchar(80) NOT NULL,
                        case_reference uuid,
                        model varchar(80) NOT NULL,
                        request_kind varchar(24) NOT NULL,
                        request_sha256 char(64) NOT NULL,
                        status varchar(12) NOT NULL,
                        reserved_cost_usd numeric(14, 8) NOT NULL,
                        actual_cost_usd numeric(14, 8),
                        input_tokens integer,
                        cached_input_tokens integer,
                        output_tokens integer,
                        embedding_tokens integer,
                        document_pages integer,
                        unit_price_snapshot jsonb NOT NULL,
                        provider_request_id varchar(200),
                        retry_of uuid REFERENCES ai_cost_entry(reservation_id) ON DELETE RESTRICT,
                        error_type varchar(80),
                        created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        settled_at timestamptz,
                        CONSTRAINT ck_ai_cost_profile CHECK (profile IN ('LIVE', 'DEMO')),
                        CONSTRAINT ck_ai_cost_kind CHECK (
                            request_kind IN ('CHAT', 'EMBEDDING', 'DOCUMENT_PARSE')
                        ),
                        CONSTRAINT ck_ai_cost_hash CHECK (
                            request_sha256 ~ '^[0-9a-f]{64}$'
                        ),
                        CONSTRAINT ck_ai_cost_status CHECK (
                            status IN ('RESERVED', 'SUCCESS', 'FAILED', 'CANCELLED')
                        ),
                        CONSTRAINT ck_ai_cost_reserved CHECK (
                            reserved_cost_usd > 0
                        ),
                        CONSTRAINT ck_ai_cost_actual CHECK (
                            actual_cost_usd IS NULL
                            OR (
                                actual_cost_usd >= 0
                                AND actual_cost_usd <= reserved_cost_usd
                            )
                        ),
                        CONSTRAINT ck_ai_cost_usage CHECK (
                            coalesce(input_tokens, 0) >= 0
                            AND coalesce(cached_input_tokens, 0) >= 0
                            AND coalesce(output_tokens, 0) >= 0
                            AND coalesce(embedding_tokens, 0) >= 0
                            AND coalesce(document_pages, 0) >= 0
                        ),
                        CONSTRAINT ck_ai_cost_settlement CHECK (
                            (
                                status = 'RESERVED'
                                AND actual_cost_usd IS NULL
                                AND settled_at IS NULL
                                AND error_type IS NULL
                            )
                            OR
                            (
                                status = 'SUCCESS'
                                AND actual_cost_usd IS NOT NULL
                                AND settled_at IS NOT NULL
                                AND error_type IS NULL
                            )
                            OR
                            (
                                status IN ('FAILED', 'CANCELLED')
                                AND actual_cost_usd IS NOT NULL
                                AND settled_at IS NOT NULL
                                AND error_type IS NOT NULL
                            )
                        )
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_cost_active_request
                    ON ai_cost_entry (profile, feature_name, model, request_sha256)
                    WHERE status IN ('RESERVED', 'SUCCESS')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_ai_cost_created
                    ON ai_cost_entry (created_at DESC)
                    """
                )
            )
    finally:
        await engine.dispose()


class AiCostGate:
    def __init__(self, settings: Settings) -> None:
        if settings.ai_control_database_url is None:
            raise CostControlError("AI_CONTROL_DATABASE_URL_REQUIRED")
        self._hard_stop = settings.upstage_cost_hard_stop_usd
        self._engine: AsyncEngine = create_async_engine(
            settings.ai_control_database_url,
            pool_pre_ping=True,
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def reserve(
        self,
        *,
        profile: Literal["LIVE", "DEMO"],
        feature_name: str,
        case_reference: UUID | None,
        model: str,
        request_kind: Literal["CHAT", "EMBEDDING", "DOCUMENT_PARSE"],
        request_sha256: str,
        reserved_cost_usd: Decimal,
        unit_price_snapshot: dict[str, Any],
        retry_of: UUID | None = None,
    ) -> CostReservation:
        if not _SHA256.fullmatch(request_sha256):
            raise ValueError("request SHA-256 is invalid")
        reservation_id = uuid4()
        async with self._engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('esafe-ai-cost-global'))")
            )
            duplicate_result = await connection.execute(
                text(
                    """
                    SELECT reservation_id
                    FROM ai_cost_entry
                    WHERE profile = :profile
                      AND feature_name = :feature_name
                      AND model = :model
                      AND request_sha256 = :request_sha256
                      AND status IN ('RESERVED', 'SUCCESS')
                    LIMIT 1
                    """
                ),
                {
                    "profile": profile,
                    "feature_name": feature_name,
                    "model": model,
                    "request_sha256": request_sha256,
                },
            )
            if duplicate_result.scalar_one_or_none() is not None:
                raise DuplicateCostRequest("AI_DUPLICATE_REQUEST")
            total_result = await connection.execute(
                text(
                    """
                    SELECT coalesce(sum(
                        CASE
                            WHEN status = 'RESERVED' THEN reserved_cost_usd
                            ELSE actual_cost_usd
                        END
                    ), 0)
                    FROM ai_cost_entry
                    WHERE status IN ('RESERVED', 'SUCCESS', 'FAILED')
                    """
                )
            )
            current = Decimal(str(total_result.scalar_one()))
            check_cost_headroom(current, reserved_cost_usd, self._hard_stop)
            await connection.execute(
                text(
                    """
                    INSERT INTO ai_cost_entry (
                        reservation_id, profile, feature_name, case_reference,
                        model, request_kind, request_sha256, status,
                        reserved_cost_usd, unit_price_snapshot, retry_of
                    )
                    VALUES (
                        :reservation_id, :profile, :feature_name, :case_reference,
                        :model, :request_kind, :request_sha256, 'RESERVED',
                        :reserved_cost_usd, CAST(:unit_price_snapshot AS jsonb), :retry_of
                    )
                    """
                ),
                {
                    "reservation_id": reservation_id,
                    "profile": profile,
                    "feature_name": feature_name,
                    "case_reference": case_reference,
                    "model": model,
                    "request_kind": request_kind,
                    "request_sha256": request_sha256,
                    "reserved_cost_usd": reserved_cost_usd,
                    "unit_price_snapshot": json.dumps(
                        unit_price_snapshot,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "retry_of": retry_of,
                },
            )
        return CostReservation(
            reservation_id=reservation_id,
            reserved_cost_usd=reserved_cost_usd,
        )

    async def settle(
        self,
        reservation: CostReservation,
        *,
        status: Literal["SUCCESS", "FAILED", "CANCELLED"],
        actual_cost_usd: Decimal,
        usage: dict[str, int],
        provider_request_id: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if actual_cost_usd < 0 or actual_cost_usd > reservation.reserved_cost_usd:
            raise ValueError("actual cost is outside the reservation")
        if status == "SUCCESS" and error_type is not None:
            raise ValueError("successful settlement cannot have an error")
        if status != "SUCCESS" and not error_type:
            raise ValueError("failed or cancelled settlement requires an error type")
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE ai_cost_entry
                    SET status = :status,
                        actual_cost_usd = :actual_cost_usd,
                        input_tokens = :input_tokens,
                        cached_input_tokens = :cached_input_tokens,
                        output_tokens = :output_tokens,
                        embedding_tokens = :embedding_tokens,
                        document_pages = :document_pages,
                        provider_request_id = :provider_request_id,
                        error_type = :error_type,
                        settled_at = CURRENT_TIMESTAMP
                    WHERE reservation_id = :reservation_id
                      AND status = 'RESERVED'
                    """
                ),
                {
                    "reservation_id": reservation.reservation_id,
                    "status": status,
                    "actual_cost_usd": actual_cost_usd,
                    "input_tokens": usage.get("input_tokens"),
                    "cached_input_tokens": usage.get("cached_input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "embedding_tokens": usage.get("embedding_tokens"),
                    "document_pages": usage.get("document_pages"),
                    "provider_request_id": provider_request_id,
                    "error_type": error_type,
                },
            )
            if result.rowcount != 1:
                raise CostControlError("AI_COST_RESERVATION_NOT_OPEN")
