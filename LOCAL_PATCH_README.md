# ESafe 로컬 통합 패치 설명

이 문서는 `agent/esafe-demo-map-sld-data-extract` 브랜치에서 로컬 테스트 환경에 적용한
기능과 PR 검토 포인트를 정리한다. 패치는 특정 사용자 PC의 절대 경로에 의존하지 않으며,
실행 시 필요한 키와 데이터는 Docker Compose 환경변수와 저장소 내부 fixture를 사용한다.

## 패치 목적

- NAVER 지도와 거리뷰를 위험지도 안에서 일관되게 제공한다.
- DEMO 시나리오 1의 화재 위치와 주변 영향 건물을 실제 건물 도형으로 표현한다.
- 지역별 고위험 건물 목록을 14열 Excel 파일로 내려받을 수 있게 한다.
- 건물별 단선결선도를 등록하고 Upstage OCR로 설비 및 화재 유발 요소를 추출한다.
- 복원된 지역 위험분석 선택 UI와 DEMO 시나리오 리모컨을 Docker 환경에서 제공한다.

## 주요 변경사항

### 1. NAVER 위험지도와 거리뷰

- NAVER Maps JavaScript SDK 로더와 지도 컴포넌트를 추가했다.
- 건물 도형 클릭 시 같은 지도 화면 안에서 주변 거리뷰를 열 수 있다.
- 지도 단계는 광역시도 → 시군구 → 읍면동 → 건물 순으로 전환한다.
- 개별 건물 벡터는 줌 16부터 조회·렌더링해 밀집 지역의 2,000건 이상 GeoJSON
  재렌더링 부하를 줄였다.
- `NAVER_MAPS_NCP_KEY_ID`는 `.env`에서만 주입한다. Client Secret은 JavaScript 지도
  SDK에 사용하지 않으며 저장소에 보관하지 않는다.

주요 파일:

- `frontend/src/map.tsx`
- `frontend/src/naver_maps.tsx`
- `backend/app/api/spatial.py`
- `backend/app/spatial.py`
- `infra/gateway/nginx.conf`

### 2. DEMO 화재 시나리오 1

- 화재 발생점을 임의의 점이 아닌 매칭된 건물 SHP 도형으로 표시한다.
- 화재 건물은 빨간색, 반경 100m 이내 건물은 주황색으로 표시한다.
- 시나리오 단계 이동 시 영향 건물 목록과 지도 도형이 동일한 공간 연산 결과를 사용한다.
- DEMO 시나리오 리모컨의 선택·초기화·단계 진행 흐름을 복원했다.

주요 파일:

- `backend/app/demo/playback.py`
- `backend/app/automation/impact.py`
- `backend/app/api/demo.py`
- `frontend/src/demo.tsx`
- `frontend/src/cases.tsx`
- `backend/alembic/versions/20260730_0019_fire_impact_radius.py`

### 3. 자료 추출

- 좌측 Overview 메뉴에 `자료 추출` 화면을 추가했다.
- 광역시도와 시군구를 AND 조건으로 선택하고 상위 1%, 5%, 10% 위험 건물을 조회한다.
- Excel 결과는 다음 14열로 제한한다.

  1. 번호
  2. 건물명
  3. 지번주소
  4. 광역시도
  5. 시군구
  6. 위험순위
  7. 위험점수
  8. 상위백분위
  9. 주용도
  10. 주구조
  11. 건축연도
  12. 건물연령
  13. 6개월 내 점검·검사 이력
  14. 1년 내 점검·검사 이력

주요 파일:

- `frontend/src/data_extract.tsx`
- `backend/app/api/data_extract.py`
- `backend/app/data_extract.py`
- `backend/tests/test_data_extract.py`

### 4. 단선결선도 관리와 Upstage OCR

- 건물상세 화면에서 관리자가 PDF 또는 이미지 단선결선도를 등록·교체할 수 있다.
- 등록된 도면이 있을 때만 `설비 추출 시작`을 실행할 수 있다.
- OCR 공급자는 Upstage Document OCR만 사용하며 Paddle OCR은 포함하지 않는다.
- 큰 도면은 원본에서 300 DPI로 다시 렌더링한 뒤 외함별로 자르고, 2배 확대·선명화한
  Crop을 OCR한다.
- Crop 결과의 좌표는 전체 원본 도면 좌표로 복원해 한 장의 결과 화면에 파란 박스로
  합성한다.
- 설비는 변압기, 차단기, 발전기, 배터리 등 설비군으로 묶어 설명하며 파란 박스를
  선택하면 해당 설비군 설명으로 이동한다.
- 결과 도면은 마우스 휠로 50%~500% 확대·축소할 수 있고 빈 도면을 드래그해 이동할 수
  있다.
- 분석 요청마다 별도 실행 키를 사용해 동일 문서의 재분석을 허용한다.

도면 파이프라인은 `C:\Users\...\Desktop\결선도리딩`을 런타임에 참조하지 않는다.
필요한 v1~v11 문법 체인과 Crop 검출 로직을 `backend/app/sld_grammar` 및
`backend/app/sld_box_pipeline.py`에 포함해 Docker 이미지 자체로 실행된다.

