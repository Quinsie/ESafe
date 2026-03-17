@echo off
chcp 65001 >nul
REM ============================================================
REM SQL*Loader 실행 배치 파일
REM 58컬럼 CSV (A0-A30 포함) → TB_BLDG_RISK_STATIC 벌크 로딩
REM ============================================================

REM --- 설정 ---
SET ORACLE_USER=username
SET ORACLE_PASS=password
SET ORACLE_TNS=host:1521/service_name
SET CTL_FILE=%~dp003_sqlldr_load.ctl
SET LOG_DIR=%~dp0logs

REM --- 로그 디렉터리 생성 ---
IF NOT EXIST "%LOG_DIR%" MKDIR "%LOG_DIR%"

REM --- 사용법 ---
IF "%~1"=="" (
    echo.
    echo 사용법: %~nx0 ^<CSV파일경로^>
    echo.
    echo 예시:
    echo   %~nx0 "C:\data\통합위험분석_광주전남본부직할_20260210.csv"
    echo   %~nx0 "C:\data\*.csv"  (여러 파일)
    echo.
    echo DB 접속 정보를 수정하려면 이 파일을 편집하세요.
    echo   ORACLE_USER, ORACLE_PASS, ORACLE_TNS
    echo.
    exit /b 1
)

REM --- 파일별 로딩 ---
SET TOTAL_FILES=0
SET SUCCESS=0
SET FAIL=0

FOR %%F IN (%~1) DO (
    SET /A TOTAL_FILES+=1
    SET CSV_FILE=%%~fF
    SET CSV_NAME=%%~nF

    echo.
    echo ============================================================
    echo [LOAD] %%~nxF
    echo ============================================================

    sqlldr %ORACLE_USER%/%ORACLE_PASS%@%ORACLE_TNS% ^
        control="%CTL_FILE%" ^
        data="%%~fF" ^
        log="%LOG_DIR%\%%~nF.log" ^
        bad="%LOG_DIR%\%%~nF.bad" ^
        discard="%LOG_DIR%\%%~nF.dsc" ^
        direct=false ^
        multithreading=true

    IF ERRORLEVEL 1 (
        echo [WARN] 일부 오류 발생 - 로그 확인: %LOG_DIR%\%%~nF.log
        SET /A FAIL+=1
    ) ELSE (
        echo [OK] 적재 완료
        SET /A SUCCESS+=1
    )
)

echo.
echo ============================================================
echo 적재 완료: 총 %TOTAL_FILES%개 파일 (성공: %SUCCESS%, 실패: %FAIL%)
echo 로그 디렉터리: %LOG_DIR%
echo ============================================================

pause
