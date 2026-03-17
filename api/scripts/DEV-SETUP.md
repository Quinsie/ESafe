# 개발 환경 셋업 가이드

## 변경 이력

### 2026-02-18 — 하드코딩 경로 제거 (`start-tomcat-h2.ps1`)

**문제:** 기본값이 `C:\Users\user\dev\...` 로 특정 계정에 종속되어 있어서
다른 PC나 다른 계정에서 실행하면 경로를 못 찾아 오류 발생.

**해결:** `$env:USERPROFILE` 로 대체 → 실행하는 계정의 홈 폴더를 자동으로 사용.

```powershell
# 변경 전
[string]$TomcatHome = "C:\Users\user\dev\apache-tomcat-8.5.100"
[string]$JavaHome   = "C:\Users\user\dev\jdk-11.0.25+9"
[string]$MavenCmd   = "C:\Users\user\dev\apache-maven-3.9.9\bin\mvn.cmd"

# 변경 후
[string]$TomcatHome = "$env:USERPROFILE\dev\apache-tomcat-8.5.100"
[string]$JavaHome   = "$env:USERPROFILE\dev\jdk-11.0.25+9"
[string]$MavenCmd   = "$env:USERPROFILE\dev\apache-maven-3.9.9\bin\mvn.cmd"
```

---

## 신규 PC 셋업 절차

### 1단계: 개발 도구 설치 (최초 1회)

PowerShell을 열고 프로젝트 루트(`api/`)로 이동 후 실행:

```powershell
cd C:\...\kescoaitest\api
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev-env.ps1
```

자동으로 아래 3가지를 `%USERPROFILE%\dev\` 에 다운로드 & 압축 해제:

| 도구 | 버전 | 설치 경로 |
|------|------|-----------|
| Apache Tomcat | 8.5.100 | `%USERPROFILE%\dev\apache-tomcat-8.5.100` |
| Eclipse Temurin JDK | 11.0.25+9 | `%USERPROFILE%\dev\jdk-11.0.25+9` |
| Apache Maven | 3.9.9 | `%USERPROFILE%\dev\apache-maven-3.9.9` |

### 2단계: Tomcat 기동

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1
```

기동 후 접속:
- 앱: http://localhost:18080/
- 대시보드: http://localhost:18080/riskDashboard.do

---

## 참고

- 이미 설치된 도구는 `setup-dev-env.ps1` 이 자동으로 건너뜀 (재설치 없음)
- 포트 변경이 필요하면: `-HttpPort 8080` 파라미터 추가
- 빌드 포함 기동: `-SkipBuild:$false` 파라미터 추가
