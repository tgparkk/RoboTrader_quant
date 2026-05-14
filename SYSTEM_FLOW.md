# RoboTrader 퀀트 시스템 동작 흐름

> V100 단일 팩터 전환 (2026-04-14) 후 시점 기준 동작 흐름.
> 이전 4팩터 시대 문서는 [docs/archive/SYSTEM_FLOW_v4factor_pre_20260414.md](docs/archive/SYSTEM_FLOW_v4factor_pre_20260414.md) 참고.

---

## 1. 프로그램 시작

```
python main.py
    ↓
초기화: API 인증, PG 연결 (port 5433), 텔레그램 봇, 자금 관리자, 서킷 브레이커
    ↓
상태 복원: DB(`real_trading_records`)에서 미체결 포지션 로드
            → 수량/매수가/익절률(12%)/손절률(6%) 메모리 복원
    ↓
메인 루프 (6 태스크 동시 실행)
```

**메인 루프 6 태스크** (`main.py`):

| 태스크 | 역할 | 주기 |
|--------|------|------|
| 데이터 수집 | 실시간 가격 (현재가 API) | 지속 |
| 주문 모니터링 | 미체결 주문 추적 + 체결 콜백 | 지속 |
| 거래 모니터링 | TP/SL 신호 감지 + 매도 실행 | **3초마다** |
| 시스템 모니터링 | 스케줄 작업 (스크리닝, 백업) | 5초마다 체크 |
| 텔레그램 알림 | 매매·이상 이벤트 전송 | 이벤트 발생 시 |
| 리밸런싱 | 09:30 1회 매수/매도/유지 결정 | 1일 1회 |

---

## 2. 시간대별 동작

```
08:20  종목 리스트 갱신 (KOSPI + KOSDAQ → stock_list.json)
       └─ DB 백업 (7일 보관)

08:30  전일 데이터 수집
       ├─ 일봉 가격 → daily_prices
       └─ 재무제표 → quant_balance_sheet, quant_income_statement, quant_financial_ratio

08:40  장전 시장 분석 (core/pre_market_analyzer.py)
       ├─ KRX 예상체결지수 → KOSPI 등락률 추정
       ├─ 미장 (S&P500, VIX) via yfinance
       ├─ NewsQuant 글로벌 뉴스 감성 (GET /api/market/global-sentiment)
       └─ 판정: NORMAL / CAUTION / CRISIS
            CRISIS: KOSPI≤-3.0%, S&P≤-5%, VIX≥40, 뉴스 down+strong+신뢰≥60% → 전량 매도
            CAUTION: KOSPI≤-1.5%, S&P≤-3%, VIX≥30, 뉴스 down+신뢰≥40% → 매수 5종목 제한
            NORMAL: 그 외 → 정상 운영

09:00  장 시작
       └─ TP/SL 즉시 작동 (09:00 즉시 손절 허용, 2026-03-31 변경)

09:30  리밸런싱 (1회)
       ├─ 전날 15:35 스크리닝 결과 조회 (quant_portfolio)
       ├─ 3단계 매도 필터 → 탈락 종목 시장가 매도
       ├─ 6단계 매수 게이트 → 신규 종목 시장가 매수
       └─ 유지 종목 → 익절/손절률(12%/6%) 갱신

09:00 ~ 15:20  장중 모니터링
               └─ 3초마다: 보유 종목 TP/SL 체크 → 도달 시 즉시 시장가 매도

15:35  순차 실행 (3단계)
       ├─ 1단계: 전체 ~2,500종목 당일 종가 포함 일봉 수집
       ├─ 2단계: 퀀트 스크리닝 (V100 점수 계산 + 상위 10 선정 → 다음 날용)
       └─ 3단계: 일일 매매 리포트 생성
```

---

## 3. 매수 흐름 (09:30 리밸런싱)

전날 15:35 스크리닝 결과(`quant_portfolio` 상위 10) 중 신규 편입 종목에 대해:

```
1. 점수 컷:        item.total_score >= 95           # V100 buy_min_score
2. 5일 하한:       ret_5d >= -3%                    # BUY_RET5D_MIN (급락 차단)
3. 5일 천장:       ret_5d <= +17%                   # BUY_RET5D_MAX (단기 모멘텀 천장)
4. 20일 천장:      ret_20d <= +30%                  # BUY_RET20D_MAX (장기 모멘텀 천장)
5. 모멘텀 점수 하한: momentum_score >= 30           # BUY_MOMENTUM_SCORE_MIN
6. 가격 검증:      전일저가 -5% ~ 종가 +10% + 시장 대비 상대강도
   자금 예약:      reserve_funds() race condition 방지
   ↓
시장가 매수 + DB 저장 (real_trading_records)
+ 익절률 = 0.12 / 손절률 = 0.06 설정
```

