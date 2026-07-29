from __future__ import annotations

import hashlib
import json
import math
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from app.ai_control import AiCostGate, CostReservation
from app.config import Settings

EMBEDDING_DIMENSION = 1024
MAX_EMBEDDING_BATCH_ITEMS = 100
MAX_EMBEDDING_BATCH_TOKENS = 204_800
EMBEDDING_USD_PER_MILLION_WITH_VAT = Decimal("0.022")
EMBEDDING_MAX_BATCH_COST_USD = (
    Decimal(MAX_EMBEDDING_BATCH_TOKENS) / Decimal(1_000_000) * EMBEDDING_USD_PER_MILLION_WITH_VAT
)
CHAT_MAX_INPUT_TOKENS = 120_000
CHAT_MAX_OUTPUT_TOKENS = 3_072
CHAT_INPUT_USD_PER_MILLION_WITH_VAT = Decimal("0.165")
CHAT_CACHED_INPUT_USD_PER_MILLION_WITH_VAT = Decimal("0.0165")
CHAT_OUTPUT_USD_PER_MILLION_WITH_VAT = Decimal("0.66")
CHAT_MAX_REQUEST_COST_USD = (
    Decimal(CHAT_MAX_INPUT_TOKENS) / Decimal(1_000_000) * CHAT_INPUT_USD_PER_MILLION_WITH_VAT
    + Decimal(CHAT_MAX_OUTPUT_TOKENS) / Decimal(1_000_000) * CHAT_OUTPUT_USD_PER_MILLION_WITH_VAT
).quantize(Decimal("0.00000001"))


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    embedding_tokens: int
    reservation_id: str
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class ChatResult:
    payload: dict[str, Any]
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reservation_id: str


def embedding_request_hash(model: str, texts: Sequence[str]) -> str:
    payload = json.dumps(
        {"model": model, "input": list(texts)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def embedding_cost(tokens: int) -> Decimal:
    if tokens < 0:
        raise ValueError("embedding tokens cannot be negative")
    return (Decimal(tokens) / Decimal(1_000_000) * EMBEDDING_USD_PER_MILLION_WITH_VAT).quantize(
        Decimal("0.00000001")
    )


def chat_response_format(
    response_schema: dict[str, Any] | None,
    *,
    schema_name: str = "response",
) -> dict[str, Any]:
    if response_schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": response_schema,
        },
    }


