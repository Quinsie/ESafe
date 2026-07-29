from __future__ import annotations

import sys
from array import array

from app.rag_embeddings import vector_bytes
from app.upstage import EMBEDDING_DIMENSION


def test_vector_bytes_are_little_endian_float32() -> None:
    payload = vector_bytes([[0.25] * EMBEDDING_DIMENSION])
    values = array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()

    assert len(payload) == EMBEDDING_DIMENSION * 4
    assert len(values) == EMBEDDING_DIMENSION
    assert values[0] == 0.25
