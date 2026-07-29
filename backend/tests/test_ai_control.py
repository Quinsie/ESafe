from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai_control import CostLimitReached, check_cost_headroom
from app.config import Settings
from app.upstage import (
    EMBEDDING_DIMENSION,
    chat_cost,
    chat_request_hash,
    chat_response_format,
    embedding_cost,
    embedding_request_hash,
    pack_embedding_vectors,
    parse_chat_response,
    parse_embedding_response,
    unpack_embedding_vectors,
)


def test_chat_timeout_is_bounded_for_async_generation() -> None:
    assert Settings().upstage_chat_timeout_seconds == 300.0
    assert Settings(UPSTAGE_CHAT_TIMEOUT_SECONDS=30).upstage_chat_timeout_seconds == 30.0
    with pytest.raises(ValidationError):
        Settings(UPSTAGE_CHAT_TIMEOUT_SECONDS=301)


def test_cost_headroom_blocks_before_hard_stop_is_crossed() -> None:
    check_cost_headroom(Decimal("449.99"), Decimal("0.01"), Decimal("450"))

    with pytest.raises(CostLimitReached, match="AI_COST_HARD_STOP"):
        check_cost_headroom(Decimal("449.99"), Decimal("0.01000001"), Decimal("450"))


def test_embedding_cost_includes_configured_vat_snapshot() -> None:
    assert embedding_cost(1_000_000) == Decimal("0.02200000")


def test_embedding_request_hash_is_content_and_order_sensitive() -> None:
    first = embedding_request_hash("model", ["가", "나"])

    assert first == embedding_request_hash("model", ["가", "나"])
    assert first != embedding_request_hash("model", ["나", "가"])
    assert first != embedding_request_hash("other", ["가", "나"])


def test_embedding_response_requires_order_dimension_and_usage() -> None:
    vector = [0.0] * EMBEDDING_DIMENSION
    payload = {
        "data": [
            {"index": 1, "embedding": vector},
            {"index": 0, "embedding": vector},
        ],
        "usage": {"total_tokens": 12},
    }

    vectors, tokens = parse_embedding_response(payload, 2)

    assert len(vectors) == 2
    assert tokens == 12


def test_embedding_response_rejects_wrong_dimension() -> None:
    payload = {
        "data": [{"index": 0, "embedding": [0.0]}],
        "usage": {"total_tokens": 1},
    }

    with pytest.raises(ValueError, match="VECTOR_INVALID"):
        parse_embedding_response(payload, 1)


def test_embedding_cache_payload_round_trip() -> None:
    vectors = [[0.25] * EMBEDDING_DIMENSION, [-0.5] * EMBEDDING_DIMENSION]

    restored = unpack_embedding_vectors(
        pack_embedding_vectors(vectors),
        item_count=2,
        dimension=EMBEDDING_DIMENSION,
    )

    assert restored == vectors


def test_chat_cost_separates_cached_input_and_includes_vat() -> None:
    assert chat_cost(1_000_000, 0, 1_000_000) == Decimal("0.82500000")
    assert chat_cost(1_000_000, 1_000_000, 1_000_000) == Decimal("0.67650000")


def test_chat_request_hash_covers_prompt_and_model() -> None:
    first = chat_request_hash("solar-pro3", "system", "user")

    assert first == chat_request_hash("solar-pro3", "system", "user")
    assert first != chat_request_hash("solar-pro3", "system", "other")
    assert first != chat_request_hash("other", "system", "user")
    assert first != chat_request_hash(
        "solar-pro3",
        "system",
        "user",
        chat_response_format({"type": "object"}, schema_name="result"),
    )


def test_chat_response_format_supports_json_schema() -> None:
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}

    assert chat_response_format(None) == {"type": "json_object"}
    assert chat_response_format(schema, schema_name="result") == {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": schema},
    }


def test_chat_response_requires_json_stop_and_consistent_usage() -> None:
    parsed, input_tokens, cached_tokens, output_tokens = parse_chat_response(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"summary":"확인"}'},
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        }
    )

    assert parsed == {"summary": "확인"}
    assert (input_tokens, cached_tokens, output_tokens) == (100, 40, 20)


@pytest.mark.parametrize(
    "payload,error",
    [
        (
            {
                "choices": [{"finish_reason": "length", "message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            "FINISH_INVALID",
        ),
        (
            {
                "choices": [{"finish_reason": "stop", "message": {"content": "not json"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            "JSON_INVALID",
        ),
        (
            {
                "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "prompt_tokens_details": {"cached_tokens": 2},
                },
            },
            "USAGE_INVALID",
        ),
    ],
)
def test_chat_response_rejects_unsafe_contracts(
    payload: dict[str, object],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        parse_chat_response(payload)
