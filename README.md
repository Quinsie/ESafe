# KESCO 전기재해위험지도 관리시스템 E-Safe

전북대학교 2026학년도 1학기 캡스톤디자인 프로젝트, 전기재해위험지도 관리시스템 E-Safe.
건물 정적 위험요소, 기상 위험, 설비 점검/검사 이력, 과거 화재 이력을 결합해 건물별 전기재해위험도를 산정하고 조회하는 프로젝트다. Python 분석 파이프라인, H2/Oracle 적재 스크립트, Spring MVC + MyBatis + JSP 웹 애플리케이션이 함께 들어 있다.

## 온보딩 목표

이 저장소의 기본 온보딩 기준은 `광주전남본부직할` 전체 데이터다.

로컬 H2 기준 검증된 기대값:

- 건물 위험 데이터: `217241`건
- 일반용 설비 이력 insert: `2023433`건
- 자가용 설비 이력 insert: `41383`건
- 설비 이력 총 insert: `2064816`건

전체 데이터 SQL은 GitHub에 올리지 않는다. 대신 외부 원본 데이터를 프로젝트 루트에 복사한 뒤, 로컬에서 전체 H2 시드를 다시 생성해서 기동하는 구조다.

## 저장소에 포함되는 것

- Python 분석/전처리 코드
- Java 웹/API 코드
- Oracle/H2 스키마 및 운영 SQL
- 작은 참조 CSV와 코드표
- H2 기동용 기본 리소스
- 전체 데이터 복원 스크립트

## 저장소에 포함되지 않는 것

- 대용량 GIS 원본 데이터
- 설비 원본 CSV
- 사업소별 최종 분석 결과물
- 로컬에서 생성한 전체 H2 SQL
- 각종 캐시, 임시 파일, 빌드 산출물

로컬 전체 H2 SQL은 아래 경로에 생성되며 `.gitignore` 대상이다.

- `api/.local-seed/data-h2.full.sql`
- `api/.local-seed/data-h2-facility-history.full.sql`

## 필수 외부 데이터

아래 폴더와 파일을 별도 전달받아 프로젝트 루트 바로 아래에 둬야 한다.

### 1. 설비데이터

필수 파일:

- `설비데이터/광주전남 일반용 점검 데이터_정제.csv`
- `설비데이터/광주전남 자가용 검사 데이터_정제.csv`

선택:

- `설비데이터/*.backup_addrfix_*`
- 원본 xlsx/csv

원본만 있고 `_정제.csv`가 없다면 먼저 주소 정제를 실행해야 한다.

### 2. 사업소별 분석결과

필수 파일:

- `사업소별 분석결과/광주전남본부/광주전남본부직할/통합위험분석_광주전남본부직할_20260303.csv`

전국 위험지도 건물 폴리곤 표시까지 쓰려면 같은 이름의 SHP 세트도 필요하다.

- `.shp`
- `.shx`
- `.dbf`
- `.prj`
- `.cpg`

### 3. GIS 보조 데이터 폴더

아래 폴더는 분석 스크립트 및 지도 기능에서 직접 읽는다.

- `건물연령/`
- `홍수위험/`
- `산사태위험/`
- `침수흔적도/`
- `용도지역지구/`
- `전기화재이력/`

## 외부 데이터 배치 방식

별도로 받은 압축이 `data/` 폴더 형태라면, `data` 폴더 자체를 두는 게 아니라 그 안의 하위 폴더들을 프로젝트 루트에 꺼내놔야 한다.

정상 구조:

```text
<clone-root>/
  api/
  db/
  README.md
  설비데이터/
  사업소별 분석결과/
  건물연령/
  홍수위험/
  산사태위험/
  침수흔적도/
  용도지역지구/
  전기화재이력/
```

잘못된 구조:

```text
<clone-root>/
  data/
    설비데이터/
    사업소별 분석결과/
```

현재 코드와 스크립트는 프로젝트 루트를 기준으로 외부 데이터를 찾는다.

## 전체 데이터 온보딩 절차

### 1. 저장소 clone

