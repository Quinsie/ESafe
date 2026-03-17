# KESCO 전기재해위험지수 관리시스템

건물 정적 위험요소, 기상 위험, 설비 점검/검사 이력, 과거 재해 이력을 결합해 건물별 전기재해위험을 산정하고 조회하는 하이브리드 프로젝트다. Python 분석 파이프라인, H2/Oracle 적재 스크립트, Spring MVC + MyBatis + JSP 웹 애플리케이션이 함께 들어 있다.

## 현재 리포지토리 상태

이 리포지토리는 팀 공유와 GitHub 업로드를 위해 정리된 상태다.

- 포함된 것
  - Python 분석/전처리 코드
  - Java 웹 애플리케이션 코드
  - Oracle/H2 스키마 및 운영 SQL
  - 작은 참조 CSV와 코드표
  - H2용 소형 샘플 건물 시드
  - H2용 정적 기상 시드
- 제외된 것
  - 대용량 원본 GIS 데이터
  - 설비 원본 CSV
  - 사업소별/지역별 최종 분석 산출물
  - 로컬 임시 파일과 캐시
  - GitHub 제한을 넘는 전체 H2 덤프

주의:

- `api/src/main/resources/egovframework/spring/data-h2.sql`은 전체 데이터가 아니라 리포 공유용 샘플 시드다.
- `api/src/main/resources/egovframework/spring/data-h2-facility-history.sql`은 리포 공유용 빈 시드다.
- 전체 로컬 데이터를 다시 만들려면 아래의 "빠진 데이터 복원 / 재생성" 절차를 따라야 한다.

## 기술 스택

- 분석/전처리: Python, pandas, geopandas, shapely
- 웹/API: Java 8 target, Spring MVC, MyBatis, JSP, jQuery
- 실행 환경: Tomcat 8.5.x, JDK 11, Maven 3.9.x
- DB: H2, Oracle
- 지도: VWorld 2D + OpenLayers, VWorld 3D

## 주요 디렉터리

- `api`
  - Spring MVC 웹 애플리케이션 본체
- `db`
  - Oracle 기준 스키마/적재/운영 SQL 및 배치 스크립트
- `기상특보`
  - 기상청 특보 수집 스크립트와 매핑표
- `설비데이터`
  - 설비 CSV 원본 위치였던 폴더
  - 현재 `.gitignore`로 제외됨
- `사업소별 분석결과`
  - 사업소 단위 최종 분석 CSV/SHP 위치였던 폴더
  - 현재 `.gitignore`로 제외됨
- `건물연령`, `홍수위험`, `산사태위험`, `침수흔적도`, `용도지역지구`, `전기화재이력`
  - 대용량 공간데이터 폴더
  - 현재 `.gitignore`로 제외됨

## 빠른 시작

### 1. 개발 도구 준비

기본 설치 경로는 `%USERPROFILE%\dev` 기준이다.

- Tomcat: `%USERPROFILE%\dev\apache-tomcat-8.5.100`
- JDK: `%USERPROFILE%\dev\jdk-11.0.25+9`
- Maven: `%USERPROFILE%\dev\apache-maven-3.9.9`

최초 1회 자동 설치:

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev-env.ps1
```

### 2. H2 로컬 기동

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1
```

기본 URL:

- 로그인: `http://localhost:18080/login.do`
- 대시보드: `http://localhost:18080/riskDashboard.do`
- 전국 위험지도: `http://localhost:18080/riskNationwideRiskMap.do`

기본 계정:

- 관리자: `localadmin / LocalAdmin123`
- 사용자: `localuser / LocalUser123`

추가 옵션:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1 -HttpPort 18081
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1 -SkipBuild
```

### 3. Oracle 기동

Oracle은 자동 DDL 적용을 하지 않는다. 먼저 `db/00_oracle_full_setup.sql`부터 수동 실행해야 한다.

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-oracle.ps1
```

### 4. Tomcat 중지

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\stop-tomcat.ps1
```

## 환경변수 및 설정

주요 실행 설정:

- `JAVA_HOME`
- `CATALINA_HOME`
- `MAVEN_HOME` 또는 `M2_HOME`
- `RISK_ADMIN_USERNAME`
- `RISK_ADMIN_PASSWORD`
- `RISK_USER_USERNAME`
- `RISK_USER_PASSWORD`
- `KMA_AUTH_KEY`
- `RISK_ALERT_ZONE_FILE`

설정 파일:

- `api/src/main/resources/egovframework/spring/risk-db.properties`
- `api/src/main/resources/egovframework/spring/risk-db-h2.properties`
- `api/src/main/resources/egovframework/spring/risk-db-oracle.properties`
- `api/src/main/resources/egovframework/spring/risk-security.properties`

DB 프로필 전환:

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\switch-db-profile.ps1 -Profile h2
powershell -ExecutionPolicy Bypass -File .\scripts\switch-db-profile.ps1 -Profile oracle
```

