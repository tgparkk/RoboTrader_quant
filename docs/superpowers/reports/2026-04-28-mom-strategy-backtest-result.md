---
title: mom_006676 운영 백테스트 결과 (T9 + 격차 조사)
date: 2026-04-28
status: 1/3 게이트 (MDD 일치, Sharpe/Return outperform 미해명)
spec: docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md
plan: docs/superpowers/plans/2026-04-27-mom-strategy-port-implementation.md
correction: 라운드 3 의 "look-ahead 수정"은 over-fix 였음 (revert)
---

# mom_006676 운영 백테스트 결과

## 실행 환경

- **기간**: 2024-07-01 ~ 2026-02-28 (sim equity_dates 정렬, 401일)
- **자본**: 1,000만원
- **비용**: slippage 0.0025 / buy 0.00015 / sell 0.00245
- **DB**: `robotrader_backtest` (sim multiverse_min 도 동일 DB 사용 확인)
- **Universe**: cap≥3조 → 112-158 종목/일
- **Paramset**: T8.4 BacktestParams 기본값 (TP/SL 99.0, port=15, hard/soft/safe 비활성)
- **Scoring**: raw risk-adjusted momentum (clamp 없음)

## ⚠️ 라운드 3 정정 사항

라운드 3 에서 "look-ahead 1일 발견" 으로 `factor_calculator.py:245` `<= calc_date` → `< calc_date` 수정했으나 **잘못된 진단이었음**. 이유:

- `backtester.py:218-251` 에 이미 `_get_prev_calc_date()` + `_get_factors()` 메커니즘이 존재
- 거래일 D 의 의사결정에 `calc_date = D-1` 의 factor 만 사용 (line 247 명시 주석)
- → factor_calculator 가 `<= calc_date` 로 X 종가까지 써도 백테스트 실효 의사결정은 D-1 종가 기준 = look-ahead 없음
- 잘못된 fix 는 실효 lag 를 D-2 로 미루어 mom 알파 약화 → 우연히 sim 메트릭에 가까워 보였을 뿐

revert 후 결과는 라운드 2 와 동일 (정확한 mom 운영 backtest).

## 최종 결과 (라운드 2 = revert 후)

| 지표 | sim | actual | gate |
|---|---|---|---|
| Sharpe | 1.76 | 2.34 | FAIL +33% (높음) |
| Total return | +78.9% | +125.2% | FAIL +59% (높음) |
| MDD | -16.6% | -15.1% | OK (격차 -9%) |

equity overlay (라운드 2):
| date | sim% | ours% | gap pp |
|---|---|---|---|
| 2024-09-30 | -5.67 | -2.44 | +3.23 |
| 2024-12-30 | -5.75 | -7.39 | -1.64 |
| 2025-03-31 | +1.53 | +3.01 | +1.48 |
| 2025-06-30 | +21.16 | +34.00 | +12.83 |
| 2025-09-30 | +30.97 | +45.30 | +14.34 |
| 2025-12-30 | +47.80 | +75.91 | +28.11 |
| 2026-02-25 | +78.91 | +127.62 | **+48.71** |

처음 9개월 (2024-07~2025-03) ±5pp 안정 추적, 2025-Q2 부터 단조 outperform 발산.

## Verdict

**실측 outperform 미해명 — paper trading 진입 신중**.

✅ **확인된 사실**:
- MDD 일치 (위험 프로파일 sim 동급 — 약간 낮음)
- Look-ahead bias 없음 (V100 main 도 우리도 `_get_prev_calc_date` 보호)
- 같은 DB, 같은 cap_min, 같은 universe (112-158 종목/일)

❌ **미해명**:
- 2025-Q2~ +49pp 누적 outperform — 같은 universe 인데 픽이 갈림
- 가능 원인:
  1. **vol_20 NaN 처리 미세 차이** (sim `pct_change(fill_method=None)` vs ours default)
  2. **equal-weight 정수 매수 rounding** (sim 도 동일 가정인지 미확인)
  3. **monthly 첫 거래일 정의** (sim panel index 의 trading_days vs ours korean_holidays)
  4. **factor_calculator 의 추가 필터** (MIN_PRICE / MIN_AVG_TRADING_VALUE 등 sim 에는 없을 수도)

## Paper trading 권고

**현재 정지** — sim 보다 +49pp outperform 은 운영에서 재현되지 않을 가능성이 큼 (sim 만의 보수성이 실은 정확하고 우리가 우연히 운 좋은 픽들을 잡고 있을 수 있음).

대안:
- (a) **격차 원인 조사 우선** — 같은 calc_date 에서 우리 top-15 vs sim mom_rskip_12_1 top-15 set diff (10개 월 샘플)
- (b) **V100 + mom_006676 hybrid** (Phase 9 SUCCESS sharpe 1.95) 직접 진입 — mom 단독 outperform 의 불확실성 회피

## 메트릭 원본

```json
{
  "sharpe": 2.344581970561674,
  "total_return_pct": 125.21660743531511,
  "mdd_pct": -15.129921011608985,
  "winning_trades": 66,
  "losing_trades": 50,
  "win_rate": 0.5689655172413793,
  "annualized": 0.6614398579296434,
  "final_value": 22521660.74353151,
  "trade_count": 116
}
```

재실행: `python scripts/run_mom_backtest.py --start 2024-07-01 --end 2026-02-28`
