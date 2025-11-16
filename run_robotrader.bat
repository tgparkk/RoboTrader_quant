@echo off
chcp 65001 > nul
echo ========================================
echo    RoboTrader 주식 단타 거래 시스템
echo ========================================

::: 현재 디렉토리로 이동
cd /d "%~dp0"

::: Python 가상환경 확인 및 생성
if not exist "venv" (
    echo 가상환경이 없습니다. 생성 중...
    python -m venv venv
    if errorlevel 1 (
        echo Python이 설치되지 않았거나 경로에 없습니다.
        echo Python을 설치하고 PATH에 추가한 후 다시 실행해주세요.
        pause
        exit /b 1
    )
)

::: 가상환경 활성화
echo 가상환경 활성화 중...
call venv\Scripts\activate.bat

::: pip 업그레이드 (선택)
where pip >nul 2>nul
if %errorlevel%==0 (
    echo pip 업그레이드 중...
    python -m pip install --upgrade pip
) else (
    echo pip을 찾을 수 없습니다. 건너뜁니다.
)

::: 의존성 패키지 설치 (requirements.txt가 있을 때만)
if exist "requirements.txt" (
    echo 의존성 패키지 설치 중...
    set PYTHONUTF8=1
    pip install -r requirements.txt --no-cache-dir
) else (
    echo requirements.txt가 없어 패키지 설치를 건너뜁니다.
)

::: 설정 파일 확인
if not exist "config\key.ini" (
    echo.
    echo ❌ 설정 파일이 없습니다!
    echo config\key.ini 파일을 생성하고 API 키를 설정해주세요.
    echo config\key.ini.example 파일을 참고하세요.
    echo.
    pause
    exit /b 1
)

::: 로그 디렉토리 생성
if not exist "logs" mkdir logs

::: 로그 파일명 생성 (YYYYMMDD_HHMMSS)
for /f "tokens=1-3 delims=/- " %%a in ("%date%") do (set YYYY=%%a&set MM=%%b&set DD=%%c)
set HH=%time:~0,2%
set MN=%time:~3,2%
set SS=%time:~6,2%
set HH=%HH: =0%
set LOGFILE=logs\robotrader_%YYYY%%MM%%DD%_%HH%%MN%%SS%.log

::: 중복 실행 방지: 기존 PID 파일 존재 시 경고 (main.py에서도 방지함)
if exist "bot.pid" (
    echo ⚠️ 기존 실행 흔적이 있습니다: bot.pid
    echo 기존 프로세스가 실행 중이 아니라면 bot.pid를 삭제하세요.
)

::: 프로그램 실행
echo.
echo 🚀 RoboTrader 시작 중...
echo 종료하려면 Ctrl+C를 누르세요.
echo.
set PYTHONIOENCODING=utf-8
python -X utf8 main.py %* 1>> "%LOGFILE%" 2>&1

::: 종료 메시지
echo.
echo RoboTrader가 종료되었습니다.
echo 로그 파일: %LOGFILE%
pause