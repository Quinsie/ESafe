# ESafe

광주·전남 전기재해 예방 관제 시스템이다. 한 코드베이스를 실제 외부 신호를 수집하는 LIVE와 반복 가능한 체험 시나리오를 제공하는 DEMO로 격리 배포한다.

## 핵심 범위

- H-01D `오늘의 상황 브리핑` 홈과 확정된 27개 업무 화면
- 광주·전남 실제 행정구역과 217,238개 건물 폴리곤 위험지도
- NFDS·기상특보·재난문자 원천 신호 수집, 결정적 중복 판정과 사건별 Case 자동화
- 공식 근거와 과거 사례를 구분하는 RAG 대응 제안
- 사고·상황 보고서, 위기상황판단 보고서, 공문, 대응 계획서의 HWPX·PDF 생성
- 점검 대상 시나리오 계산, 팀 배정, 공통 승인과 과업 생성
- 승인·보류·폐기, 잠긴 승인본, 수동 발송 기록과 감사 이력
- LIVE와 DEMO의 DB·큐·파일·로그·스케줄러·세션 격리

위험도는 발생확률이 아니다. 2026-03 기준 v27.1 계열 `final_score`를 광주·전남 내부 상대점수, 순위, 상위 백분위와 네 구간으로 표현한다. 실시간 신호는 기준점수를 다시 계산하지 않고 사건 영향과 관제 우선상태를 결정한다.

## LIVE와 DEMO

| 구분 | LIVE | DEMO |
| --- | --- | --- |
| 화면 배지 | `실시간 연동` | `체험 데이터` |
| 외부 신호 | NFDS·기상특보·재난문자 어댑터 | 외부 호출 없음 |
| 사건 생성 | 실제 수집 원천 | 선택한 원천형 fixture가 같은 파싱·정규화·Case 경로를 통과 |
| 시나리오 제어 | 없음 | 시작·일시정지·다음 단계·초기화 |
| 데이터 | LIVE 전용 DB·큐·파일·세션 | DEMO 전용 DB·큐·파일·세션 |

읽기 전용 건물·위험도·RAG 기준자산만 양쪽에서 같은 snapshot을 사용한다. LIVE에는 DEMO fixture를 주입하지 않으며 DEMO는 실제 외부 신호를 호출하지 않는다.

## 저장소와 데이터 경계

- 공식 GitHub 저장소는 `https://github.com/Quinsie/ESafe`이며 기본 branch는 `main`이다.
- 애플리케이션 코드와 배포 설정은 GitHub와 `Main:/data2/ESafe` 작업트리에서 같은 Git 이력으로 관리한다.
- 배포 release는 검증된 `main` commit 전체 SHA로 식별하고 원자적 Conventional Commit 단위로 push한다.
- `data/`, `storage/`, `artifacts/`, `backups/`, `secrets/`와 `.env`는 Git에서 제외한다.
- API 키, 비밀번호, 원천 데이터, DB volume, 생성 문서와 테스트 산출물은 commit하지 않는다.
- `/data2/ESafe/data`와 `storage/reference`는 사용자·기준 자산이다. 검증 없이 삭제하거나 덮어쓰지 않는다.

## 설치와 설정

필수 조건은 Docker Engine, Compose plugin, `curl`, `jq`, 약 217,238개 건물 기준자산과 RAG snapshot이다. 실행 사용자는 Docker를 sudo 없이 사용할 수 있어야 한다.

```bash
cd /data2/ESafe
cp .env.example .env
chmod 600 .env
# .env의 모든 CHANGE_ME, snapshot ID와 외부 API 키를 안전하게 설정한다.
docker compose config --quiet
```

중요 환경변수:

