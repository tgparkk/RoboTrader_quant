@echo off
chcp 65001 > nul
echo ========================================
echo      RoboTrader 차트 생성
echo ========================================

:: 현재 디렉토리로 이동
cd /d "%~dp0"

:: 가상환경 존재 확인
if not exist "venv\Scripts\activate.bat" (
    echo ❌ 가상환경이 없습니다. run_robotrader.bat을 먼저 실행해주세요.
    pause
    exit /b 1
)

:: 가상환경 활성화
echo 가상환경 활성화 중...
call venv\Scripts\activate.bat

:: UTF-8 인코딩 설정
set PYTHONUTF8=1

echo.
echo 📊 차트 생성 옵션:
echo   1. 모든 차트 (최근 1일)
echo   2. 모든 차트 (최근 7일)  
echo   3. 모든 차트 (최근 30일)
echo   4. 점수 분포만 (최근 1일)
echo   5. 성과 요약만 (최근 1일)
echo.

set /p choice=선택하세요 (1-5): 

if "%choice%"=="1" (
    echo 📈 최근 1일 모든 차트 생성 중...
    python utils/chart_cli.py --type all --days 1
) else if "%choice%"=="2" (
    echo 📈 최근 7일 모든 차트 생성 중...
    python utils/chart_cli.py --type all --days 7
) else if "%choice%"=="3" (
    echo 📈 최근 30일 모든 차트 생성 중...
    python utils/chart_cli.py --type all --days 30
) else if "%choice%"=="4" (
    echo 📊 점수 분포 차트 생성 중...
    python utils/chart_cli.py --type score --days 1
) else if "%choice%"=="5" (
    echo 📋 성과 요약 차트 생성 중...
    python utils/chart_cli.py --type summary --days 1
) else (
    echo ❌ 잘못된 선택입니다.
    pause
    exit /b 1
)

echo.
echo ✅ 차트 생성 완료! charts 폴더를 확인하세요.
pause