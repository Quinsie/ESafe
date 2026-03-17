# 작업 로그 — scripts 환경 셋업

## 2026-02-18 작업 이력

---

### [오류 1] 하드코딩된 경로 — 다른 PC에서 실행 불가

**발생 스크립트:** `start-tomcat-h2.ps1`, `start-tomcat-oracle.ps1`

**증상:** `C:\Users\user\dev\...` 로 특정 계정에 종속된 경로가 기본값으로
박혀 있어 다른 PC/계정에서 실행 시 "Tomcat not found", "JAVA_HOME not found" 오류.

**1차 수정 (2026-02-18):** `$env:USERPROFILE\dev\...` 로 대체 → 계정 종속 해결.

**2차 수정 (2026-02-18):** 시스템 환경변수 우선 적용으로 업그레이드.
서버처럼 `JAVA_HOME`, `CATALINA_HOME`, `MAVEN_HOME` 이 이미 설정된 환경에서는
해당 값을 자동 사용하고, 없으면 `$env:USERPROFILE\dev\...` 폴백.

```powershell
# 적용된 파라미터 기본값 패턴
[string]$TomcatHome = $(if ($env:CATALINA_HOME) { $env:CATALINA_HOME } else { "$env:USERPROFILE\dev\apache-tomcat-8.5.100" })
[string]$JavaHome   = $(if ($env:JAVA_HOME)     { $env:JAVA_HOME }     else { "$env:USERPROFILE\dev\jdk-11.0.25+9" })
[string]$MavenCmd   = $(if ($env:MAVEN_HOME)    { "$env:MAVEN_HOME\bin\mvn.cmd" } elseif ($env:M2_HOME) { "$env:M2_HOME\bin\mvn.cmd" } else { "$env:USERPROFILE\dev\apache-maven-3.9.9\bin\mvn.cmd" })
```

---

### [오류 2] startup.bat / shutdown.bat 실행 안 됨

**발생 스크립트:** `start-tomcat-h2.ps1`, `start-tomcat-oracle.ps1`

**증상:** `Push-Location` 후 `cmd /c "startup.bat"` 실행 시
"startup.bat는 내부 또는 외부 명령이 아닙니다" 오류.

**원인:** `cmd /c`가 PowerShell의 현재 위치를 상속하지 않는 케이스 존재.

**수정:**
```powershell
# 변경 전
Push-Location (Join-Path $TomcatHome "bin")
try { cmd /c "startup.bat" | Out-Host } finally { Pop-Location }

# 변경 후 — 전체 경로 변수 직접 호출
& $startupBat | Out-Host
```

shutdown도 동일하게 처리 + Tomcat 미기동 시 오류 무시:
```powershell
try { & $shutdownBat 2>&1 | Out-Null } catch { }
```

---

### [오류 3] 한글 깨짐 (인코딩)

**발생 환경:** Windows 한국어 + Tomcat 8.5 + JDK 11

**증상:** 브라우저에서 한글 페이지 접속 시 글자 깨짐.

**원인 1:** `server.xml` Connector에 `URIEncoding` 미설정 → Tomcat 기본값(ISO-8859-1)으로 URL 디코딩.

**원인 2:** `setenv.bat` 없음 → JVM `file.encoding` 이 Windows 기본값 `MS949` 로 동작 → JSP 파일을 MS949로 읽음.

**수정 1:** `conf/server.xml` Connector에 `URIEncoding="UTF-8"` 추가:
```xml
<Connector port="18080" protocol="HTTP/1.1"
           connectionTimeout="20000"
           redirectPort="8443"
           maxParameterCount="1000"
           URIEncoding="UTF-8"
           />
```

**수정 2:** `bin/setenv.bat` 신규 생성:
```bat
set JAVA_OPTS=%JAVA_OPTS% -Dfile.encoding=UTF-8 -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8
```

---

## Oracle(운영) 서버 배포 시 적용 사항

### 경로 설정 — 3가지 방법 중 선택

#### 방법 A: 시스템 환경변수 설정 (권장)

서버 관리자 권한으로 아래 환경변수를 시스템에 등록하면
스크립트가 자동으로 읽어옴 (파라미터 불필요).

| 환경변수 | 값 예시 |
|----------|---------|
| `JAVA_HOME` | `C:\jdk-11.0.25+9` 또는 `/usr/lib/jvm/java-11` |
| `CATALINA_HOME` | `C:\apache-tomcat-8.5.100` 또는 `/opt/tomcat` |
| `MAVEN_HOME` | `C:\apache-maven-3.9.9` 또는 `/opt/maven` |

Windows 등록 방법:
```powershell
# 관리자 PowerShell에서 실행
[System.Environment]::SetEnvironmentVariable("JAVA_HOME",     "C:\실제\jdk경로",    "Machine")
[System.Environment]::SetEnvironmentVariable("CATALINA_HOME", "C:\실제\tomcat경로", "Machine")
[System.Environment]::SetEnvironmentVariable("MAVEN_HOME",    "C:\실제\maven경로",  "Machine")
```
등록 후 PowerShell 재시작 필요.

#### 방법 B: 실행 시 파라미터 직접 전달

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-oracle.ps1 `
  -TomcatHome "C:\실제\tomcat경로" `
  -JavaHome   "C:\실제\jdk경로" `
  -MavenCmd   "C:\실제\maven\bin\mvn.cmd"
```

#### 방법 C: 로컬 개발 PC (setup-dev-env.ps1 설치 후)

환경변수 없어도 `$env:USERPROFILE\dev\...` 폴백으로 자동 동작.
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-oracle.ps1
```

---

### 인코딩 설정 — 운영 서버에도 동일 적용 필요

운영 서버의 Tomcat에도 아래 두 가지 반드시 적용:

**1. `{CATALINA_HOME}/conf/server.xml`**
```xml
<Connector ... URIEncoding="UTF-8" />
```

**2. `{CATALINA_HOME}/bin/setenv.bat` (Windows) 또는 `setenv.sh` (Linux)**

Windows:
```bat
set JAVA_OPTS=%JAVA_OPTS% -Dfile.encoding=UTF-8 -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8
```

Linux:
```bash
export JAVA_OPTS="$JAVA_OPTS -Dfile.encoding=UTF-8 -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8"
```

---

### Oracle 프로파일 전환

운영 배포 시 `start-tomcat-oracle.ps1` 이 자동으로 oracle 프로파일로 전환.
- 활성 파일: `src/main/resources/egovframework/spring/risk-db.properties`
  → 내용이 `risk-db-oracle.properties` 내용으로 교체됨
- `risk.db.init.enabled=false` 확인 필수 (Oracle에서 H2 초기화 SQL 실행 방지)

### Oracle 배포 추가 체크리스트

`README-oracle-apply-20260212.txt` 참고:
1. Oracle 19c에 단일 DDL 진입점 실행
   - `db/00_oracle_full_setup.sql`
   - `api/src/main/resources/egovframework/spring/schema-oracle.sql` 사용 금지 (deprecated)
2. WAR 배포 (`-SkipBuild:$false` 로 빌드 포함 실행)
3. 운영 검증 엔드포인트 확인
   - `/selectCombinedList.do` → HTTP 200, resultCode=OK
   - `/selectCombinedDetail.do` → HTTP 200, resultCode=OK
   - `/selectGradeStats.do` → HTTP 200, resultCode=OK
   - `/selectHqSummary.do` → 본부별 집계 확인
   - `/refreshWeatherData.do`(POST, ADMIN) → SQL 오류 없이 수행
