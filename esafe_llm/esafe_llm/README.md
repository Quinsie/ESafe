# ESafe LLM 사이드카

전국 위험지도의 **AI 브리핑/상황요약 보고서**와 **건물 위험원인 설명(XAI)** 기능을
담당하는 로컬 LLM 서비스. Qwen(Ollama) + SHAP 기반.

```
CatBoost 모델(160 피처) → SHAP(상위 요인) → 이 서비스(프롬프트+Ollama) → 화면
                          └ shap_provider.py 한 곳만 모델에 맞춰 교체하면 됨
```

## 0. 사전 준비 (1회)

```bash
brew install ollama            # 이미 설치돼 있음
ollama serve &                 # 데몬 실행 (한 번만)
ollama pull qwen2.5:7b         # 생성 모델 (~4.7GB)
ollama pull bge-m3             # 임베딩 모델, 유사사례 RAG용 (~1.2GB)

conda activate esafe
pip install -r esafe_llm/requirements.txt
```

## 1. 서비스 실행

```bash
conda activate esafe
uvicorn app:app --app-dir esafe_llm --port 8800 --reload
```

확인:
```bash
curl http://localhost:8800/health
# {"ollama": true, "model": "qwen2.5:7b", "mock": true}
```

## 2. 동작 테스트 (모델 없이 mock으로)

```bash
# 지역 브리핑 (기능 3)
curl -s -X POST http://localhost:8800/briefing/region \
  -H 'Content-Type: application/json' \
  -d '{"region_name":"광주광역시 북구"}' | python -m json.tool

# 건물 위험원인 설명 (기능 1)
curl -s -X POST http://localhost:8800/explain/building \
  -H 'Content-Type: application/json' \
  -d '{"building_id":"A","predicted_score":89,"grade":"고위험"}' | python -m json.tool

# 유사 사고 사례 추천 (기능 2, RAG)
curl -s -X POST http://localhost:8800/similar-cases \
  -H 'Content-Type: application/json' \
  -d '{"grade":"고위험","factors":[{"feature":"ageScore","label":"건물 연령","contribution":10}]}' \
  | python -m json.tool
```

웹:
- 전국 위험지도 페이지 하단 **'AI 브리핑 생성'** 버튼 (기능 3)
- 건물 상세 페이지 **'AI 위험원인 설명'** / **'유사 사례 검색'** 버튼 (기능 1·2)

## 기능 2(RAG) 실제 사례 데이터 연결

`cases_seed.json`은 발표/데모용 **예시 사례 12건**이다. 실제 KESCO/국가화재정보시스템(NFDS)
사례로 교체하려면 같은 형식(`cause`/`response`/`damage`/`prevention`/`text`)으로 채우면 된다.
임베딩 인덱스는 서버 기동 후 첫 검색 시 자동 생성된다(메모리 캐시). 사례가 수천 건 이상으로
커지면 `rag.py`의 numpy 코사인을 FAISS/Chroma로 교체.

## 3. 팀원 CatBoost 모델 연결 (모델 나온 뒤)

받을 것 3가지:
1. 모델 파일 (`.cbm` / `.pkl`)
2. 피처 160개 **이름 리스트** (+ 한국어 표시명/단위)
3. 입력 샘플 1행

연결 절차:
1. `pip install catboost shap pandas` (requirements.txt 주석 해제)
2. `shap_provider.py`의 `FEATURE_LABELS`에 160개 매핑 채우기
3. `building_factors()` / `region_factors()`를 `_real_building_factors_example()` 참고해 실제 SHAP 계산으로 교체
4. `ESAFE_LLM_USE_MOCK=0` 환경변수로 실행

→ LLM/프론트 코드는 **수정 불필요**. RiskFactor 계약만 지키면 됨.

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ESAFE_LLM_MODEL` | `qwen2.5:7b` | Ollama 모델 태그 |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 주소 |
| `ESAFE_LLM_USE_MOCK` | `1` | 1=mock SHAP, 0=실제 모델 |