def chat_request_hash(
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any] | None = None,
) -> str:
    resolved_response_format = response_format or {"type": "json_object"}
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": CHAT_MAX_OUTPUT_TOKENS,
            "response_format": resolved_response_format,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chat_cost(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> Decimal:
    if (
        input_tokens < 0
        or cached_input_tokens < 0
        or output_tokens < 0
        or cached_input_tokens > input_tokens
    ):
        raise ValueError("chat usage cannot be negative or inconsistent")
    uncached_input_tokens = input_tokens - cached_input_tokens
    return (
        Decimal(uncached_input_tokens) / Decimal(1_000_000) * CHAT_INPUT_USD_PER_MILLION_WITH_VAT
        + Decimal(cached_input_tokens)
        / Decimal(1_000_000)
        * CHAT_CACHED_INPUT_USD_PER_MILLION_WITH_VAT
        + Decimal(output_tokens) / Decimal(1_000_000) * CHAT_OUTPUT_USD_PER_MILLION_WITH_VAT
    ).quantize(Decimal("0.00000001"))


def pack_embedding_vectors(vectors: list[list[float]]) -> bytes:
    flattened = array("f", (value for vector in vectors for value in vector))
    if sys.byteorder != "little":
        flattened.byteswap()
    return flattened.tobytes()


def unpack_embedding_vectors(
    payload: bytes,
    *,
    item_count: int,
    dimension: int,
) -> list[list[float]]:
    if (
        dimension != EMBEDDING_DIMENSION
        or not 1 <= item_count <= MAX_EMBEDDING_BATCH_ITEMS
        or len(payload) != item_count * dimension * 4
    ):
        raise ValueError("UPSTAGE_EMBEDDING_CACHE_INVALID")
    values = array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if not all(math.isfinite(value) for value in values):
        raise ValueError("UPSTAGE_EMBEDDING_CACHE_INVALID")
    return [
        list(values[offset : offset + dimension]) for offset in range(0, len(values), dimension)
    ]


def parse_embedding_response(
    payload: dict[str, Any],
    expected_items: int,
) -> tuple[list[list[float]], int]:
    data = payload.get("data")
    usage = payload.get("usage")
    if not isinstance(data, list) or len(data) != expected_items or not isinstance(usage, dict):
        raise ValueError("UPSTAGE_EMBEDDING_RESPONSE_INVALID")
    indexed: list[tuple[int, list[float]]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("UPSTAGE_EMBEDDING_ITEM_INVALID")
        index = item.get("index")
        vector = item.get("embedding")
        if (
            not isinstance(index, int)
            or not isinstance(vector, list)
            or len(vector) != EMBEDDING_DIMENSION
            or not all(
                not isinstance(value, bool)
                and isinstance(value, int | float)
                and math.isfinite(value)
                for value in vector
            )
        ):
            raise ValueError("UPSTAGE_EMBEDDING_VECTOR_INVALID")
        indexed.append((index, [float(value) for value in vector]))
    indexed.sort(key=lambda item: item[0])
    if [item[0] for item in indexed] != list(range(expected_items)):
        raise ValueError("UPSTAGE_EMBEDDING_INDEX_INVALID")
    tokens = usage.get("total_tokens", usage.get("prompt_tokens"))
    if not isinstance(tokens, int) or not 0 < tokens <= MAX_EMBEDDING_BATCH_TOKENS:
        raise ValueError("UPSTAGE_EMBEDDING_USAGE_INVALID")
    return [item[1] for item in indexed], tokens


def parse_chat_response(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], int, int, int]:
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(usage, dict):
        raise ValueError("UPSTAGE_CHAT_RESPONSE_INVALID")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("UPSTAGE_CHAT_RESPONSE_INVALID")
    finish_reason = choice.get("finish_reason")
    if finish_reason != "stop":
        raise ValueError(f"UPSTAGE_CHAT_FINISH_INVALID:{finish_reason}")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("UPSTAGE_CHAT_MESSAGE_INVALID")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
        raise ValueError("UPSTAGE_CHAT_CONTENT_INVALID")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("UPSTAGE_CHAT_JSON_INVALID") from error
    if not isinstance(parsed, dict):
        raise ValueError("UPSTAGE_CHAT_JSON_INVALID")
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    prompt_details = usage.get("prompt_tokens_details") or {}
    cached_input_tokens = (
        prompt_details.get("cached_tokens", 0) if isinstance(prompt_details, dict) else 0
    )
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not 0 < input_tokens <= CHAT_MAX_INPUT_TOKENS
        or not isinstance(cached_input_tokens, int)
        or isinstance(cached_input_tokens, bool)
        or not 0 <= cached_input_tokens <= input_tokens
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or not 0 < output_tokens <= CHAT_MAX_OUTPUT_TOKENS
    ):
        raise ValueError("UPSTAGE_CHAT_USAGE_INVALID")
    return parsed, input_tokens, cached_input_tokens, output_tokens


class UpstageEmbeddingClient:
    def __init__(self, settings: Settings, cost_gate: AiCostGate) -> None:
        self._settings = settings
        self._cost_gate = cost_gate

    async def embed_passages(
        self,
        texts: Sequence[str],
        *,
        feature_name: str,
        privacy_verified: bool,
    ) -> EmbeddingResult:
        return await self._embed(
            texts,
            model=self._settings.upstage_embed_passage_model,
            feature_name=feature_name,
            privacy_verified=privacy_verified,
            case_reference=None,
        )

    async def embed_query(
        self,
        text: str,
        *,
        feature_name: str,
        privacy_verified: bool,
        case_reference: UUID | None = None,
    ) -> EmbeddingResult:
        return await self._embed(
            [text],
            model=self._settings.upstage_embed_query_model,
            feature_name=feature_name,
            privacy_verified=privacy_verified,
            case_reference=case_reference,
        )

    async def _embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        feature_name: str,
        privacy_verified: bool,
        case_reference: UUID | None,
    ) -> EmbeddingResult:
        if not privacy_verified:
            raise ValueError("UPSTAGE_PRIVACY_NOT_VERIFIED")
        if not texts or len(texts) > MAX_EMBEDDING_BATCH_ITEMS:
            raise ValueError("UPSTAGE_EMBEDDING_BATCH_SIZE_INVALID")
        if any(not text.strip() for text in texts):
            raise ValueError("UPSTAGE_EMBEDDING_EMPTY_INPUT")
        request_sha256 = embedding_request_hash(model, texts)
        cached = await self._cost_gate.get_embedding_cache(
            model=model,
            request_sha256=request_sha256,
        )
        if cached is not None:
            return EmbeddingResult(
                vectors=unpack_embedding_vectors(
                    cached.vector_payload,
                    item_count=cached.item_count,
                    dimension=cached.dimension,
                ),
                embedding_tokens=cached.embedding_tokens,
                reservation_id=str(cached.source_reservation_id),
                cache_hit=True,
            )
        api_key = self._settings.upstage_api_key
        if api_key is None:
            raise ValueError("UPSTAGE_API_KEY_REQUIRED")
        reservation = await self._cost_gate.reserve(
            profile=self._settings.profile,
            feature_name=feature_name,
            case_reference=case_reference,
            model=model,
            request_kind="EMBEDDING",
            request_sha256=request_sha256,
            reserved_cost_usd=EMBEDDING_MAX_BATCH_COST_USD,
            unit_price_snapshot={
                "currency": "USD",
                "embedding_per_million": str(EMBEDDING_USD_PER_MILLION_WITH_VAT),
                "vat_included": True,
                "price_version": "2026-07-28",
            },
        )
        settled = False
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.upstage_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0),
            ) as client:
                response = await client.post(
                    "/embeddings",
                    json={"model": model, "input": list(texts)},
                )
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("UPSTAGE_EMBEDDING_RESPONSE_INVALID")
            vectors, tokens = parse_embedding_response(payload, len(texts))
            await self._cost_gate.settle_embedding_success(
                reservation,
                actual_cost_usd=embedding_cost(tokens),
                embedding_tokens=tokens,
                provider_request_id=(
                    response.headers.get("x-request-id")
                    or response.headers.get("x-upstage-request-id")
                ),
                model=model,
                request_sha256=request_sha256,
                dimension=EMBEDDING_DIMENSION,
                item_count=len(texts),
                vector_payload=pack_embedding_vectors(vectors),
            )
            settled = True
            return EmbeddingResult(
                vectors=vectors,
                embedding_tokens=tokens,
                reservation_id=str(reservation.reservation_id),
            )
        except Exception as error:
            if not settled:
                await self._settle_failure(reservation, type(error).__name__)
            raise

    async def _settle_failure(
        self,
        reservation: CostReservation,
        error_type: str,
    ) -> None:
        await self._cost_gate.settle(
            reservation,
            status="FAILED",
            actual_cost_usd=reservation.reserved_cost_usd,
            usage={},
            error_type=error_type[:80],
        )


