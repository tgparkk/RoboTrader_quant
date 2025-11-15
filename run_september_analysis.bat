@echo off
echo ========================================
echo 9월 1일부터 17일까지 일봉 필터 분석 실행
echo ========================================

echo.
echo 1. 전체 패턴 분석 실행...
python -m core.indicators.daily_pattern_analyzer

echo.
echo 2. 일별 시뮬레이션 실행...

echo 9월 1일...
python utils/signal_replay.py --date 20250901 --export txt

echo 9월 2일...
python utils/signal_replay.py --date 20250902 --export txt

echo 9월 3일...
python utils/signal_replay.py --date 20250903 --export txt

echo 9월 4일...
python utils/signal_replay.py --date 20250904 --export txt

echo 9월 5일...
python utils/signal_replay.py --date 20250905 --export txt

echo 9월 8일...
python utils/signal_replay.py --date 20250908 --export txt

echo 9월 9일...
python utils/signal_replay.py --date 20250909 --export txt

echo 9월 10일...
python utils/signal_replay.py --date 20250910 --export txt

echo 9월 11일...
python utils/signal_replay.py --date 20250911 --export txt

echo 9월 12일...
python utils/signal_replay.py --date 20250912 --export txt

echo 9월 15일...
python utils/signal_replay.py --date 20250915 --export txt

echo 9월 16일...
python utils/signal_replay.py --date 20250916 --export txt

echo 9월 17일...
python utils/signal_replay.py --date 20250917 --export txt

echo.
echo ========================================
echo 모든 분석 완료!
echo ========================================
pause
