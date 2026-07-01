# 주간 리밸런싱 타당성 검증 보고서

- **작성일**: 2026-05-08
- **워크트리**: `D:\GIT\RoboTrader_quant_mom` (branch `mom-strategy`)
- **데이터**: `D:\GIT\RoboTrader_quant_v2\strategy_v2\multiverse_min\results\phase1_momentum\phase1_momentum_full.parquet` (10,944 행 × 48 컬럼, valid 7,488)
- **검증 도구**: pandas/parquet 직접 분석 (python_repl)
- **계기**: 사용자 운영 가설 호기심 — "현재 mom-strategy 의 매월 1회 리밸런싱을 매주 1회로 바꾸면 더 좋을지" 정량 검증

---

## Executive Summary

**결론: monthly 가 5 freq 중 sharpe 1위. weekly/biweekly/semimonthly/quarterly 모두 열위. 운영 도입 비추천.**

- mom_006676 paramset 고정 + 5 freq 직접 비교 (monthly 1.759 / semimonthly 1.509 / biweekly 1.367 / weekly 1.340 / quarterly 1.247)
- Phase 1 전체 분포 통계도 monthly 우위 (평균 sharpe -0.019 vs weekly -0.273)
- Weekly winner 후보 (`mom_007780` 등) 도 2024H2 음수 sharpe (top-30 중 28건) → **Phase 5.7 와 같은 overfitting 패턴**
- 거래비용 sim 에 이미 반영 — sharpe 차이가 곧 비용 + 변동성 패널티

---

## 0. 5-freq mini-run (격주/월 2회 추가, 사용자 follow-up)

multiverse_min Phase 1 에는 weekly/monthly/quarterly 만 존재 → 격주(biweekly) / 월 2회(semimonthly) Rebalancer 신규 추가 후 mom_006676 paramset 고정으로 5 freq 직접 비교.

### 신규 Rebalancer 정의 (`strategy_v2/multiverse_min/modules/rebalancer.py`)

| 클래스 | 정의 |
|---|---|
| `BiWeeklyRebalancer` | 주 첫 거래일 AND ISO week % 2 == 0 (격주, 짝수 ISO 주 월요일) |
| `SemiMonthlyRebalancer` | 월 첫 거래일 OR (이전 거래일 day < 15 AND as_of day ≥ 15) |

엔진 변경: `modules/__init__.py` rebalancers dict 에 `biweekly` / `semimonthly` 추가. paramspace REBAL_CHOICES 는 미변경 (mini-run 은 ParamSet 직접 생성).

### 5 freq 비교 결과 (n=5, 단일 paramset)

실행: `python -m strategy_v2.multiverse_min.bench.freq_grid_mom006676` (~30초)
결과: `strategy_v2/multiverse_min/results/freq_grid_mom006676/freq_grid.parquet`

| freq | sharpe | return | MDD | win | trades | min_year_sharpe | 2024H2 sharpe | 2024H2 ret | 2025 sharpe | 2025 ret | 2026Q1 sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **monthly** ★ | **1.759** | +78.91% | **-16.63%** | **57.4%** | **101** | **-0.366** | -0.366 | -5.75% | 2.375 | +54.83% | 5.364 |
| semimonthly | 1.509 | **+83.05%** | -22.31% | 52.7% | 146 | -1.005 | -1.005 | -14.53% | 2.042 | +61.60% | 5.518 |
| biweekly | 1.367 | +64.70% | -18.18% | 52.5% | 160 | -0.605 | -0.605 | -9.40% | 1.897 | +50.15% | 5.052 |
| weekly | 1.340 | +75.63% | -26.12% | 50.0% | 230 | -1.166 | -1.166 | -19.76% | 2.363 | +76.43% | 4.331 |
| quarterly | 1.247 | +53.08% | -19.13% | 52.5% | 40 | -0.479 | -0.479 | -7.63% | 1.741 | +42.11% | 5.100 |

### 핵심 관찰

1. **Sharpe 순위**: monthly > semimonthly > biweekly > weekly > quarterly. **U-자 곡선 아님 — monthly 가 명확한 최적점**
2. **semimonthly return +83% 가 monthly +78.9% 보다 +4.1pp 높음** — 단 MDD -22.3% (+5.7pp 악화), win 52.7% (-4.7pp), sharpe -0.25 → **risk-adjusted 기준 monthly 우위**
3. **biweekly 가 weekly 보다 sharpe 약간 우위** (1.367 vs 1.340), MDD 도 개선 (-18.2 vs -26.1) → 더 자주 ≠ 더 좋음. 단 monthly 보다는 여전히 열위
4. **모든 freq 의 2024H2 sharpe 음수** → mom_006676 paramset 자체가 2025/2026Q1 강세 의존. 주기 변경으로 해소 안 됨
5. **거래수**: weekly 230 ≫ biweekly 160 ≈ semimonthly 146 > monthly 101 ≫ quarterly 40

### 시사점