주요 파일:

- `backend/app/sld_documents.py`
- `backend/app/sld_analysis.py`
- `backend/app/sld_box_pipeline.py`
- `backend/app/sld_grammar/`
- `backend/app/api/sld_analysis.py`
- `frontend/src/sld_analysis.tsx`
- `backend/alembic/versions/20260730_0017_sld_analysis.py`
- `backend/alembic/versions/20260730_0018_building_sld_documents.py`

### 5. Docker와 최종 적용 런처

- LIVE/DEMO에 단선결선도 전용 Celery worker를 추가했다.
- API, 일반 worker, SLD worker, gateway를 저장소 Dockerfile과 Compose 정의로
  빌드·재시작한다.
- `launch-scenario1-fix.cmd`가 `scripts/apply-scenario1-fix.ps1`을 호출한다.
- 적용 스크립트는 마이그레이션, 컨테이너 상태, DEMO 시나리오 재생, SLD worker
  실행 가능 여부를 검증한다.
- 배포 마지막 단계에서 DS-01의 기존 단선결선도 분석 시도·완료 이력만 비우고 등록된
  원본 도면은 유지한다.

## 데이터베이스 마이그레이션

적용 순서는 다음과 같다.

1. `20260730_0017_sld_analysis`
2. `20260730_0018_building_sld_documents`
3. `20260730_0019_fire_impact_radius`

upstream의 `20260729_0016_standalone_documents` 이후에 순차 적용된다.

## 필요한 환경변수

`.env.example`을 복사해 `.env`를 만들고 실제 값은 로컬 또는 배포 환경에서만 입력한다.

```dotenv
NAVER_MAPS_NCP_KEY_ID=
UPSTAGE_API_KEY=
UPSTAGE_DOCUMENT_MODEL=ocr
UPSTAGE_DOCUMENT_TIMEOUT_SECONDS=300
SLD_MAX_UPLOAD_BYTES=26214400
SLD_MAX_REGION_OCR_CROPS=24
SLD_REGION_RENDER_DPI=300
SLD_REGION_CROP_UPSCALE=2
```

NAVER Cloud 콘솔의 Web 서비스 URL에는 로컬 origin과 실제 배포 origin을 등록해야 한다.
API 키, Client Secret, 비밀번호, 토큰은 커밋하지 않는다.

## 실행 방법

Windows Docker Desktop 환경에서는 저장소 루트의 다음 파일을 실행한다.

```text
launch-scenario1-fix.cmd
```

수동 실행 시에는 저장소 루트에서 다음 순서로 확인한다.

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

DEMO 접속 주소는 `http://127.0.0.1:8080/demo`이다.

## 검증 범위

PR 전 최소 검증 명령은 다음과 같다.

```powershell
cd backend
ruff check .
mypy app
pytest -q

cd ..\frontend
npm ci
npm run verify

cd ..
docker compose config --quiet
git diff --check
```

2026-07-31 로컬 검증 결과:

- Backend: Ruff 통과, Mypy 통과, Pytest 210개 통과
- Frontend: Biome 통과, TypeScript 통과, Vitest 42개 통과, Vite production build 통과
- `git diff --check` 통과
- Docker Compose 실제 재빌드·readiness 검증은 Docker Desktop에서
  `launch-scenario1-fix.cmd` 실행으로 완료해야 한다.

주요 회귀 테스트는 다음을 포함한다.

- 지도 단계별 공간 API 및 줌 16 건물 조회 제한
- 화재 건물과 100m 영향 건물 공간 연산
- DEMO 시나리오 단계 진행
- 14열 Excel 다운로드 계약
- Upstage 전용 단선결선도 OCR과 Crop 좌표 복원
- 결과 도면의 휠 줌, 드래그 이동, 설비군 박스 선택
- Docker worker 및 API readiness

## PR 제안

제안 제목:

```text
feat: integrate NAVER risk map, data export, fire scenario, and SLD analysis
```

제안 본문 요약:

```text
## Summary
- integrate NAVER Maps and in-map panorama with zoom-16 building overlays
- restore DEMO scenario controls and render fire impact on actual building geometry
- add 14-column high-risk building Excel export
- add Docker-contained Upstage-only SLD upload, crop OCR, equipment grouping, and interactive result viewer
- add migrations and dedicated LIVE/DEMO SLD workers

## Validation
- backend lint, type checks, and tests
- frontend lint, type checks, tests, and production build
- Docker Compose config/build/readiness checks

## Security
- no API keys or client secrets are committed
- NAVER ncpKeyId and Upstage key are injected through environment variables
```

## 리뷰 시 확인할 사항

- 4MB DEMO 단선결선도 fixture를 저장소에 포함하는 정책이 허용되는지
- Upstage Crop별 OCR 호출량과 비용 한도가 운영 정책에 맞는지
- 줌 16에서도 초고밀도 지역에서 건물 GeoJSON 2,000건 제한이 재현되는지
- 배포 환경의 NAVER Web 서비스 URL 등록이 완료됐는지
- 신규 마이그레이션 3개가 기존 운영 데이터에 미치는 영향