**코드**: `core/quant/quant_rebalancing_service.py` + `core/helpers/rebalancing_executor.py`

---

## 4. 매도 흐름

### 리밸런싱 매도 (09:30)

```python
for stock in 보유종목:
    if score < 65:                           # Hard Stop: 즉시 매도
        sell_market()
    elif 65 <= score < 67 and rank > 30:     # Soft Stop: 조건부 매도
        sell_market()
    elif score >= 75 or rank <= 25:          # Safe Hold: 유지
        update_target_rates(0.12, 0.06)
    elif stock not in 목표_포트폴리오:        # 탈락
        sell_market()
```

### 장중 TP/SL (3초마다, 09:00 ~ 15:20)

```python
profit_rate = (현재가 - 매수가) / 매수가
if profit_rate >= 0.12:        # 익절 도달
    sell_market()
if profit_rate <= -0.06:       # 손절 도달
    sell_market()
```

**코드**: `core/trading_decision_engine.py`, `core/trading_stock_manager.py`

---

## 5. 데이터 흐름

```
yfinance + KIS API + KRX
    ↓ 08:30 / 15:35
PostgreSQL `robotrader_quant` (port 5433)
    ├─ daily_prices            (일봉 + ret_1d/5d/20d, vol_20d)
    ├─ financial_data          (재무 raw)
    ├─ quant_balance_sheet, quant_income_statement, quant_financial_ratio
    ├─ quant_factors           (V100 점수 + momentum_score + factor_rank)
    ├─ quant_portfolio         (상위 50 by V100 score)
    ├─ real_trading_records    (실전 매매)
    └─ virtual_trading_records (가상 매매)

분봉 / 현재가는 메모리 only (DB 미저장).
```

---

## 6. 상태 전이 (종목)

```
SELECTED → BUY_PENDING → POSITIONED → SELL_CANDIDATE → SELL_PENDING → COMPLETED
                                                                      → FAILED
```

`core/trading_stock_manager.py`에서 관리. 프로그램 재시작 시 DB 미체결 포지션 로드하여 `POSITIONED` 상태로 복원.

---

## 7. 안전 장치

상세는 [docs/safety_mechanisms.md](docs/safety_mechanisms.md). 요약:

- **09:00 즉시 TP/SL 작동** — 09:00-09:05 손절 차단 제거 (2026-03-31)
- **당일 손절 재매수 차단** — 같은 날 같은 종목 못 사게
- **6단계 매수 게이트** — 위 매수 흐름 참조
- **Thread-Safe 매수** — Lock으로 중복 매수 방지
- **중복 매도 차단** — UNIQUE 인덱스 + IntegrityError
- **전역 API Rate Limiting** — `kis_auth.py` 60ms 간격, 서킷 브레이커
- **리밸런싱 매도 쿨다운** — 매도 후 3일 재매수 차단 (`REBALANCING_SELL_COOLDOWN_DAYS=3`)
- **CRISIS 레짐 전량 매도** — 매크로 이벤트 자동 대응

---

## 8. 코드 진입점

| 작업 | 파일 |
|------|------|
| 시스템 시작 | `main.py` |
| 매매 판단 (TP/SL) | `core/trading_decision_engine.py` |
| 종목 상태 관리 | `core/trading_stock_manager.py` |
| 09:30 리밸런싱 | `core/quant/quant_rebalancing_service.py` |
| 매수 실행 + 검증 | `core/helpers/rebalancing_executor.py` |
| 15:35 스크리닝 | `core/quant/quant_screening_service.py` |
| TP/SL 계산 | `core/quant/target_profit_loss_calculator.py` |
| 장전 레짐 분석 | `core/pre_market_analyzer.py` |
| KIS API + Rate Limit | `api/kis_auth.py` |
| DB 인터페이스 | `db/database_manager.py` |
| 시스템 상수 | `config/constants.py` |
| 백테스트 엔진 | `backtest/backtester.py` |
| 백테스트 팩터 | `backtest/factor_calculator.py` |

---

**관련 문서**:
- [README.md](README.md) — 빠른 시작 + 개요
- [CLAUDE.md](CLAUDE.md) — 아키텍처 + 현재 설정값 (개발자용)
- [docs/safety_mechanisms.md](docs/safety_mechanisms.md) — 안전 장치 상세
- [docs/multiverse_guide.md](docs/multiverse_guide.md) — 백테스트 멀티버스 가이드
