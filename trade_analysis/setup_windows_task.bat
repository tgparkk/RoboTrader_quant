@echo off
echo ========================================
echo Windows 작업 스케줄러 설정
echo ========================================

REM 작업 스케줄러에 매일 16:00에 실행되도록 등록
schtasks /create /tn "RoboTrader_Daily_Data_Collection" /tr "C:\GIT\RoboTrader\trade_analysis\run_daily_collection.bat" /sc daily /st 16:00 /f

echo ✅ 작업 스케줄러 등록 완료
echo 매일 16:00에 자동으로 데이터 수집이 실행됩니다.

pause
