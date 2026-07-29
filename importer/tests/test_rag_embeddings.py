from __future__ import annotations

from array import array

from esafe_importer.rag_embeddings import EXPECTED_DIMENSION, load_vectors


def test_load_vectors_reads_little_endian_float32(tmp_path) -> None:
    path = tmp_path / "vector.f32"
    payload = array("f", [0.5] * EXPECTED_DIMENSION)
    path.write_bytes(payload.tobytes())

    vectors = load_vectors(path, 1)

    assert len(vectors) == 1
    assert len(vectors[0]) == EXPECTED_DIMENSION
    assert vectors[0][0] == 0.5