## 현재 H2 시드 구성

H2 초기화는 `api/src/main/resources/egovframework/spring/context-datasource.xml`에서 아래 순서로 로드한다.

- `schema-h2.sql`
- `data-h2.sql`
- `data-h2-weather-20260211.sql`
- `data-h2-facility-history.sql`

현재 리포에 들어 있는 상태:

- `schema-h2.sql`
  - 유지
- `data-h2.sql`
  - 전체 데이터가 아닌 리포 공유용 샘플
- `data-h2-weather-20260211.sql`
  - 정적 기상 샘플 유지
- `data-h2-facility-history.sql`
  - 전체 설비 이력 대신 빈 시드

즉, 지금 리포만으로도 H2는 기동되지만, 과거처럼 `광주전남본부직할` 전체 건물 217,241건 + 설비 이력 2,064,816건이 들어 있는 상태는 아니다.

## 빠진 데이터 복원 / 재생성

### 준비해야 하는 비공개 원본

아래 폴더와 파일은 리포에 포함되지 않는다. 별도 로컬 저장본이 있어야 한다.

- `설비데이터`
  - `광주전남 일반용 점검 데이터_정제.csv`
  - `광주전남 자가용 검사 데이터_정제.csv`
- `사업소별 분석결과`
  - `광주전남본부\광주전남본부직할\통합위험분석_광주전남본부직할_20260303.csv`
- 대용량 GIS 폴더
  - `건물연령`
  - `홍수위험`
  - `산사태위험`
  - `침수흔적도`
  - `용도지역지구`
  - `전기화재이력`

### 1. 설비 주소 정제

설비 CSV가 원본 상태라면 먼저 주소 정제를 수행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\clean_facility_addresses.py
```

이 스크립트는 다음을 정리한다.

- `-0` 번지 제거
- 공백 정리
- 괄호/콤마 주변 정리
- 백업 파일 생성

### 2. 전체 건물 H2 시드 재생성

비공개 사업소 분석 CSV로 전체 `data-h2.sql`을 다시 만든다.

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_branch_data.py
```

산출물:

- `api/src/main/resources/egovframework/spring/data-h2.sql`

설명:

- `광주전남본부직할` 분석 CSV를 읽어 `TB_BUILDING_RISK`용 insert SQL을 다시 만든다.
- 리포에 있는 샘플 시드를 덮어쓴다.
- 전체 덤프는 GitHub에 올리면 안 된다.

### 3. 전체 설비 이력 H2 시드 재생성

건물 주소와 설비 주소를 매칭해 전체 설비 이력 SQL을 다시 만든다.

사전 점검:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\estimate_full_facility_load.py
```

전체 생성:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_facility_history.py
```

산출물:

- `api/src/main/resources/egovframework/spring/data-h2-facility-history.sql`

설명:

- 일반용/자가용 설비 CSV를 읽는다.
- 건물 주소 기준으로 `BLDG_SEQ`에 매핑한다.
- 동일 주소에 여러 건물이 있으면 insert가 증가할 수 있다.
- 전체 덤프는 GitHub에 올리면 안 된다.

### 4. 샘플 건물 시드 다시 만들기

