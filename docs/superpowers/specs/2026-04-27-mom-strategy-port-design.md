---
title: mom_006676 운영 시스템 포팅 설계
date: 2026-04-27
status: draft (pending user review)
scope: V100 운영 시스템 코드를 momentum 전용으로 완전 교체한 워크트리(`RoboTrader_quant_mom`) 구성
worktree: D:\GIT\RoboTrader_quant_mom (branch `mom-strategy`, base `main` @ 9e2968f)
predecessor: docs/superpowers/specs/2026-04-26-phase9-v100-momentum-hybrid-design.md (Phase 9 SUCCESS)
---

# mom_006676 운영 시스템 포팅 설계

## 0. 배경

Phase 9 멀티버스(`RoboTrader_quant_v2/strategy_v2/multiverse_min`)에서 V100(가치) + Momentum 자본 분할 hybrid가 sharpe 1.95 / MDD -9.9% 로 단독 strategy를 모두 우월. 현재 운영(`RoboTrader_quant`, branch `main`)은 V100 단독 1,000만원 실전매매 중. Hybrid 운영 진입 전 momentum 단독 백테스트 + paper trading 검증이 필요.

운영 시스템 코드 점검 결과(2026-04-27):
- V100 하드코딩: `core/quant/factor_calculator.py:299-302` total_score=value_score
- Daily 리밸런싱만 지원 (monthly 미지원)
- cap_min=100억 (mom_006676은 3조 필요)
- TP/SL=12/6 default (mom_006676은 none)
- → 운영 시스템에 strategy 추상화 추가는 큰 리팩토링(~2-3주). 시간 효율 ↓.

대안: 운영 시스템 main을 그대로 유지하고, 신규 워크트리 `RoboTrader_quant_mom`에서 V100 코드를 momentum 전용으로 **완전 교체**. 두 워크트리는 동일 git repo의 별개 브랜치이므로 main의 안전 수정사항을 cherry-pick으로 백포팅 가능.

## 1. 목적

**1차**: 운영 환경 백테스트(2024-07~2026-03)에서 mom_006676이 multiverse_min sim 결과(sharpe 1.76, +78.9%, MDD -16.6%)를 ±10% 이내 재현하는지 확인.

**2차**: 신규 KIS 계좌(자본 TBD, 집에서 결정)에서 paper trading 1-2개월 → 실측 알파 검증.

**3차(향후)**: V100 + mom_006676 hybrid 운영 의사결정.

## 2. 범위

### 2.1 In scope
- `RoboTrader_quant_mom` 워크트리 내부 모든 변경
- V100 코드 → momentum 코드 완전 교체
- 신규 DB(`robotrader_quant_mom`) 분리
- 백테스트 엔진 monthly 리밸런싱 추가
- paper trading 실행 가능한 상태까지 (계좌 정보는 후속 패치)

### 2.2 Out of scope
- 운영 시스템(`main` 브랜치) 수정 — 변경 0건
- Strategy 추상화 레이어 도입 — YAGNI, momentum 단일 운영
- V100/momentum 동시 운영 코드 (한 워크트리 = 한 strategy)
- mom_006676 외 momentum paramset (S-002~S-005 등) — 본 워크트리는 mom_006676 전용
- 자본 분할 hybrid 운영 — 두 워크트리 결합은 후속 spec

## 3. 핵심 결정 사항

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 1 | V100 코드 처리 | 완전 교체 | YAGNI, 워크트리=strategy 1:1 |
| 2 | 검증 순서 | 백테스트 → paper | sim ↔ 운영 격차 사전 발견 |
| 3 | 리밸런싱 | 매월 첫 거래일만 | multiverse_min `MonthlyRebalancer` 동일 |
| 4 | 장중 모니터링 | 비활성화 | `tp_sl_mode=none`, sim 동일성 |
| 5 | DB | `robotrader_quant_mom` 분리 | 운영 V100 데이터 무영향 |
| 6 | 재무 수집 | 비활성화 | momentum은 가격만 사용 |
| 7 | 장전 시장 분석 | 비활성화 | sim 동일성 우선 (regime_filter=off) |
| 8 | cap_min | 3조 runtime 필터 | mom_006676 paramset |
| 9 | 백테스트 검증 | sim 대비 ±10% | 재현 성공 게이트 |
| 10 | paper 자본 | TBD (집에서 결정) | placeholder, 후속 패치 |

## 4. mom_006676 paramset (목표 동작)

