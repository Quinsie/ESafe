from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai_control import CostLimitReached, check_cost_headroom
from app.upstage import (
    EMBEDDING_DIMENSION,
    embedding_cost,
    embedding_request_hash,
    pack_embedding_vectors,
    parse_embedding_response,
    unpack_embedding_vectors,
)


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
