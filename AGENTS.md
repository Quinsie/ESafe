# 저장소 가이드라인

## 프로젝트 구조
이 저장소는 Python 분석 파이프라인과 Java 웹 애플리케이션을 함께 포함한다. 루트의 `building_multi_risk_analyzer.py`, `weather_risk_multiplier.py`, `app.py`는 분석, 전처리, Streamlit UI를 담당한다. 웹 애플리케이션은 `api/` 아래에 있으며 Java 코드는 `api/src/main/java`, MyBatis SQL은 `api/src/main/resources/egovframework/sqlmap`, JSP 및 정적 자산은 `api/src/main/webapp`, 테스트는 `api/src/test/java`에 있다. DB 스키마와 마이그레이션은 `db/`에서 관리한다. `설비데이터/`, `사업소별 분석결과/` 같은 대용량 외부 데이터는 Git에 포함하지 않는다.

## 빌드, 테스트, 개발 명령
Python 관련 명령은 항상 conda 환경 `esafe`에서 실행한다. 환경이 없으면 저장소 루트에서 `conda env create -f environment.yml`로 생성하고, 대화형 셸에서는 `conda activate esafe`, Codex 같은 비대화형 환경에서는 `conda run -n esafe ...`를 사용한다. Codex sandbox에서 Jetty/Tomcat이 `Operation not permitted`로 포트를 열지 못하면 권한 상승으로 다시 실행한다.

Windows에서는 저장소에 포함된 PowerShell 스크립트를 우선 사용하고, Linux/Codex 환경에서는 `api/scripts/start-jetty-h2.sh`를 우선 사용한다.

- `powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\clean_facility_addresses.py`: 설비 CSV 주소 정제.
- `powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_branch_data.py`: 로컬 H2 건물 시드 재생성.
- `powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\estimate_full_facility_load.py`: 전체 설비 이력 예상 insert 수 확인.
- `powershell -ExecutionPolicy Bypass -File .\run_kesco_py.ps1 .\api\scripts\regenerate_h2_full_facility_history.py`: 로컬 H2 설비 이력 시드 재생성.
- `cd api; powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1 -HttpPort 8080`: WAR 빌드 후 Tomcat에 `8080`으로 배포하고 H2 프로필 기동.
- `cd api && bash ./scripts/start-jetty-h2.sh`: Linux/Codex에서 프로젝트 로컬 `.m2/` 캐시를 사용해 H2 프로필을 `8080`으로 기동.
- `cd api; .\scripts\start-tomcat-oracle.ps1 -SkipBuild:$false`: Oracle 프로필로 배포 및 실행.
- `cd api; conda run -n esafe mvn test`: JUnit 테스트 실행.
- `cd api; conda run -n esafe mvn -DskipTests package`: `target/risk-api-1.0.0.war` 생성.

## 코딩 스타일과 네이밍
새 도구를 추가하기보다 현재 규칙을 따른다. Python과 Java 모두 4칸 들여쓰기를 사용한다. Java 패키지는 `egovframework.com.risk.*` 아래로 유지하고, 클래스는 `PascalCase`, 메서드는 `camelCase`, 상수는 `UPPER_SNAKE_CASE`를 사용한다. Python 파일은 설명적인 `snake_case`, SQL은 `04_create_weather_tables.sql`처럼 번호 기반 파일명을 유지한다. 기존 스크립트가 전제하는 UTF-8 처리 방식도 유지한다.

## 테스트 가이드
스키마 계약, 설정 로딩, 컨트롤러·서비스 동작을 바꿀 때는 `api/src/test/java`에 JUnit 4 테스트를 추가하거나 갱신한다. 테스트 클래스명은 `*Test.java` 형식을 사용하고, 메서드명은 `h2WeatherUniqueKeyMustMatchOracleShape`처럼 의도가 드러나게 작성한다. Python 데이터 스크립트는 자동화 테스트가 어렵다면 `README.md`에 적힌 기대 row 수나 insert 수로 검증한다.

## 커밋과 PR 가이드
모든 커밋 메시지는 Conventional Commits 규칙을 따른다. 최근 히스토리는 `docs:`, `fix:`, `refactor:`, `chore:` 형식을 사용하므로 새 커밋도 `fix: externalize alert zone file path`처럼 짧은 명령형 요약으로 작성한다. PR에는 변경 범위(`api`, `db`, Python 파이프라인), 필요한 외부 데이터나 환경변수, UI 변경 시 스크린샷을 포함한다. H2/Oracle 시드, SQL 마이그레이션, 온보딩 절차에 영향이 있으면 리뷰 전에 명시한다.

## 보안 및 설정 팁
외부 데이터, `api/.local-seed/` 아래 생성된 H2 시드 SQL, 실제 계정 정보는 커밋하지 않는다. 로컬 경로를 코드에 박아 넣기보다 `JAVA_HOME`, `CATALINA_HOME`, `KMA_AUTH_KEY`, `RISK_PROJECT_ROOT`, `RISK_ALERT_ZONE_FILE` 같은 환경변수를 우선 사용한다.