- `ESAFE_APP_VERSION`: 이미지 태그. 배포 commit 전체 SHA 사용 권장
- `ESAFE_BUILD_COMMIT`: 배포 commit 전체 SHA
- `ESAFE_PUBLIC_USER_ID`, `ESAFE_PUBLIC_USER_PASSWORD`: 공용 사용자 로그인 정보
- `ESAFE_SESSION_SECRET_LIVE`, `ESAFE_SESSION_SECRET_DEMO`: 프로필별 독립 세션 서명값
- `UPSTAGE_API_KEY`: Solar Pro 3 및 Solar Embedding 2 호출 키
- `DATA_GO_KR_SERVICE_KEY`: 기상특보·재난문자 공공 API 인증키
- `NAVER_MAPS_NCP_KEY_ID`: NAVER Maps JavaScript API의 ncpKeyId. Cloud 콘솔의 Web 서비스 URL에는 포트와 경로를 제외한 `http://127.0.0.1`, `http://localhost` 및 실제 공개 origin을 등록
- `NFDS_ENABLED`: `false`이면 다음 관련 서비스 재시작부터 NFDS 외부 호출만 중단
- `ESAFE_COOKIE_SECURE`: Quick Tunnel 공개 배포에서는 반드시 `true`; 로컬 HTTP 전용 격리 환경에서만 `false`
- `UPSTAGE_CHAT_TIMEOUT_SECONDS`: 비동기 대응안 생성의 provider 응답 제한시간
- `UPSTAGE_DOCUMENT_MODEL`, `UPSTAGE_DOCUMENT_TIMEOUT_SECONDS`: 단선결선도 전용
  Upstage OCR 모델과 응답 제한시간
- `SLD_MAX_UPLOAD_BYTES`: 건물상세 단선결선도 업로드 크기 제한(기본 25MB)
- `SLD_MAX_REGION_OCR_CROPS`, `SLD_REGION_RENDER_DPI`, `SLD_REGION_CROP_UPSCALE`:
  단선결선도 외함 Crop의 최대 수, 원본 렌더 DPI(기본 300), OCR용 확대 배율(기본 2배)

비밀키와 내부 비용 설정은 브라우저·사용자 API·로그에 노출하지 않는다. `NAVER_MAPS_NCP_KEY_ID`는 브라우저 SDK 로드에 쓰는 공개 식별자이므로 허용 Web 서비스 URL로 사용처를 제한한다. NAVER Client Secret은 JavaScript 지도 SDK에 사용하지 않으며 저장소나 브라우저에 넣지 않는다. 개인정보가 포함된 자료는 서버 내부 비식별 검증을 통과한 사본만 Upstage에 전송한다. Quick Tunnel을 시작하기 전에 `ESAFE_COOKIE_SECURE=true`인지 확인한다.

### 공용 로그인 비밀번호 교체

최초 배포 직후와 로그인 정보가 노출됐다고 의심되는 즉시 아래 명령으로 LIVE·DEMO 비밀번호를 함께 교체한다. 명령은 새 무작위 비밀번호를 생성하고 두 DB의 Argon2id 해시를 갱신한 뒤 기존 세션을 모두 폐기하며, 평문 비밀번호를 프로세스 인자나 로그에 넣지 않는다.

```bash
cd /data2/ESafe
./scripts/rotate-public-password.sh
```

지정한 시험용 비밀번호를 적용해야 할 때는 값을 명령행 인자로 넘기지 말고 권한이 `600`인 임시 파일로 전달한다. 성공 후 임시 파일은 즉시 삭제한다.

```bash
ESAFE_PUBLIC_PASSWORD_FILE=/secure/path/password.txt \
  ./scripts/rotate-public-password.sh
```

새 값은 권한이 `600`인 `.env`의 `ESAFE_PUBLIC_USER_PASSWORD`에만 저장된다. 운영자에게 전달할 때만 다음 명령을 보안 터미널에서 실행하고 출력·셸 이력·메신저 보관 정책을 확인한다.

```bash
sed -n 's/^ESAFE_PUBLIC_USER_ID=//p' .env
sed -n 's/^ESAFE_PUBLIC_USER_PASSWORD=//p' .env
```

교체 스크립트는 두 프로필 중 하나의 갱신이 실패하면 이미 변경한 프로필을 기존 비밀번호로 되돌린다. 완료 뒤 로그인 smoke와 공개 터널 검증까지 통과해야 성공한다.

### 최초 기준자산 구성

현재 서버에는 검증된 기준자산이 준비돼 있다. 새 환경에서만 manifest와 snapshot 경로를 먼저 배치한 뒤 아래 순서를 사용한다.