class UpstageChatClient:
    def __init__(self, settings: Settings, cost_gate: AiCostGate) -> None:
        self._settings = settings
        self._cost_gate = cost_gate

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        feature_name: str,
        privacy_verified: bool,
        case_reference: UUID | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
    ) -> ChatResult:
        if not privacy_verified:
            raise ValueError("UPSTAGE_PRIVACY_NOT_VERIFIED")
        if not system_prompt.strip() or not user_prompt.strip():
            raise ValueError("UPSTAGE_CHAT_EMPTY_INPUT")
        if len(system_prompt) + len(user_prompt) > 360_000:
            raise ValueError("UPSTAGE_CHAT_INPUT_TOO_LARGE")
        model = self._settings.upstage_chat_model
        response_format = chat_response_format(
            response_schema,
            schema_name=schema_name,
        )
        request_sha256 = chat_request_hash(
            model,
            system_prompt,
            user_prompt,
            response_format,
        )
        api_key = self._settings.upstage_api_key
        if api_key is None:
            raise ValueError("UPSTAGE_API_KEY_REQUIRED")
        reservation = await self._cost_gate.reserve(
            profile=self._settings.profile,
            feature_name=feature_name,
            case_reference=case_reference,
            model=model,
            request_kind="CHAT",
            request_sha256=request_sha256,
            reserved_cost_usd=CHAT_MAX_REQUEST_COST_USD,
            unit_price_snapshot={
                "currency": "USD",
                "input_per_million": str(CHAT_INPUT_USD_PER_MILLION_WITH_VAT),
                "cached_input_per_million": str(CHAT_CACHED_INPUT_USD_PER_MILLION_WITH_VAT),
                "output_per_million": str(CHAT_OUTPUT_USD_PER_MILLION_WITH_VAT),
                "vat_included": True,
                "price_version": "2026-07-29",
                "source": "https://www.upstage.ai/pricing/api",
            },
        )
        settled = False
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.upstage_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self._settings.upstage_chat_timeout_seconds),
            ) as client:
                response = await client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0,
                        "max_tokens": CHAT_MAX_OUTPUT_TOKENS,
                        "response_format": response_format,
                    },
                )
                response.raise_for_status()
                response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError("UPSTAGE_CHAT_RESPONSE_INVALID")
            parsed, input_tokens, cached_input_tokens, output_tokens = parse_chat_response(
                response_payload
            )
            await self._cost_gate.settle(
                reservation,
                status="SUCCESS",
                actual_cost_usd=chat_cost(
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                ),
                usage={
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                },
                provider_request_id=(
                    response.headers.get("x-request-id")
                    or response.headers.get("x-upstage-request-id")
                ),
            )
            settled = True
            return ChatResult(
                payload=parsed,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                reservation_id=str(reservation.reservation_id),
            )
        except Exception as error:
            if not settled:
                await self._cost_gate.settle(
                    reservation,
                    status="FAILED",
                    actual_cost_usd=reservation.reserved_cost_usd,
                    usage={},
                    error_type=type(error).__name__[:80],
                )
            raise
