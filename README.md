# ESafe

광주·전남 전기재해 예방 관제 시스템이다. 한 코드베이스를 실제 외부 신호를 수집하는 LIVE와 반복 가능한 체험 시나리오를 제공하는 DEMO로 격리 배포한다.

> 현재 상태: 신규 구현 진행 중. 검증된 배포 URL과 최종 사용 절차는 P0 인수시험이 끝난 release에서 이 문서에 고정한다.

## 제공 범위

- H-01D `오늘의 상황 브리핑` 홈과 확정된 27개 업무 화면
- 광주·전남 실제 행정구역과 217,238개 건물 폴리곤 위험지도
- NFDS·기상특보·재난문자 신호 수집과 사건별 Case 자동화
- 공식 근거와 과거 사례를 분리한 RAG 대응 제안
- 사고·상황 보고서, 위기상황판단 보고서, 공문, 대응 계획서의 HWPX·PDF 생성
- 승인·보류·폐기, 잠긴 승인본, 수동 발송 기록과 감사 이력
- LIVE와 DEMO의 DB·큐·파일·로그·스케줄러·세션 격리

## 저장소 경계

- 애플리케이션 코드와 배포 설정만 Git으로 관리한다.
- `data/`, `storage/`, `artifacts/`, `backups/`, `secrets/`와 `.env`는 Git에서 제외한다.
- API 키, 비밀번호, 원천 데이터, DB volume, 생성 문서와 테스트 산출물은 commit하지 않는다.
- 이 저장소에는 외부 Git remote를 연결하지 않는다.

## 빠른 시작

구현이 진행되면서 아래 명령은 실제 검증된 절차로 갱신한다.

```bash
cp .env.example .env
# .env의 CHANGE_ME와 API 키를 안전하게 설정
docker compose build
docker compose up -d
./scripts/verify.sh
```

내부 접속 기준:

- LIVE: `http://127.0.0.1:8080/live/`
- DEMO: `http://127.0.0.1:8080/demo/`

외부 접속은 무료 Cloudflare Quick Tunnel 한 호스트의 `/live/`, `/demo/`로 제공한다.

```bash
# 기본 앱 stack이 healthy인 상태에서 별도 tunnel project를 시작
./scripts/start-tunnel.sh

# 현재 주소와 외부 LIVE·DEMO 응답 확인
cat storage/runtime/public-url.txt
./scripts/verify-tunnel.sh

# 필요할 때만 명시적으로 중지
./scripts/stop-tunnel.sh
```

현재 주소는 `storage/runtime/public-url.txt`에 기록된다. Quick Tunnel은 별도 계정 없이 사용하는 체험·제출용 경로이며 컨테이너를 재생성하면 주소가 바뀔 수 있다.

## 운영 명령

```bash
docker compose ps
docker compose logs --tail=200 gateway api-live api-demo worker-live worker-demo
docker compose restart api-live api-demo worker-live worker-demo
```

일반 애플리케이션 재시작에서는 `cloudflared` 컨테이너를 재생성하지 않는다. 서버나 터널 컨테이너가 재생성되면 Quick Tunnel 주소가 바뀔 수 있으므로 현재 URL을 다시 검증한다.

백업 스케줄러는 매일 03:30 KST에 LIVE·DEMO·내부 비용원장 DB, 생성 문서와 기준자산 메타데이터를 백업하고 최근 정상 7세대를 보관한다.

```bash
# 스케줄러 상태와 최근 결과
docker compose ps backup-scheduler
docker compose logs --tail=100 backup-scheduler

# 즉시 백업과 최신 정상 세대의 격리 복원 시험
docker compose run --rm --no-deps backup-scheduler \
  sh /opt/esafe/scripts/backup-now.sh
./scripts/test-restore.sh
```

## 비개발자 사용자 안내

1. 배포된 `/live/` 또는 `/demo/` 주소에서 공용 사용자 계정으로 로그인한다.
2. 홈 `오늘의 상황 브리핑`에서 새 사건, 처리할 업무, 외부 신호 상태와 지역 위험 요약을 확인한다.
3. 위험지도에서 광역시·도 → 시·군·구 → 건물 순으로 확대하고 지역 또는 건물 분석으로 이동한다.
4. 사건 카드에서 영향 건물, 상대 위험순위, 근거, 대응 제안과 과업을 확인한다.
5. 문서 초안을 생성하고 경고·근거를 검토한 뒤 승인·보류·폐기한다.
6. 승인본 HWPX와 PDF를 내려받고 외부 전달 뒤 수신처·시각·방법·메모를 수동 기록한다.

LIVE 화면에는 `실시간 연동`, DEMO 화면에는 `체험 데이터` 배지가 항상 표시된다. 근거가 부족하거나 충돌한 초안도 생성되지만 해당 경고를 확인해야 하며, 위험점수는 발생확률이 아니라 광주·전남 안의 상대점수와 순위다.

## 장애 대응

- 한 외부 신호가 30분 이상 갱신되지 않으면 지연, 60분이면 수집 장애로 표시한다. LIVE에서 장애를 체험 데이터로 숨기지 않는다.
- NFDS 외부 호출은 `.env`의 `NFDS_ENABLED=false`로 바꾸고 관련 서비스를 재시작하면 다음 시작부터 중단되며 기존 데이터는 보존된다.
- AI 호출 한도가 중단돼도 기존 근거·캐시·초안 조회와 결정적 Case 처리는 유지된다.
- 복구·백업·현재 외부 URL·release rollback의 검증 명령은 해당 기능 구현 뒤 이 문서에 추가한다.
