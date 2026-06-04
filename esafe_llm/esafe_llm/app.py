# -*- coding: utf-8 -*-
"""
ESafe LLM 사이드카 (FastAPI).

실행:
    conda activate esafe
    pip install -r esafe_llm/requirements.txt
    uvicorn app:app --app-dir esafe_llm --port 8800 --reload

엔드포인트:
    GET  /health            - Ollama 연결 상태
    POST /explain/building  - 기능1: 개별 건물 위험원인 설명
    POST /briefing/region   - 기능3: 지역 상황요약 브리핑
"""
import ollama_client
import prompts
import rag
import shap_provider as shap
from contracts import (BuildingExplainRequest, CaseHit, LlmResponse,
                       RegionBriefingRequest, SimilarCaseRequest,
                       SimilarCaseResponse)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ESafe LLM 사이드카")

# 데모용: JSP(8080)에서 직접 호출 허용. 운영에선 Java 프록시로 바꾸는 게 안전.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ollama": ollama_client.is_available(), "model": ollama_client.LLM_MODEL,
            "mock": shap.USE_MOCK, "embed_model": rag.EMBED_MODEL,
            "case_count": rag.case_count()}


@app.post("/explain/building", response_model=LlmResponse)
def explain_building(req: BuildingExplainRequest):
    # 호출 측이 factor를 안 넘겼을 때만(=모델 미연결) mock SHAP으로 채운다.
    used_mock = False
    if not req.factors:
        req.factors = shap.building_factors(req.building_id or "demo")
        used_mock = shap.USE_MOCK
    prompt = prompts.build_building_prompt(req)
    try:
        text = ollama_client.chat(prompts.SYSTEM_PROMPT, prompt)
    except Exception as e:
        raise HTTPException(503, f"LLM 호출 실패: {e}")
    return LlmResponse(text=text, model=ollama_client.LLM_MODEL, used_mock=used_mock)


@app.post("/briefing/region", response_model=LlmResponse)
def briefing_region(req: RegionBriefingRequest):
    used_mock = False
    if not req.top_factors:
        req.top_factors = shap.region_factors(req.region_name)
        used_mock = shap.USE_MOCK
    prompt = prompts.build_region_prompt(req)
    try:
        text = ollama_client.chat(prompts.SYSTEM_PROMPT, prompt)
    except Exception as e:
        raise HTTPException(503, f"LLM 호출 실패: {e}")
    return LlmResponse(text=text, model=ollama_client.LLM_MODEL, used_mock=used_mock)


@app.post("/similar-cases", response_model=SimilarCaseResponse)
def similar_cases(req: SimilarCaseRequest):
    # 질의 텍스트: 직접 지정 우선, 없으면 등급+위험요인으로 조립
    if req.query_text:
        query = req.query_text
    else:
        parts = []
        if req.grade:
            parts.append(f"{req.grade} 건물")
        parts.extend(f.label for f in req.factors)
        query = ", ".join(parts) or "전기재해 위험 건물"

    try:
        hits = rag.search(query, top_k=req.top_k)
    except Exception as e:
        raise HTTPException(503, f"사례 검색 실패(임베딩 모델 확인): {e}")

    cases = []
    for case, score in hits:
        cases.append(CaseHit(
            id=case["id"], title=case["title"], year=case.get("year"),
            building_type=case.get("building_type"), cause=case.get("cause"),
            response=case.get("response"), damage=case.get("damage"),
            prevention=case.get("prevention"), tags=case.get("tags", []),
            score=round(float(score), 3),
        ))

    summary = ""
    if hits:
        top_case = hits[0][0]
        try:
            summary = ollama_client.chat(
                prompts.SIMILAR_SYSTEM_PROMPT,
                prompts.build_similar_prompt(query, top_case),
            )
        except Exception:
            summary = f"현재 상태는 '{top_case['title']}' 사례와 유사합니다."

    return SimilarCaseResponse(cases=cases, summary=summary,
                               model=ollama_client.LLM_MODEL,
                               embed_model=rag.EMBED_MODEL)
