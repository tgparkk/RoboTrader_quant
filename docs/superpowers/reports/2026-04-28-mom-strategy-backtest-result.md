---
title: mom_006676 운영 백테스트 결과 (T9)
date: 2026-04-28
status: FAIL — 1/3 게이트 통과
spec: docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md
plan: docs/superpowers/plans/2026-04-27-mom-strategy-port-implementation.md
---

# mom_006676 운영 백테스트 결과

## 실행 환경

- **기간**: 2024-07-01 ~ 2026-03-31 (424 영업일)
- **자본**: 1,000만원
- **비용**: slippage 0.0025 / buy 0.00015 / sell 0.00245 (실측 교정)
- **DB**: robotrader_backtest (재계산 후 quant_factors 352K rows + portfolio 21K rows 갱신)
- **Paramset**: T8.4 BacktestParams 기본값 (TP/SL 99.0, port=15, hard/soft/safe 비활성)
- **factor scoring**: T8.2 momentum_scorer (lookback=12M, skip=1M, raw score, no clamp)
- **trigger**: T8.3 monthly first trading day (utils.trading_calendar)

## sim 대비 비교 (±10% 게이트)

| 지표 | sim 목표 | 운영 백테스트 | 격차 | ±10% 통과 |
|---|---|---|---|---|
| Sharpe | 1.76 | **1.45** | -17.7% | ❌ FAIL |
| Total return | +78.9% | **+84.8%** | +7.5% | ✅ OK |
| MDD | -16.6% | **-20.7%** | +24.8% | ❌ FAIL |
| 2024H2 Sharpe | -0.37 | (미측정) | — | — |

**Gate: 1/3 pass (SUCCESS 임계값 3/4 미달)**

## Verdict

**FAIL — paper trading 진입 보류.**

Total return 은 sim 과 정합 (+5.9%p) 이라 전략 자체는 작동. 그러나 risk-adjusted 지표 (Sharpe, MDD) 에서 sim 보다 변동성 4-5%p 더 높음. 운영 환경 데이터/체결 가정이 sim 과 미세하게 달라 동일 종목군 안에서도 시점·실현 가격 차이가 누적된 결과로 추정.

## 보조 메트릭

- 총 거래 수: 116 건 (월평균 5.5 건)
- 승률: 51.7% (60승 56패)
- 손익비: 2.58 (평균 익 231,071원 / 평균 손 95,834원)
- 연환산 수익률: +44.07%
- 최종 자산: 18,483,678원

거래 수가 sim 의 "월간 15종목 전수 교체" 가정 (월 7-15건 turnover) 범위 안. 흐름은 정상.

## 격차 가능 원인 (조사 우선순위)

### 1. Universe 차이 (cap≥3조 필터)
- **운영**: `daily_prices.market_cap` (close × shares_outstanding 추정)
- **sim**: multiverse_min 의 cap 소스 (FDR/MARCAP 추정 또는 다른 lookup)
- 같은 날 cap≥3조 종목 수가 sim vs ours 다르면 top-15 도 다름 → 다른 종목 → 다른 변동성
- **검증법**: 임의 월초 1-2일 골라 cap≥3조 통과 종목 리스트를 sim 과 ours 에서 추출, set diff

### 2. equal weight 정확도
- 1,000만원 ÷ 15 = 66.67만원/종목. 실제로는 정수 주 단위로 매수.
- 고가주(예: 50만원) 1주 매수 시 ~75% 활용도 → cash drag 누적
- sim 도 같은 정수 매수면 무시 가능. 다르면 수익률 노이즈.
- **검증법**: 백테스트 첫 월 첫 거래일의 종목별 매수 금액 / 총 자산 비율 출력

### 3. 종가/시가 체결 시점 차이
- 운영 백테스트: `매수: 당일 시가 × (1+slippage)` (backtester.py:5)
- sim multiverse_min: 동일한지 확인 필요 (혹시 종가 체결이면 차이 큼)

### 4. 슬리피지 적용 방식
- 운영: 매수 +0.25%, 매도 -0.25% (모델 기본)
- sim: 동일하게 0.25% 가정인지 확인. 만약 sim 이 시가 그대로면 ours 가 -0.5% 페널티 더 받음.

### 5. monthly trigger 첫 거래일 정의 차이
- ours: KRX 영업일 기준 (utils.korean_holidays.is_holiday)
- sim: multiverse_min `MonthlyRebalancer` 의 영업일 정의 (panel index 의 trading_days 일 가능성)
- 두 캘린더가 1-2일 어긋나면 진입 시점 1-2일 차이 → 월수익률에 영향

### 6. 2024H2 분기 재무 미사용 확인
- 운영: T6.5 에서 재무 수집 비활성. 그러나 backtest factor_calculator.preload_data 는 여전히 financial_statements 전체 로드 (used 안 됨). 필터링이나 종목 제외에 끼치는지 검증.

## 다음 액션 후보

### 옵션 a: 격차 원인 조사 (권장)
1. sim 과 ours 가 같은 종목을 같은 날에 매수했는지 비교 (10건 샘플)
2. 월별 수익률 시계열 비교 (sim 이력이 있다면)
3. cap_min 통과 universe 비교

### 옵션 b: paper trading 진입 (적극)
- Total return 매칭 = "정해진 종목 픽 능력은 sim 과 동급". Sharpe 격차는 운영 환경 노이즈로 받아들이고 paper trading 으로 실측. 단, 자본 소액 (예: 200만원) 한정.

### 옵션 c: 더 보수적인 대안
- V100 + mom_006676 hybrid (Phase 9 SUCCESS) 로 운영 진입. mom 단독보다 risk-adjusted 지표 우월 확인됨 (sharpe 1.95).

## 메트릭 원본

```json
{
  "sharpe": 1.4473667619582986,
  "total_return_pct": 84.83678098531503,
  "mdd_pct": -20.715857200434137,
  "winning_trades": 60,
  "losing_trades": 56,
  "win_rate": 0.5172413793103449,
  "annualized": 0.44066469974046174,
  "final_value": 18483678.098531503
}
```

재실행: `python scripts/run_mom_backtest.py`
