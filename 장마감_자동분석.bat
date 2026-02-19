@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo   RoboTrader 장 마감 후 자동 분석
echo ============================================================
echo.

REM 기본: 분석만 수행 (Claude 호출 안함)
REM python scripts/auto_analysis.py --analyze-only

REM 문제 발견 시 Claude와 대화
python scripts/auto_analysis.py

echo.
echo ============================================================
echo   분석 완료 - reports/auto_analysis 폴더에서 결과 확인
echo ============================================================
pause
