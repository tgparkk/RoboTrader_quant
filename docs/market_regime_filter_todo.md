# 시장 레짐 필터 TODO

## 배경
2026-03-09 미국-이란 전쟁 상황에서 수동 전량 매도 경험 후,
"시스템이 자동으로 위기를 판단하고 대응하게" 만드는 프로젝트.

## 완료

- [x] 긴급 매도 스크립트 (`scripts/emergency_sell_all.py`)
- [x] 규칙 기반 필터 — KOSPI 이평선 데드크로스 + 변동성 (`core/market_regime_filter.py`)
- [x] main.py 리밸런싱 전 레짐 체크 통합
- [x] DB 매도 기록 동기화 (KIS 체결 → DB 반영)
- [x] 백테스트 레짐 필터 (KOSPI 갭 + S&P500 + VIX) — 108조합 검증, **효과 없음** 결론
- [x] NXT 벨웨더 30종목 + 미장 데이터 장전 분석기 (`core/pre_market_analyzer.py`)
- [x] NewsQuant 뉴스 감성 예측 통합 (REST API `GET /api/market/predict`)
- [x] CRISIS 시 보유 전량 시장가 매도 + 텔레그램 알림 (`main.py:_execute_crisis_sell_all`)
- [x] 08:40 장전 분석 → 09:05 리밸런싱에 반영 (`main.py`)
- [x] 텔레그램 알림: 레짐 판단 결과 + NXT/미장/뉴스 데이터 포함
- [x] `run_all_robotraders.bat` — NewsQuant `start.bat`으로 변경 (API 서버 포함)

## TODO

### 1. 레짐 이력 DB 저장
- [ ] 매일 레짐 판단 결과를 DB에 기록 (추후 분석용)
- [ ] 테이블: `market_regime_history` (date, regime, reason, nxt_sentiment, news_sentiment)

## 설계 결정 기록

### Claude AI 제외 (2026-03-09 결정)
- Anthropic API는 별도 과금 → 사용자 거부
- 대안: NewsQuant 로컬 뉴스 감성 분석 (추가 비용 없음)

### NewsQuant 통합 (2026-03-09)
- `GET http://127.0.0.1:8000/api/market/predict?hours=24`
- 글로벌 뉴스 (CNBC, MarketWatch, Google News) + 국내 뉴스 (네이버금융, DART, 한경, 매경)
- 시간대별 가중치: 장전 글로벌65%/국내35%, 장중 글로벌40%/국내60%
- 레짐 규칙:
  - CRISIS: direction=down + strength=strong + confidence>=60%
  - CAUTION: direction=down + confidence>=40%
  - NewsQuant 연결 실패 → 무시 (NXT+미장만 사용)

### 규칙 기반 임계값 (2026-03-09 초기 설정)
- CRISIS: NXT극약세(-0.7), S&P500 -5%, VIX >40, 뉴스 강한하락(60%)
- CAUTION: NXT약세(-0.3), S&P500 -3%, VIX >30, 뉴스 하락(40%)
- NORMAL: 위 조건 모두 해당 없음
- 주의: 아직 실전 검증 전, 운영하며 조정 필요

### 백테스트 레짐 필터 결과 (2026-03-09)
- KOSPI 시가 갭 + S&P500 + VIX 조합 108개 전수 탐색
- **결론: 수치 기반 레짐 필터는 현재 전략에 효과 없음**
- 기준선(필터 없음): 샤프 11.88, MDD 13.4% → 모든 조합이 기준선보다 나빴음
- 원인: buy_min_score=65 필터가 이미 동일 역할, 매수 차단이 반등 기회 손실
- `regime_filter_enabled=False`(기본값) 유지

### 장전 분석기 설계 (2026-03-09)
- 3개 데이터 소스: NXT 벨웨더 30종목, 미장 (S&P500/VIX/NASDAQ/환율), NewsQuant 뉴스
- NXT 심리 점수: 방향성(60%) + 종목수(40%) = -1.0~+1.0
- CRISIS → 보유 전량 시장가 매도 (자동, 텔레그램 알림 후)
- CAUTION → 매수 최대 5종목 축소
- 08:40 실행 → 09:05 리밸런싱에 결과 반영