```powershell
git clone https://github.com/Quinsie/ESafe.git
cd .\ESafe
```

### 2. 외부 데이터 복사

별도 전달받은 데이터 묶음에서 아래 폴더들을 clone한 프로젝트 루트에 복사한다.

- `설비데이터`
- `사업소별 분석결과`
- `건물연령`
- `홍수위험`
- `산사태위험`
- `침수흔적도`
- `용도지역지구`
- `전기화재이력`

### 3. 개발 도구 설치

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev-env.ps1
cd ..
```

기본 설치 위치:

- Tomcat: `%USERPROFILE%\dev\apache-tomcat-8.5.100`
- JDK: `%USERPROFILE%\dev\jdk-11.0.25+9`
- Maven: `%USERPROFILE%\dev\apache-maven-3.9.9`

이미 `JAVA_HOME`, `CATALINA_HOME`, `MAVEN_HOME`, `M2_HOME`가 잡혀 있으면 그 값을 우선 사용한다.

### 4. 설비 주소 정제 여부 확인

전달받은 파일이 이미 아래 두 파일이면 이 단계는 건너뛰면 된다.

- `설비데이터/광주전남 일반용 점검 데이터_정제.csv`
- `설비데이터/광주전남 자가용 검사 데이터_정제.csv`

정제 전 원본만 있으면 프로젝트 루트에서 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\clean_facility_addresses.py
```

### 5. 전체 건물 H2 시드 생성

프로젝트 루트에서 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_branch_data.py
```

출력 파일:

- `api/.local-seed/data-h2.full.sql`

기대 출력:

- `Output building rows : 217241`

### 6. 전체 설비 이력 H2 시드 생성

사전 규모 확인:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\estimate_full_facility_load.py
```

기대 출력:

- `general_estimated_inserts=2023433`
- `self_estimated_inserts=41383`
- `total_estimated_inserts=2064816`

실제 생성:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_facility_history.py
```

출력 파일:

- `api/.local-seed/data-h2-facility-history.full.sql`

기대 출력:

- `general_inserts=2023433`
- `self_inserts=41383`

### 7. H2 서버 기동

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1
```

정상일 때 스크립트 출력에 아래 문구가 포함된다.

- `Using local full H2 building seed:`
- `Using local full H2 facility seed:`
- `Tomcat started: http://localhost:18080/`

`start-tomcat-h2.ps1`는 `api/.local-seed/` 아래의 전체 SQL이 존재하면 자동으로 그 파일들을 사용한다.

### 8. 브라우저 확인

- `http://localhost:18080/login.do`
- `http://localhost:18080/riskDashboard.do`
- `http://localhost:18080/riskNationwideRiskMap.do`

기본 계정:

- 관리자: `localadmin / LocalAdmin123`
- 사용자: `localuser / LocalUser123`

## 온보딩 검증 기준

아래 기준을 만족하면 전체 데이터 온보딩이 완료된 상태다.

- `login.do` 접속 가능
- 관리자 계정 로그인 가능
- 건물 목록 총건수가 `217241`
- 설비 상세 이력 조회 가능
- 전국 위험지도 진입 가능
- 외부 SHP가 준비된 경우 건물 폴리곤 레이어 표시 가능

PowerShell에서 관리자 로그인 후 총건수를 확인하려면:

```powershell
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginPage = Invoke-WebRequest -Uri 'http://localhost:18080/login.do' -WebSession $session -UseBasicParsing
$token = ([regex]::Match($loginPage.Content, 'name="_csrf" value="([^"]+)"')).Groups[1].Value
Invoke-WebRequest -Uri 'http://localhost:18080/perform_login.do' -Method Post -Body @{ username='localadmin'; password='LocalAdmin123'; _csrf=$token } -WebSession $session -MaximumRedirection 5 -UseBasicParsing | Out-Null
$resp = Invoke-WebRequest -Uri 'http://localhost:18080/selectCombinedList.do?pageIndex=1&pageSize=1' -WebSession $session -UseBasicParsing
($resp.Content | ConvertFrom-Json).totalCount
```

정상 기대값:

- `217241`

## 문제 해결

