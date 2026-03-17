@echo off
chcp 65001 > nul
echo ========================================
echo 전기안전 위험도 통합분석 시스템
echo ========================================
echo.

cd /d "%~dp0"

echo Streamlit 앱을 시작합니다...
echo 브라우저가 자동으로 열립니다.
echo 종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.
echo.

if not "%PYTHON_EXE%"=="" (
    "%PYTHON_EXE%" -m streamlit run app.py --server.port 8501
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.13 -m streamlit run app.py --server.port 8501
    ) else (
        python -m streamlit run app.py --server.port 8501
    )
)

pause
