@echo off
chcp 65001 > nul
echo ========================================
echo     시각화 라이브러리 설치
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

:: pip 업그레이드
echo pip 업그레이드 중...
python -m pip install --upgrade pip

:: 시각화 라이브러리 설치
echo 시각화 라이브러리 설치 중...
pip install matplotlib>=3.7.0 --no-cache-dir
if errorlevel 1 (
    echo ❌ matplotlib 설치 실패
    pause
    exit /b 1
)

pip install seaborn>=0.12.0 --no-cache-dir
if errorlevel 1 (
    echo ❌ seaborn 설치 실패
    pause
    exit /b 1
)

pip install plotly>=5.15.0 --no-cache-dir
if errorlevel 1 (
    echo ❌ plotly 설치 실패
    pause
    exit /b 1
)

echo.
echo ✅ 시각화 라이브러리 설치 완료!
echo.
echo 이제 다음 명령으로 차트를 생성할 수 있습니다:
echo   python utils/chart_cli.py --type all --days 1
echo.
pause