팀 공유용 샘플만 다시 만들고 싶다면 PowerShell 샘플 생성 스크립트를 쓴다.

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\generate-h2-building-from-branch.ps1
```

특징:

- 기본 10,000건
- 샘플 설비 CSV 주소와 연관된 건물을 우선 선택
- 리포 공유용 샘플 재생성 용도

### 5. 샘플 설비 이력 시드 만들기

로컬 서버에 로그인해서 샘플 설비 이력을 만들 수 있다.

```powershell
cd .\api
powershell -ExecutionPolicy Bypass -File .\scripts\generate-h2-facility-history-from-csv.ps1
```

특징:

- 로컬 API 로그인 필요
- 기본 관리자 계정 사용
- 샘플 CSV 기준으로 insert를 생성

### 6. 기상 특보 CSV 다시 받기

```powershell
powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\기상특보\save_weather_warnings_csv.py
```

산출물:

- `기상특보/기상특보현황_YYYYMMDD.csv`
- `기상특보/기상특보요약_YYYYMMDD.csv`

주의:

- 위 산출물은 `.gitignore` 대상이다.
- 리포에는 스크립트와 매핑표만 유지한다.

## 주요 스크립트 매뉴얼

### 루트

- `run_app.bat`
  - Streamlit UI 실행
- `run_kesco_py.ps1`
  - Python 3.13 UTF-8 강제 실행 래퍼
- `run_building_multi_risk_analyzer.ps1`
  - `building_multi_risk_analyzer.py` 실행 래퍼
- `clean_facility_addresses.py`
  - 설비 주소 정제
- `app.py`
  - Streamlit 기반 분석 UI
- `building_multi_risk_analyzer.py`
  - 다중 위험도 분석 메인 로직
- `weather_risk_multiplier.py`
  - 기상특보 기반 위험 배수 반영

### `api/scripts`

- `setup-dev-env.ps1`
  - Tomcat/JDK/Maven 자동 설치
- `start-tomcat-h2.ps1`
  - H2 프로필로 WAR 빌드/배포/기동
- `start-tomcat-oracle.ps1`
  - Oracle 프로필로 WAR 빌드/배포/기동
- `stop-tomcat.ps1`
  - Tomcat 중지
- `switch-db-profile.ps1`
  - `risk-db.properties`를 H2/Oracle 파일로 교체
- `build-war-profiles.ps1`
  - H2/Oracle WAR 산출물을 각각 stamp
- `regenerate_h2_full_branch_data.py`
  - 전체 건물 H2 시드 생성
- `regenerate_h2_full_facility_history.py`
  - 전체 설비 이력 H2 시드 생성
- `regenerate_h2_facility_history.py`
  - 샘플/대체용 설비 이력 SQL 생성
- `generate-h2-building-from-branch.ps1`
  - 샘플 건물 시드 생성
- `generate-h2-facility-history-from-csv.ps1`
  - 샘플 설비 이력 시드 생성
- `estimate_full_facility_load.py`
  - 전체 설비 이력 insert 예상량 계산
- `analyze_facility_overlap.py`
  - 건물 주소와 설비 주소의 중첩률 점검
- `show-korea-wildfire-stack.ps1`
  - 산불 스택/보조 분석용 스크립트

### `db`

- `00_oracle_full_setup.sql`
  - Oracle 초기 진입점
- `01_create_tables.sql`
  - 주요 테이블 생성
- `04_create_weather_tables.sql`
  - 기상 테이블 생성
- `05_create_facility_inspection_tables.sql`
  - 설비 이력 테이블 생성
- `06_combined_queries.sql`
  - 결합 조회 쿼리
- `07_create_branch_hq_map.sql`
  - 본부/사업소 매핑
- `09_migrate_from_legacy_schema_oracle.sql`
  - 레거시 스키마 마이그레이션
- `10_seed_alert_zone_map.sql`
  - 기상 특보 구역 매핑

## 전국 위험지도 메모

- 구역 레이어: 줌 14 미만
- 건물 포인트: 줌 14 이상
- 건물 폴리곤: 줌 16 이상
- 포인트 상한: 20,000
- 폴리곤 상한: 1,500
- 등급 기준: `COMBINED_SCORE / COMBINED_RISK_CD`

핵심 파일:

- `api/src/main/java/egovframework/com/risk/web/RiskCombinedController.java`
- `api/src/main/resources/egovframework/sqlmap/risk/RiskCombined_SQL.xml`
- `api/src/main/java/egovframework/com/risk/util/RiskMapPolygonResolver.java`
- `api/src/main/webapp/resources/js/risk-nationwide-risk-map.js`

## Git 운영 원칙

- `.gitignore`에 잡힌 대용량 데이터와 로컬 산출물은 커밋하지 않는다.
- 전체 H2 덤프를 다시 만들더라도 공유 리포에는 올리지 않는다.
- 팀 공유가 필요하면 샘플 시드만 유지한다.
- 로컬 임시 파일 패턴:
  - `api/.tmp*`
  - `api/.m2/`
  - `api/.mvn-local-settings.xml`
  - `_tmp*.py`

## 참고 문서

루트에 아래 문서들이 별도로 있다.

- `프로젝트_기능_설명.txt`
- `개발자_온보딩_상세.txt`
- `운영_매뉴얼_상세.txt`
- `키_환경변수_정리.txt`

README는 현재 리포 기준의 운영/복구 절차를 요약한 문서이고, 위 txt 문서는 작업 히스토리와 세부 배경 설명까지 포함한다.
