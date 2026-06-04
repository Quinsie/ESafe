# -*- coding: utf-8 -*-
"""Ollama 로컬 LLM 호출 래퍼."""
import os
import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.environ.get("ESAFE_LLM_MODEL", "qwen2.5:7b")


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.2,
         timeout: float = 180.0) -> str:
    """Ollama /api/chat 호출. 근거 기반 설명이므로 temperature를 낮게 둔다."""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def is_available() -> bool:
    try:
        httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3.0).raise_for_status()
        return True
    except Exception:
        return False
