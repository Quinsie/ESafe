# -*- coding: utf-8 -*-
"""
유사 사고 사례 검색기 (기능 2, RAG).

코퍼스가 작아 벡터DB(Chroma/FAISS) 없이 numpy 코사인 유사도로 처리한다.
개념(임베딩 → 유사도 검색)은 벡터DB와 동일하며, 사례가 많아지면 그대로 FAISS로 교체 가능.

★ 실제 사례 데이터 연결: cases_seed.json을 KESCO/국가화재정보시스템 사례로 교체하면 끝. ★
"""
import json
import math
import os

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.environ.get("ESAFE_EMBED_MODEL", "bge-m3")
CASES_PATH = os.path.join(os.path.dirname(__file__), "cases_seed.json")

# 임베딩 인덱스 메모리 캐시 (최초 1회 계산)
_index = {"cases": None, "vectors": None}


def embed(text: str) -> list:
    """Ollama 임베딩 1건."""
    resp = httpx.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_cases() -> list:
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)["cases"]


def _ensure_index():
    """최초 호출 시 모든 사례 텍스트를 임베딩해 캐시한다."""
    if _index["vectors"] is not None:
        return
    cases = _load_cases()
    vectors = [embed(c["text"]) for c in cases]
    _index["cases"] = cases
    _index["vectors"] = vectors


def search(query_text: str, top_k: int = 3) -> list:
    """질의 텍스트와 유사한 사례 top_k를 (case, score)로 반환."""
    _ensure_index()
    qv = embed(query_text)
    scored = [
        (case, _cosine(qv, vec))
        for case, vec in zip(_index["cases"], _index["vectors"])
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def case_count() -> int:
    return len(_load_cases())
