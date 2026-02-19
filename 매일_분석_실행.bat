@echo off
chcp 65001 >nul
echo ================================================================================
echo               📊 RoboTrader 일일 매매 분석 📊
echo ================================================================================
echo.

REM 가상환경 활성화
call venv\Scripts\activate.bat

echo [1/3] 일일 매매 분석 실행 중...
echo.
python daily_analysis.py
echo.

echo [2/3] DB 상태 점검 실행 중...
echo.
python check_virtual_trading_db.py
echo.

echo [3/3] 공식 일일 리포트 실행 중...
echo.
python scripts\daily_trading_summary.py
echo.

echo ================================================================================
echo ✅ 모든 분석 완료!
echo ================================================================================
echo.
echo 생성된 파일:
echo   - 오늘자_매매분석_YYYYMMDD.md (상세 보고서)
echo   - 로그 출력 (콘솔)
echo.
pause