- **freq 만 바꿔서는 monthly 를 능가 불가** (5 freq 중 1위 = monthly)
- semimonthly return alpha (+4.1pp) 는 변동성 페널티로 상쇄 — sharpe 기준 비추천
- 격주 / 월 2회도 monthly 에 비해 명확한 우위 없음 → **운영 monthly 그대로 유지**

---

## 1. mom_006676 동일 paramset 비교

`p_lookback_months=12, p_skip_months=1, p_portfolio_size=15, p_cap_min=3조, p_scorer_type=risk_adjusted, p_tp_sl_mode=none, p_regime_filter_type=off, p_weight_scheme=equal` 의 rebalance_freq 만 다른 3행:

| run_id | freq | sharpe | return | MDD | win | trades | min_year | 2024H2 sharpe | 2024H2 ret | 2025 sharpe | 2025 ret | 2026Q1 sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **mom_006676** | **monthly** | **1.759** | **+78.91%** | **-16.63%** | **57.4%** | **101** | **-0.366** | -0.366 | -5.75% | 2.375 | +54.83% | 5.364 |
| mom_006628 | weekly | 1.340 | +75.63% | -26.12% | 50.0% | 230 | -1.166 | -1.166 | -19.76% | 2.363 | +76.43% | 4.331 |
| mom_006724 | quarterly | 1.247 | +53.08% | -19.13% | 52.5% | 40 | -0.479 | -0.479 | -7.63% | 1.741 | +42.11% | 5.100 |

**Δ (weekly vs monthly)**:
- sharpe: -0.42 (-24%)
- return: -3.3pp (-4%)
- MDD: -9.5pp (악화)
- winrate: -7.4pp
- trades: +128% (101 → 230)
- min_year_sharpe: -0.80 (2024H2 더 깊게 무너짐)

> 이전 Explore agent 가 보고한 "weekly sharpe 1.18 / +66.2% / MDD -22.9%" 는 잘못된 추출. 정확값은 위 표.

---

## 2. Weekly subset 분포 통계 (n=2,496)

| 지표 | weekly | monthly | quarterly |
|---|---|---|---|
| sharpe (mean) | **-0.273** | -0.019 | -0.116 |
| sharpe (median) | -0.315 | -0.068 | -0.087 |
| sharpe (90th%) | 0.620 | **0.884** | 0.656 |
| total_return (mean) | -6.4% | +4.0% | +3.0% |
| MDD (mean) | -28.6% | -16.9% | -14.1% |
| trade_count (mean) | 448 | 150 | 55 |
| winrate (mean) | 0.379 | 0.386 | 0.352 |

**모든 분포 지표에서 monthly 가 우위.** Weekly 의 90th percentile 조차 monthly 의 90th percentile 보다 낮음.

---

## 3. Weekly Top-10 paramset (sharpe 내림차순)

| Rank | run_id | sharpe | return | MDD | min_year | trades | lookback | port | scorer |
|---|---|---|---|---|---|---|---|---|---|
| 1 | mom_007780 | 1.803 | +138.4% | -25.0% | -0.470 | 219 | 6 | 15 | residual |
| 2 | mom_000868 | 1.803 | +138.4% | -25.0% | -0.470 | 219 | 6 | 15 | total_return |
| 3 | mom_004468 | 1.796 | +81.4% | -15.5% | -0.058 | 365 | 6 | 20 | risk_adjusted |
| 4 | mom_000892 | 1.782 | +141.4% | -23.9% | -0.037 | 208 | 6 | 15 | total_return |
| 5 | mom_007804 | 1.764 | +139.2% | -24.5% | -0.046 | 207 | 6 | 15 | residual |
| 6 | mom_005620 | 1.709 | +81.6% | -16.6% | -0.512 | 316 | 9 | 20 | risk_adjusted |
| 7 | mom_004492 | 1.703 | +80.9% | -16.9% | -0.091 | 363 | 6 | 20 | risk_adjusted |
| 8 | mom_003316 | 1.624 | +103.7% | -20.4% | -0.615 | 174 | 12 | 20 | total_return |
| 9 | mom_010228 | 1.624 | +103.7% | -20.4% | -0.615 | 174 | 12 | 20 | residual |
| 10 | mom_007948 | 1.576 | +102.8% | -21.6% | -0.245 | 258 | 6 | 20 | residual |

**관찰**:
1. **모든 top-10 의 min_year_sharpe < 0** — 어느 한 연도에서 음수 sharpe 발생, 즉 일관된 alpha 가 없음
2. 8/10 이 lookback=6 (mom_006676 의 12 와 다른 paramset). 짧은 lookback 일수록 weekly 와 잘 맞으나 노이즈 큼
3. portfolio_size 모두 15 또는 20, cap_min=3조, skip=1, tp_sl=none, regime=off 일관

---

## 4. 일반화 검증 — 2024H2 편중 (Overfitting 진단)

| 검증 항목 | weekly | monthly |
|---|---|---|
| valid n | 2,496 | 2,496 |
| 모든 연도 양수 sharpe | **7건 (0.28%)** | **13건 (0.52%)** |
| top-30 중 2024H2 양수 sharpe | **2/30 (6.7%)** | (해당 분석 별도) |
| top-30 평균 sharpe_2024H2 | **-0.507** | (해당 분석 별도) |

