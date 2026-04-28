@echo off
chcp 65001 > nul
echo ========================================
echo    RoboTrader_quant_mom Trading System
echo    (mom_006676 monthly momentum strategy)
echo ========================================

cd /d "%~dp0"

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Python not found. Please install Python and add to PATH.
        pause
        exit /b 1
    )
)

echo Activating venv...
call venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install --upgrade pip

echo Installing dependencies...
set PYTHONUTF8=1
pip install -r requirements.txt --no-cache-dir

if not exist "config\key.ini" (
    echo.
    echo ERROR: config\key.ini not found!
    echo.
    pause
    exit /b 1
)

if not exist "logs" mkdir logs

echo.
echo Starting RoboTrader_quant_mom...
echo Press Ctrl+C to stop.
echo.
python main.py

echo.
echo RoboTrader_quant_mom stopped.
pause