multiverse_min `MomentumParamSet`:
```
scorer_type      = "risk_adjusted"   # (price[t-1M] / price[t-12M] - 1) / std_returns
lookback_months  = 12
skip_months      = 1                  # 직전 1개월 제외 (단기 반전 노이즈)
portfolio_size   = 15
rebalance_freq   = "monthly"          # 매월 첫 거래일
weight_scheme    = "equal"
tp_sl_mode       = "none"             # TP=99, SL=99 → 사실상 무한
cap_min          = 3e12               # 3조
regime_filter    = "off"
universe         = "kospi+kosdaq"
```

운영 시 의미:
- 매월 첫 거래일 09:05에 1번만 매매 결정
- 시총 3조 이상 종목만 대상 (~80개 풀)
- risk-adjusted momentum 점수 상위 15개를 동일 가중 매수
- 매수 후 다음 월초까지 보유 (장중 청산 없음)
- 다음 월초 재계산 → 새 Top 15와 교체

## 5. 변경 영역 (high-level)

### 5.1 Scorer 교체 (`core/quant/factor_calculator.py`)

V100 value_score 계산 로직 제거 → momentum risk_adjusted 계산으로 대체.

```
# Before (V100)
total_score = clamp(value_score)   # line 299-302

# After (momentum)
def score(stock_code, asof_date, daily_prices):
    # lookback 12M, skip 1M
    end = asof_date - 1month
    start = asof_date - 12months
    prices = daily_prices[stock_code, start:end]
    ret = prices[-1] / prices[0] - 1
    std = pct_change(prices).std() * sqrt(252)
    return ret / max(std, 1e-6)
```

재무 데이터 수집·캐시 코드 제거.

### 5.2 리밸런싱 트리거 (`main.py` + `core/quant/quant_rebalancing_service.py`)

```
# Before: 매일 09:05 실행
# After:  매월 첫 거래일 09:05에만 실행

if not is_first_trading_day_of_month(today):
    logger.info("Not first trading day. Skipping rebalance.")
    return
```

`is_first_trading_day_of_month()` 신규 함수: KRX 영업일 기준.

### 5.3 장중 모니터링 비활성화 (`core/trading_stock_manager.py`)

3초 루프의 TP/SL 체크 코드 제거 또는 no-op 처리. `target_profit_rate`, `stop_loss_rate` 속성 자체는 보존(DB schema 호환).

### 5.4 cap_min 필터 (`core/candidate_selector.py`)

```
# 기존 MIN_MARKET_CAP=100억 → 3e12 (3조)
candidates = [s for s in all_stocks if s.market_cap >= 3e12]
```

본 spec에서는 단순 상수 변경 (`MIN_MARKET_CAP = 3e12`).

### 5.5 장전 분석 비활성화 (`main.py`, `core/pre_market_analyzer.py`)

08:40 스케줄에서 호출 제거. `pre_market_analyzer.py` 파일 자체는 보존(향후 안전망 도입 옵션).

### 5.6 재무 수집 비활성화 (스케줄러 / 데이터 수집기)

08:30 스케줄에서 재무 수집 호출 제거. 일봉 수집은 유지 (momentum이 사용).

### 5.7 백테스트 엔진 monthly 리밸런싱 (`backtest/backtester.py`)

```
# Before: for date in trading_days: rebalance(date)
# After:
for date in trading_days:
    if is_first_trading_day_of_month(date):
        rebalance(date)
    # 그 외에는 hold (단순 mark-to-market)
```

기타: TP/SL 체크 비활성화, momentum scorer 호출.

### 5.8 DB 분리 (`config/db_config.py`)

```
DB_NAME = "robotrader_quant_mom"   # 기존 robotrader_quant
```

PG에 새 DB 생성 + 기존 schema migration 1회 실행.

기존 V100 운영 DB(`robotrader_quant`)는 무영향.

### 5.9 로그 / PID / 설정 분리

```
robotrader_quant.log → robotrader_quant_mom.log
robotrader_quant.pid → robotrader_quant_mom.pid
```

`config/constants.py`에 `INSTANCE_NAME = "mom"` 추가하여 분기.

## 6. 데이터 흐름

### 6.1 백테스트 (1차 검증)

```
DB(robotrader_quant_mom).daily_prices[2023-07~2026-03]
   ↓
factor_calculator.score_momentum_risk_adjusted(asof, lb=12, skip=1)
   ↓
filter cap_min >= 3e12
   ↓
top 15 by score, equal weight
   ↓
backtester (monthly trigger, no TP/SL)
   ↓
results: sharpe, return, MDD, year split
   ↓
compare to multiverse_min (sharpe 1.76, +78.9%, MDD -16.6%)
   ↓
±10% 이내 → SUCCESS, paper 진입 게이트 통과
```

