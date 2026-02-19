@echo off
echo ========================================
echo 매일 자동 데이터 수집 시작
echo ========================================

cd /d C:\GIT\RoboTrader

python trade_analysis/daily_data_collection.py

if %ERRORLEVEL% EQU 0 (
    echo ✅ 데이터 수집 완료
) else (
    echo ❌ 데이터 수집 실패
)

pause