```bash
set -a
. ./.env
set +a
./scripts/import-reference.sh
./scripts/import-similarity.sh
./scripts/build-rag-sources.sh
./scripts/import-rag-index.sh
./scripts/build-rag-embeddings.sh
./scripts/import-rag-embeddings.sh
./scripts/verify-reference.sh
```

Upstage embedding 생성은 유료 호출이며 같은 입력·모델 결과가 이미 있으면 다시 실행하지 않는다.

## 빌드와 배포

배포할 commit에서 작업트리가 깨끗한지 먼저 확인한다. `.env`의 버전과 build commit을 같은 전체 SHA로 맞춘 뒤 빌드한다.

```bash
cd /data2/ESafe
release_commit=$(git rev-parse HEAD)
test -z "$(git status --porcelain)"
sed -i "s/^ESAFE_APP_VERSION=.*/ESAFE_APP_VERSION=$release_commit/" .env
sed -i "s/^ESAFE_BUILD_COMMIT=.*/ESAFE_BUILD_COMMIT=$release_commit/" .env
docker compose build api-live db-live document-worker-live gateway
docker compose up -d --remove-orphans
docker compose ps
./scripts/smoke.sh
```

Compose의 공통 이미지 때문에 위 네 build 대상이 백엔드, 데이터베이스, 문서 런타임과 프런트 gateway 이미지를 모두 만든다. migration 서비스는 기동 의존관계에서 LIVE·DEMO·비용원장을 현재 schema로 올리고 seed를 멱등 적용한다.

내부 접속:

- LIVE: `http://127.0.0.1:8080/live/`
- DEMO: `http://127.0.0.1:8080/demo/`

DB·Redis·worker 포트는 외부에 공개하지 않으며 gateway도 loopback에만 바인딩된다.

## 외부 접속

학교 방화벽의 inbound 포트를 열지 않고, 별도 계정·도메인이 필요 없는 Cloudflare Quick Tunnel을 앱과 분리해 운용한다.

```bash
# 앱 stack이 healthy일 때 최초 1회 또는 터널 복구 시
./scripts/start-tunnel.sh

# 현재 공개 호스트와 LIVE·DEMO·API 응답 검증
cat storage/runtime/public-url.txt
./scripts/verify-tunnel.sh

# 명시적으로 터널을 제거할 때만
./scripts/stop-tunnel.sh
```

공개 주소 한 개에 `/live/`와 `/demo/`를 붙여 사용한다. 일반 앱 build·재시작에는 tunnel compose project를 건드리지 않아 현재 주소를 유지한다. 서버 재부팅이나 `cloudflared` 컨테이너 재생성 시 주소가 바뀔 수 있으며, 이 경우 `public-url.txt`의 새 주소만 안내한다.

### 외부 신호 어댑터 주소 교체

공식 제공처가 URL을 바꾸거나 정식 API로 전환할 때는 코드를 수정하기 전에 `.env`의 전체 endpoint를 바꾼다. `NFDS_MONITOR_URL`, `KMA_WARNING_BASE_URL`, `DISASTER_MESSAGE_URL`은 각각 실제 요청 가능한 전체 기준 경로여야 하며 키는 기존 secret 변수에만 둔다.

```bash
cd /data2/ESafe
docker compose config --quiet
docker compose up -d --no-build worker-live scheduler-live api-live
docker compose logs --tail=100 worker-live scheduler-live
./scripts/smoke.sh
./scripts/verify-tunnel.sh
```

교체 후 `LIVE / 자동화 기록`에서 HTTP·파서 상태와 다음 호출시각을 확인한다. 계약 확인 전에는 이전 어댑터를 제거하거나 DEMO fixture를 LIVE 대체값으로 사용하지 않는다.

## 비개발자 사용자 설명서

### 1. 로그인과 홈

1. 전달받은 외부 주소의 `/live/` 또는 `/demo/`에 접속한다.
2. 전달받은 공용 사용자 계정으로 로그인한다.
3. `오늘의 상황 브리핑`에서 새 사건, 처리할 업무, 외부 신호 상태, 광주·전남 위험 요약을 확인한다.
4. 우측 상단 `알림`에서 실제 승인 대기, 위험 Case, 최근 자동화 완료 기록을 확인하고 읽음 처리한다.