### 6.2 Paper trading (2차 검증, 계좌 적용 후)

```
매월 첫 거래일 09:05:
  KIS API → 일봉 + 시총 → momentum score 계산
  → top 15 → KIS 매수 주문 (신규 계좌)
  → DB에 real_trading_records로 저장
  → 다음 월초까지 hold (장중 모니터링 없음)
```

## 7. 위험 및 완화책

| 위험 | 영향 | 완화 |
|---|---|---|
| Sim ↔ 운영 sharpe 격차 (V100의 1.42 vs 운영 +241.9% 같은 문제 재현) | 백테스트가 sim과 다르면 paper 의미 ↓ | 1차 게이트(±10%)에서 발견 → 격차 시 데이터 가정 비교 |
| Monthly 첫 거래일 미스 (휴일/임시 휴장) | 한 달 매매 누락 | KRX 영업일 캘린더 정확성 검증, fallback: 다음 영업일 |
| 장중 모니터링 비활성화 후 비상 상황 (코로나급) | -50% 가능성 | paper 자본 소액 한정 (집에서 결정), 수동 개입 가능 |
| 신규 DB 마이그레이션 누락 | 백테스트 실행 불가 | 마이그레이션 스크립트 작성, dry-run 후 적용 |
| KIS API 동시 호출 (V100 + mom 두 계좌) | rate limit 충돌 | 계좌별 rate limit 분리 확인 (집에서 받은 후) |
| 백테스트 monthly 트리거 버그 | 결과 왜곡 | 단위 테스트(첫 거래일 판정) + sim 결과와 trade 일치 검증 |
| Main 브랜치 핫픽스가 mom-strategy에 미반영 | 안전 메커니즘 누락 | 정기 cherry-pick 또는 merge main → mom-strategy |

## 8. 작업 분해 (다음 plan에서 구체화)

| 단계 | 내용 | 추정 |
|---|---|---|
| T1 | DB 분리 + config 변경 + 마이그레이션 | 1h |
| T2 | factor_calculator scorer 교체 (V100 → momentum) | 2h |
| T3 | 리밸런싱 monthly 트리거 (운영 + 백테스트 양쪽) | 2h |
| T4 | 장중 모니터링 / 장전 분석 / 재무 수집 비활성화 | 1h |
| T5 | cap_min 3조, 기타 paramset (port=15, tp_sl=none) | 1h |
| T6 | 백테스트 실행 + sim 대비 ±10% 검증 | 1h |
| T7 | 결과 리포트 작성 | 0.5h |
| **합계** | | **~8.5h** |

paper trading 진입은 T1~T7 완료 + 신규 계좌 정보 수령 후 추가 패치(~1-2h).

## 9. 검증 기준

### 9.1 백테스트 검증 (1차 게이트)

- 기간: 2024-07-01 ~ 2026-03-31 (multiverse_min sim 동일)
- 자본: 1,000만원 고정
- 슬리피지/비용: 0.0025 / 0.00015 / 0.00245 (sim 동일)

| 지표 | sim 목표 | 허용 범위 (±10%) |
|---|---|---|
| Sharpe | 1.76 | 1.58 ~ 1.94 |
| Total return | +78.9% | +71% ~ +87% |
| MDD | -16.6% | -15.0% ~ -18.3% |
| 2024H2 sharpe | -0.37 | -0.41 ~ -0.33 |

위 4 지표 중 3 이상 허용 범위 → SUCCESS, paper 진입.

### 9.2 Paper trading 검증 (2차 게이트, 계좌 후)

- 기간: 1-2개월
- 종목 선정 일치도: sim과 매월 첫 거래일 결정 동일성 확인
- 슬리피지 실측: 0.0025 가정 대비 실제 측정값 비교

## 10. 검증 체크리스트

- [x] A-1, A-2 사전 점검 완료 (2026-04-27)
- [x] mom-strategy 브랜치 + 워크트리 생성 완료 (2026-04-27)
- [x] 핵심 결정 사항 10개 사용자 합의 완료
- [ ] Spec 작성 완료 (이 문서)
- [ ] Spec self-review 통과
- [ ] 사용자 spec 검토 완료
- [ ] Implementation plan 작성 (다음 단계)
- [ ] T1~T7 코드 변경 완료
- [ ] 백테스트 게이트 통과
- [ ] 신규 계좌 정보 수령 (집에서)
- [ ] paper trading 진입