**Phase 1 Momentum 메모리** (`phase1_momentum_20260424.md`) 의 "2024H2 편중 경고" 가 weekly 에서도 동일하게 관찰됨. Top-30 weekly 후보의 28/30 이 2024H2 음수 sharpe → **2025/2026Q1 강세 기간 편중 winner**.

**Phase 5.7 사고와 동일 패턴**: `phase5_7_success_20260426.md` — robust_final 38건 도출 후 일반화 검증에서 39 underlying 중 1개만 양수 (-0.566 평균). 본 weekly winner 도 같은 운명 가능성 높음.

---

## 5. 거래비용 정량 (자본 1,000만원, 15 슬롯, sim 가정)

`p_buy_fee=0.00015 + p_sell_fee=0.00245 + 2 × p_slippage_rate=0.0025 = round-trip 0.760%`

| paramset | trades | trades/yr | 연 비용 (원) | 자본 대비 |
|---|---|---|---|---|
| monthly mom_006676 | 101 | 57.7 | 292,419 | 2.92% |
| weekly mom_006628 (동일) | 230 | 131.4 | 665,905 | **6.66%** |
| weekly top mom_007780 | 219 | 125.1 | 634,057 | **6.34%** |

**중요**: 이 비용은 sim sharpe/return 에 **이미 반영됨**. 즉 위 sharpe 1.34 vs 1.76 격차가 곧 비용 + 변동성 패널티의 합산 결과. 별도 비용 추가 차감 불필요.

---

## 6. 의사결정 옵션

### 옵션 A: monthly 유지 (★ 추천)

근거: sim 정량 모든 지표에서 monthly 우위. T9 백테스트 (sharpe 1.76, +78.9% / 21개월) 검증 완료. 코드 변경 0건, 운영 리스크 0.

### 옵션 B: weekly 전용 paramset 도입 (mom_007780 등)

조건: 일반화 검증 통과 시. 단 본 데이터에서 일반화 통과 가능성 낮음:
- top-30 중 28/30 이 2024H2 음수 sharpe → **거의 확실한 overfitting 신호**
- Phase 5.7 (regime 통합) 도 같은 패턴으로 39 robust 중 1건만 일반화 → 폐기

**진행 시 추가 작업**:
1. 신규 multiverse_min run — 다른 시작 기간 (2023~2024H1) 으로 walk-forward
2. paper trading 1~3개월 (별도 KIS 계좌, 자본 ≤ 200만원)
3. 본 paramset 은 mom_006676 와 다른 lookback (=6) 이라 모멘텀 score 정의 자체 변경 — `core/quant/momentum_scorer.py:25-67` 의 lookback_months 기본값 변경 필요

### 옵션 C: 격주 (bi-weekly) / 월 2회 절충안

근거: weekly 비용 + monthly alpha 사이 절충. 단 multiverse_min sim 에 격주 데이터 없음 → **신규 sim run 필요** (`D:\GIT\RoboTrader_quant_v2` 워크트리 작업).

선험적 추정: monthly (29만원/년) ↔ weekly (66만원/년) 사이 ~50만원/년. sharpe 격차도 비례할 가능성 높음. 가치 대비 비용 큼.

---

## 7. 권고 액션

1. **monthly 유지** (현재 운영 그대로)
2. 본 보고서를 `mom_strategy_worktree_20260427` / `phase9_v100_momentum_hybrid_20260426` 메모리와 함께 향후 weekly 논의 발생 시 재인용
3. (선택) 격주 sim run 호기심 남으면 별도 작업으로 신규 multiverse_min phase (예: phase 11 — rebalance_period grid) 추가 후 30 분 분석

---

## 부록: 분석 코드

```python
import pandas as pd
P = r"D:\GIT\RoboTrader_quant_v2\strategy_v2\multiverse_min\results\phase1_momentum\phase1_momentum_full.parquet"
df = pd.read_parquet(P)
v = df[df['valid'] == True]

# mom_006676 와 동일 paramset 의 freq 별 비교
mask = (
    (df['p_lookback_months'] == 12) & (df['p_skip_months'] == 1) &
    (df['p_portfolio_size'] == 15) & (df['p_cap_min'] == 3e12) &
    (df['p_scorer_type'] == 'risk_adjusted') & (df['p_tp_sl_mode'] == 'none') &
    (df['p_regime_filter_type'] == 'off') & (df['p_weight_scheme'] == 'equal')
)
df[mask][['run_id','p_rebalance_freq','sharpe','total_return_pct','mdd_pct','min_year_sharpe']]

# Weekly top-10
w = v[v['p_rebalance_freq'] == 'weekly']
w.sort_values('sharpe', ascending=False).head(10)

# 모든 연도 양수 sharpe 카운트
((w['sharpe_2024H2'] > 0) & (w['sharpe_2025'] > 0) & (w['sharpe_2026Q1'] > 0)).sum()  # 7
```