로그인은 세션만 만들며 대시보드·지도·전체 건물 데이터를 미리 읽지 않는다. 브라우저 뒤로가기나 탭 복귀 시 목록의 검색·필터·페이지·선택 상태를 유지한다.

### 2. 위험지도와 분석

1. `위험 지도`에서 광주시·전남도 → 시·군·구 → 읍·면·동 → 건물 순으로 확대한다. 다음 단계가 나타나면 이전 단계의 색칠은 사라져 지도가 겹치지 않는다.
2. NAVER 지도에서 확대·축소와 일반/위성 지도 유형을 사용할 수 있다. 행정구역을 선택한 뒤 상세 카드의 단계별 확대 버튼 또는 지도 휠 확대를 사용해 다음 단계로 이동한다.
3. 건물을 지도나 목록에서 선택하면 양쪽 선택 상태가 동기화된다. `거리뷰` 또는 선택 건물의 `거리뷰 열기`로 주변 300m 이내 파노라마를 지도 안에서 확인한다.
4. 모든 행정단계의 `지역 분석 보기`는 지역 상세로, 건물 단계의 `건물 분석 보기`는 건물 상세로 이동한다.
5. `위험 분석`에서는 광역시·도, 시·군·구, 읍·면·동, 건물 순위를 전환해 확인한다. 지역은 상위 10% 건물 수, 건물은 광주·전남 모델 순위를 기준으로 한다.
6. 분석 화면에서 상대점수, 광주·전남 순위, 상위 백분위, 연결 시설을 확인한다.
7. 보고서 보기는 동일 사실을 읽기 쉬운 분석 보고 형태로 제시한다.
8. `과거 사고사례`, `유사 위험시설`, `후보 시설 비교`에서 조건별 참고사례를 확인한다. 유사도는 확률이나 인과관계가 아니다.

### 3. 점검계획

1. `점검 계획`에서 지역, 위험구간, 시설 조건, 목표 개소, 팀 수와 기간을 입력한다.
2. 계산 완료 후 균형·고위험 우선·확대 시나리오를 비교한다.
3. 선택된 실제 대상과 팀별 배정을 확인한다.
4. 팀 배정 순번은 팀별 연속 구간으로 표시된다. 예를 들어 240개소를 4개 반에 균등 배정하면 `1~60`, `61~120`, `121~180`, `181~240`이다.
5. 확대안이 가용 대상이나 팀 수용량을 넘으면 조용히 축소하지 않고 차단 사유를 표시한다.
6. 선택안을 승인 요청하고 공통 `검토·승인`에서 승인하면 팀 과업이 생성된다.

### 4. 재난 Case와 자동화

1. `재난 대응`에서 사건당 카드 하나를 열고 원천 상태, 영향 건물, 상대 위험순위와 타임라인을 확인한다.
2. `근거·대응`에서 공식 현행 근거, 과거 사례, 보조 참고자료와 충분·부족·충돌 경고를 확인한다.
3. `업무`에서 제안 과업을 처리하고 필요한 실제 담당 정보는 사용자가 입력한다.
4. `자동화 기록`에서 수집·파싱·Case·RAG·문서 작업의 성공·실패와 감사기록을 확인한다.
5. 종결 조건이 충족됐을 때 `종결`에서 Case를 닫는다. 원천이 아직 진행 중이거나 열린 필수 업무가 있으면 종결이 차단된다.

LLM은 사건 존재·중복·지역·거리·위험순위·상태 전이를 결정하지 않는다. 근거가 부족하거나 충돌해도 초안은 만들지만 경고를 표시하고 허위 인용을 만들지 않는다.

### 5. 문서와 승인

1. Case의 문서 작성에서 사고·상황 보고서, 위기상황판단 보고서, 공문 또는 대응 계획서를 고른다.
2. 지역·건물 분석 화면에서는 Case 없이 독립 분석 보고서 초안을 만들 수 있다. 건물 상세의 `현장점검 요청 작성`은 해당 건물 사실을 채운 독립 공문 초안을 만든다.
3. 분석 보고서는 기존 사고·상황 보고서 양식, 현장점검 요청은 기존 한국전기안전공사 공문 양식을 바탕으로 HWPX와 PDF를 생성한다.
4. 생성된 초안의 사실, 행동별 근거, 경고와 인용 위치를 검토한다.
5. 작성자·승인자·문서번호·전화번호·개인정보는 자동 추정하지 않으므로 필요한 값만 직접 입력한다.
6. `검토·승인`에서 승인·보류·폐기 중 하나를 선택한다.
7. 승인 버전은 잠기며 수정하려면 새 초안과 재승인이 필요하다.
8. `보고서·산출물`에서 같은 승인 버전의 HWPX와 PDF를 내려받는다.
9. 시스템은 실제 이메일·전자공문을 보내지 않는다. 외부 전달 후 수신처·시각·방법·메모를 수동 발송 기록으로 남긴다.

