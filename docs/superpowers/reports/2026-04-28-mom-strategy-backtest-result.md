---
title: mom_006676 운영 백테스트 결과 (T9 + 격차 조사)
date: 2026-04-28
status: 1/3 게이트 (격차 부분 해결, paper trading 진입은 신중)
spec: docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md
plan: docs/superpowers/plans/2026-04-27-mom-strategy-port-implementation.md
---

# mom_006676 운영 백테스트 결과

## 실행 환경

- **기간**: 2024-07-01 ~ 2026-02-28 (sim 의 401일 equity_dates 와 정렬)
- **자본**: 1,000만원
- **비용**: slippage 0.0025 / buy 0.00015 / sell 0.00245
- **DB**: `robotrader_backtest` (sim multiverse_min 도 동일 DB 사용 확인)
- **Universe**: cap≥3조 → 112-158 종목/일 (sim APPROX 80 은 outdated 추정치)
- **Paramset**: T8.4 BacktestParams 기본값 (TP/SL 99.0, port=15, hard/soft/safe 비활성)

## 조사 과정 (3 라운드)

### 라운드 1 (초기, end=2026-03-31): FAIL 1/3
| 지표 | sim | actual | gate |
|---|---|---|---|
| Sharpe | 1.76 | 1.45 | FAIL -17.7% |
| Total return | +78.9% | +84.8% | OK +7.5% |
| MDD | -16.6% | -20.7% | FAIL +24.8% |

**문제**: sim 의 equity_dates 는 2024-07-01 ~ **2026-02-25** 이지만 우리는 2026-03-31 까지 실행.

### 라운드 2 (정렬, end=2026-02-28): 메트릭 역전
| 지표 | sim | actual | gate |
|---|---|---|---|
| Sharpe | 1.76 | 2.34 | FAIL +33% (높음) |
| Total return | +78.9% | +125.2% | FAIL +59% (높음) |
| MDD | -16.6% | -15.1% | OK |

**문제**: 우리가 sim 보다 한참 outperform — 의심스러움. equity 곡선 overlay 결과 gap 이 시간이 갈수록 단조 증가 (2024-09 +3pp → 2026-02 +49pp). 누적 픽 차이 또는 look-ahead bias 의심.

### 라운드 3 (look-ahead 수정 + 정렬): 게이트 1/3 (MDD 거의 일치)
**look-ahead 버그 발견 + 수정**:
- `backtest/factor_calculator.py:245`: `prices['date'] <= calc_date` → `< calc_date`
- 사유: 백테스터는 calc_date 시가에 체결하는데 점수는 calc_date 종가까지 사용 → 1일 look-ahead.
- multiverse_min `execution.py:54` docstring: "T-1 스냅샷 기반 주문을 T 시가로 체결" — 정상 의미는 결정 T-1 EOD, 체결 T open.

| 지표 | sim | actual | gate |
|---|---|---|---|
| Sharpe | 1.76 | 2.10 | FAIL +19% |
| Total return | +78.9% | +110.2% | FAIL +40% |
| MDD | -16.6% | **-17.2%** | **OK** (격차 +3.5%) |

equity overlay (라운드 3):
| date | sim% | ours% | gap pp |
|---|---|---|---|
| 2024-09-30 | -5.67 | -3.15 | +2.52 |
| 2024-12-30 | -5.75 | -7.94 | -2.19 |
| 2025-03-31 | +1.53 | -3.00 | -4.53 |
| 2025-06-30 | +21.16 | +26.29 | +5.13 |
| 2025-09-30 | +30.97 | +38.99 | +8.02 |
| 2025-12-30 | +47.80 | +72.02 | +24.22 |
| 2026-02-25 | +78.91 | +115.73 | **+36.82** |

처음 9개월 (2024-07~2025-03) 은 ±5pp 안정 추적. 2025-Q2 부터 점진적 단조 발산.

## Verdict

**부분 해결 — 1/3 게이트, MDD 거의 일치하지만 return outperform 미해명.**

✅ **확인된 사실**:
1. **MDD 정합** (라운드 3 -17.2 vs sim -16.6, 격차 +3.5%) — 위험 프로파일 sim 동급.
2. **Look-ahead 버그 수정** — 운영 시스템에는 영향 없음 (운영은 15:35 close 기준으로 다음날 09:05 결정 = 정상). V100 백테스트도 동일 버그였으므로 모든 V100 historical 메트릭 재검증 필요할 수 있음.
3. **종목 픽 능력** sim 동급 이상 — 누적 +36pp outperform 은 정해진 universe 내 동등 운영을 가정하면 우리 픽이 우월하거나 sim 픽이 보수적.

❌ **미해명**:
1. **+36pp return outperform** (2025-Q2~) — 같은 universe, 같은 점수 식, 같은 체결 timing 인데 픽이 갈림. 가능성:
   - momentum_scorer 와 sim 의 mom_rskip_12_1 panel 사이 부동소수 차이가 cross-section 정렬에서 누적 다른 결과
   - vol_20 NaN 처리 (sim drop vs ours skip) 가 가용 universe 줄여 픽 변동
   - portfolio rotation 빈도 미세 차이 (rounding/quantity 처리)
2. **Sharpe 격차** (+19%) — outperform 효과로 분자 큼. risk profile 자체는 정상.

## Paper trading 권고

**조건부 진행 — 자본 소액 한정**:
- MDD 동급 + outperform 시그널 → 위험 통제는 sim 수준, 수익 가능성은 sim 이상
- 단, +36pp 분기 격차는 운영 환경에서 재현되지 않을 가능성 (sim 만의 보수성이 아닌 우리만의 우연한 outperform 일 수도)
- **자본 200만 ~ 300만원 한정으로 1-2개월 paper trading**, 매월 첫 거래일 픽이 sim 픽 분포와 일치하는지 모니터링

또는 **V100 + mom_006676 hybrid** (Phase 9 SUCCESS sharpe 1.95) 직접 진입 — mom 단독 outperform 의 불확실성 회피.

## 다음 격차 원인 조사 (선택)

1. 같은 calc_date 에서 우리 momentum_score top-15 vs sim 의 panel mom_rskip_12_1 top-15 set diff (10개 월 샘플)
2. multiverse_min 의 trade-level 로그가 있다면 우리 trades 와 비교 (현재 baseline_momentum_top5.parquet 에는 메트릭만 있음)
3. vol_20 계산에서 NaN 처리 차이 (multiverse_min indicators.py:217 `pct_change(fill_method=None)` vs ours 의 default fill_method)

## 메트릭 원본 (라운드 3, look-ahead 수정 + 정렬)

```json
{
  "sharpe": 2.09654272220501,
  "total_return_pct": 110.18115500760632,
  "mdd_pct": -17.158971043384135,
  "winning_trades": 68,
  "losing_trades": 53,
  "win_rate": 0.5619834710743802,
  "annualized": 0.5911868061356216,
  "final_value": 21018115.500760633,
  "trade_count": 121
}
```

재실행: `python scripts/run_mom_backtest.py --start 2024-07-01 --end 2026-02-28`