### `login.do`가 404인 경우

Tomcat만 떠 있고 웹 애플리케이션 컨텍스트가 시작 실패했을 가능성이 높다.

우선 확인할 로그:

- `%USERPROFILE%\dev\apache-tomcat-8.5.100\logs\localhost.<날짜>.log`
- `%USERPROFILE%\dev\apache-tomcat-8.5.100\logs\catalina.<날짜>.log`

### 전체 데이터가 안 올라오는 경우

아래를 순서대로 확인한다.

1. `api/.local-seed/data-h2.full.sql` 존재 여부
2. `api/.local-seed/data-h2-facility-history.full.sql` 존재 여부
3. `start-tomcat-h2.ps1` 실행 시 `Using local full H2 ...` 문구 출력 여부
4. 외부 데이터 폴더가 프로젝트 루트 바로 아래에 있는지 여부
5. `통합위험분석_광주전남본부직할_20260303.csv` 파일 존재 여부
6. `_정제.csv` 설비 파일 존재 여부

### 수동 편집한 SQL에서 H2 초기화가 깨지는 경우

H2 초기화 SQL은 `UTF-8 without BOM`으로 저장해야 한다. BOM이 들어가면 첫 SQL 문장이 깨져서 초기화에 실패할 수 있다.

### 기존 환경변수와 충돌하는 경우

다음 값이 이미 잡혀 있으면 자동 설치 경로보다 우선 사용된다.

- `JAVA_HOME`
- `CATALINA_HOME`
- `MAVEN_HOME`
- `M2_HOME`
- `RISK_PROJECT_ROOT`
- `KMA_AUTH_KEY`
- `RISK_ALERT_ZONE_FILE`

## 주요 스크립트

### 루트

- `run_kesco_py.ps1`: Python UTF-8 실행 헬퍼
- `clean_facility_addresses.py`: 설비 주소 정제
- `building_multi_risk_analyzer.py`: 통합 위험 분석 메인 스크립트
- `weather_risk_multiplier.py`: 기상 특보 기반 위험도 보정
- `app.py`: Streamlit UI

### `api/scripts`

- `setup-dev-env.ps1`: Tomcat/JDK/Maven 설치
- `start-tomcat-h2.ps1`: H2 WAR 빌드/배포/기동
- `start-tomcat-oracle.ps1`: Oracle WAR 빌드/배포/기동
- `stop-tomcat.ps1`: Tomcat 중지
- `switch-db-profile.ps1`: H2/Oracle 설정 전환
- `regenerate_h2_full_branch_data.py`: 전체 건물 H2 시드 생성
- `estimate_full_facility_load.py`: 설비 이력 예상 insert 규모 계산
- `regenerate_h2_full_facility_history.py`: 전체 설비 이력 H2 시드 생성
- `generate-h2-building-from-branch.ps1`: 공유용 건물 시드 생성
- `generate-h2-facility-history-from-csv.ps1`: 공유용 설비 이력 시드 생성

## 코드에서 외부 데이터를 읽는 위치

- 건물 목록/상세/통계 조회
  - `api/src/main/resources/egovframework/sqlmap/risk/RiskCombined_SQL.xml`
- 설비 상세 `rawJson` 복원
  - `api/src/main/java/egovframework/com/risk/service/impl/RiskCombinedServiceImpl.java`
- 전국 위험지도 건물 폴리곤
  - `api/src/main/java/egovframework/com/risk/util/RiskMapPolygonResolver.java`
- 전체 건물 H2 시드 생성
  - `api/scripts/regenerate_h2_full_branch_data.py`
- 전체 설비 이력 H2 시드 생성
  - `api/scripts/regenerate_h2_full_facility_history.py`
- GIS 기반 통합 분석
  - `building_multi_risk_analyzer.py`

## Git 운영 원칙

- `설비데이터/`, `사업소별 분석결과/`, GIS 원본 폴더는 커밋하지 않는다.
- `api/.local-seed/`에 생성된 전체 H2 SQL은 커밋하지 않는다.
- 공유 리포에는 스크립트와 코드, 소형 참조 자산만 남긴다.