### 6. DEMO 시나리오

1. DEMO 왼쪽 사이드바의 `WORKFLOW` 아래 `체험 시나리오`에서 여섯 시나리오의 단계와 기대 결과를 확인한다.
2. 그 아래 고정 리모컨에서 시나리오를 선택하고 시작한다. 리모컨은 어느 화면으로 이동해도 유지된다.
3. `다음 단계`로 원천 응답 → 파싱 → 정규화 → Case 생성·갱신 경로를 통제해서 재생한다.
4. 필요하면 일시정지하고 화면을 촬영하거나 다른 기능을 확인한다.
5. `초기화`는 현재 다른 시나리오가 실행 중이거나 미완료여도 그 DEMO 가변 데이터를 폐기하고 선택한 시나리오를 0단계 시작 준비 상태로 만든다. LIVE나 공유 기준자산에는 영향을 주지 않는다.
6. 촬영은 `DS-01 화재 전체 여정 → H-01D → Case → 근거·대응 → 문서·승인 → HWPX·PDF → 위험지도` 순서를 권장한다.
7. 이어서 `DS-02`의 기상특보 변경·해제, `DS-05`의 장애·복구, `DS-06`의 충분·부족·충돌 근거를 짧게 확인한다.

화면 표기의 의미:

- `실시간 연동`은 LIVE 실제 어댑터, `체험 데이터`는 DEMO 원천형 fixture를 뜻한다.
- 위험구간은 광주·전남 상대순위이며 발생확률이 아니다. 기준월과 60일 horizon을 함께 확인한다.
- `근거 충분`은 직접 공식근거가 있는 상태이고, `근거 부족`과 `근거 충돌`은 사용자 확인과 승인 사유가 필요한 상태다.
- 소스 `지연`·`수집 장애`는 기존 Case가 사라졌다는 뜻이 아니다. 마지막 성공시각과 자동화 실행기록을 확인한다.

## 검사

정적 검사와 단위·통합 테스트는 각 Dockerfile의 test stage에서 실행된다.

```bash
./scripts/verify.sh
./scripts/smoke.sh
./scripts/verify-reference.sh
./scripts/verify-tunnel.sh
./scripts/test-restore.sh
```

`smoke.sh`는 LIVE·DEMO 로그인, 217,238개 기준자산, 홈, 지도, 지역·건물, 유사사례, 인증·CSRF, schema와 프로필 격리를 검사한다. 릴리스 증적은 `artifacts/test-reports/<release-id>`에 보관하며 이미지에 포함하지 않는다.

## 운영과 장애 대응

```bash
docker compose ps
docker compose logs --tail=200 gateway api-live api-demo worker-live worker-demo
docker compose logs --tail=200 scheduler-live scheduler-demo document-worker-live document-worker-demo
docker compose restart api-live api-demo worker-live worker-demo scheduler-live scheduler-demo
./scripts/smoke.sh
```

- 한 외부 신호가 30분 이상 갱신되지 않으면 지연, 60분이면 수집 장애로 표시한다. LIVE 장애를 DEMO 데이터로 숨기지 않는다.
- NFDS 호출만 즉시 중단하려면 `.env`의 `NFDS_ENABLED=false`로 바꾸고 `scheduler-live worker-live api-live`를 재시작한다. 기존 신호와 Case는 보존된다.
- AI 비용 하드 중단이나 Upstage 장애가 발생해도 기존 근거·캐시·초안 조회와 결정적 Case 처리는 유지된다.
- 비동기 작업이 멈추면 Redis, worker, scheduler 순으로 상태와 로그를 확인한다. 같은 입력은 멱등키와 캐시로 중복 실행을 억제한다.
- 외부 주소 장애 시 앱을 재생성하지 말고 먼저 `./scripts/verify-tunnel.sh`와 tunnel 로그를 확인한다.

