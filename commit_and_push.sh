#!/bin/bash
cd /d/GIT/RoboTrader_quant

echo "=========================================="
echo "Git 상태 확인 및 커밋/푸시"
echo "=========================================="

echo ""
echo "[1] 현재 상태 확인"
git status --short

echo ""
echo "[2] 최근 커밋 확인"
git log --oneline -3

echo ""
echo "[3] 변경사항 확인"
git diff HEAD --name-only main.py core/trading_decision_engine.py

echo ""
echo "[4] 변경사항 스테이징"
git add main.py core/trading_decision_engine.py

echo ""
echo "[5] 커밋 실행"
git commit -m "매매 판단 로직 개선: 일봉 데이터 사용 및 점수 기반 판단

- 매매 판단을 1분봉 데이터에서 일봉 데이터(daily_prices)로 변경
- 점수 기반 매매 판단 로직 구현
  - quant_portfolio 테이블에서 점수 조회 (우선)
  - MLFactorCalculator로 실시간 점수 계산 (fallback)
  - 점수 50점 이상 또는 상위 50위 이내 종목 매수 신호 발생
- main.py의 _analyze_buy_decision 메서드 수정
- trading_decision_engine.py의 analyze_buy_decision 메서드 수정"

echo ""
echo "[6] 원격 저장소에 푸시"
git push origin main

echo ""
echo "=========================================="
echo "작업 완료!"
echo "=========================================="
