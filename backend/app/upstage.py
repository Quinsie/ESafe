from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.ai_control import AiCostGate, CostReservation
from app.config import Settings

EMBEDDING_DIMENSION = 1024
MAX_EMBEDDING_BATCH_ITEMS = 100
MAX_EMBEDDING_BATCH_TOKENS = 204_800
EMBEDDING_USD_PER_MILLION_WITH_VAT = Decimal("0.022")
EMBEDDING_MAX_BATCH_COST_USD = (
    Decimal(MAX_EMBEDDING_BATCH_TOKENS)
    / Decimal(1_000_000)
    * EMBEDDING_USD_PER_MILLION_WITH_VAT
)


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    embedding_tokens: int
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
    return (
        Decimal(tokens)
        / Decimal(1_000_000)
        * EMBEDDING_USD_PER_MILLION_WITH_VAT
    ).quantize(Decimal("0.00000001"))


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
        if not privacy_verified:
            raise ValueError("UPSTAGE_PRIVACY_NOT_VERIFIED")
        if not texts or len(texts) > MAX_EMBEDDING_BATCH_ITEMS:
            raise ValueError("UPSTAGE_EMBEDDING_BATCH_SIZE_INVALID")
        if any(not text.strip() for text in texts):
            raise ValueError("UPSTAGE_EMBEDDING_EMPTY_INPUT")
        api_key = self._settings.upstage_api_key
        if api_key is None:
            raise ValueError("UPSTAGE_API_KEY_REQUIRED")
        model = self._settings.upstage_embed_passage_model
        request_sha256 = embedding_request_hash(model, texts)
        reservation = await self._cost_gate.reserve(
            profile=self._settings.profile,
            feature_name=feature_name,
            case_reference=None,
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
            await self._cost_gate.settle(
                reservation,
                status="SUCCESS",
                actual_cost_usd=embedding_cost(tokens),
                usage={"embedding_tokens": tokens},
                provider_request_id=(
                    response.headers.get("x-request-id")
                    or response.headers.get("x-upstage-request-id")
                ),
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