시작·중지·업데이트:

```bash
# 앱만 중지·재개하며 별도 Quick Tunnel 컨테이너는 건드리지 않는다.
docker compose stop
docker compose start

# 새 commit의 이미지를 만든 뒤 같은 commit 값으로 재배포한다.
release_commit=$(git rev-parse HEAD)
sed -i "s/^ESAFE_APP_VERSION=.*/ESAFE_APP_VERSION=$release_commit/" .env
sed -i "s/^ESAFE_BUILD_COMMIT=.*/ESAFE_BUILD_COMMIT=$release_commit/" .env
docker compose build api-live db-live document-worker-live gateway
docker compose up -d --no-build
./scripts/smoke.sh
```

흔한 오류와 복구:

- 로그인이 반복 실패하면 입력값을 확인하고 제한시간이 지난 뒤 다시 시도한다. 비밀번호 노출이 의심되면 `rotate-public-password.sh`를 실행한다.
- `소스 지연` 또는 `수집 장애`면 `worker-live`, `scheduler-live` 로그와 제공처 응답을 확인한다. LIVE에 fixture를 넣어 숨기지 않는다.
- 문서 산출물 한 형식만 실패하면 화면의 재시도를 사용하고 document worker 로그를 확인한다. 승인본을 직접 덮어쓰지 않는다.
- 공개 주소만 열리지 않으면 앱을 재배포하지 말고 tunnel health와 `public-url.txt`를 먼저 확인한다. 주소가 바뀌면 새 값만 안내한다.
- DB·Redis가 비정상이면 쓰기를 반복하지 말고 healthcheck, 최근 백업 checksum, 복원시험 결과 순으로 확인한다.

## 백업과 복원

백업 스케줄러는 매일 03:30 KST에 LIVE·DEMO·내부 비용원장 DB, 생성 문서와 기준자산 메타데이터를 백업하고 최근 정상 7세대를 보관한다.

```bash
docker compose ps backup-scheduler
docker compose logs --tail=100 backup-scheduler

# 즉시 백업
docker compose run --rm --no-deps backup-scheduler sh /opt/esafe/scripts/backup-now.sh

# 최신 세대를 네트워크 없는 임시 DB에 실제 복원해 계약 검사
./scripts/test-restore.sh

# 특정 검증 세대
./scripts/test-restore.sh /data2/ESafe/backups/daily/YYYYMMDDTHHMMSSZ
```

`test-restore.sh`는 운영 DB를 덮어쓰지 않는다. 실제 운영 복구가 필요하면 먼저 새 백업을 만들고 checksum을 확인한 뒤, 해당 세대와 영향받는 LIVE·DEMO·CONTROL 범위를 확정하고 유지보수 시간에 수행한다.

## 릴리스 롤백

모든 배포 이미지는 commit SHA 태그로 남긴다. 앱 코드 롤백은 작업트리가 깨끗하고 대상 이미지가 존재하며 DB schema가 하위 호환되는지 확인한 뒤 수행한다.

```bash
cd /data2/ESafe
rollback_commit=<검증된-전체-commit-SHA>
test -z "$(git status --porcelain)"
docker image inspect "esafe-backend:$rollback_commit" >/dev/null
docker image inspect "esafe-gateway:$rollback_commit" >/dev/null
git switch --detach "$rollback_commit"
sed -i "s/^ESAFE_APP_VERSION=.*/ESAFE_APP_VERSION=$rollback_commit/" .env
sed -i "s/^ESAFE_BUILD_COMMIT=.*/ESAFE_BUILD_COMMIT=$rollback_commit/" .env
docker compose up -d --remove-orphans
./scripts/smoke.sh
./scripts/verify-tunnel.sh
```

DB downgrade가 필요한 릴리스는 Alembic을 임의로 역실행하지 않는다. 배포 직전 백업을 검증하고 운영을 중지한 뒤 그 세대를 복원한다. 원인 수정 후 `git switch main`으로 돌아와 새 commit·새 이미지로 순방향 배포한다.
