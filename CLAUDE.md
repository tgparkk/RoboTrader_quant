# RoboTrader 모멘텀 시스템 (mom-strategy 워크트리)

## 시스템 개요

`mom_006676` (risk-adjusted momentum) 전용으로 V100 코드를 완전 교체한 워크트리. 한국투자증권 API 사용 자동매매 시스템.

- **워크트리**: `D:\GIT\RoboTrader_quant_mom`
- **브랜치**: `mom-strategy` (origin/mom-strategy 추적, main 무영향)
- **운영 상태**: T9 백테스트 검증 완료, T10 paper trading 대기 (KIS 신규 계좌 후 진입)

운영 main(`D:\GIT\RoboTrader_quant`, branch `main`, V100) 은 별개 시스템으로 동시 운영 가능. 두 시스템은 별도 PG DB · 별도 KIS 계좌 사용.

## 핵심 동작 흐름

### 1. 매월 첫 거래일 09:05 리밸런싱 (월 1회)

**트리거 위치**: `main.py:512` — `if current_time.hour == 9 and 5 <= current_time.minute <= 30:`
**월간 게이트**: `core/quant/quant_rebalancing_service.py:97-104` — `should_rebalance()` 가 `is_first_trading_day_of_month()` 체크
**캘린더 헬퍼**: `utils/trading_calendar.py:27-39` (`is_first_trading_day_of_month`)

```
매월 첫 거래일 (KRX 공휴일/주말 제외) 09:05~09:30 윈도우에서 1회 실행
→ 현 보유 vs target top-15 비교 → 교체
→ 익월 첫 거래일까지 holding (TP/SL 없음, 포트폴리오 교체로만 청산)
```

### 2. 장중 모니터링 (3초 주기, 체결 확인 전용)

**위치**: `core/trading_stock_manager.py` (`monitor_interval = 3`)
**TP/SL 비활성**: `core/quant/target_profit_loss_calculator.py:78-85` → `return 99.0, 99.0` 고정

```python
# mom-strategy: TP/SL 비활성 (sim tp_sl_mode=none 동일성).
# 99.0 = +9900%/-9900% → 사실상 무한, 장중 트리거 안 됨.
# 청산은 매월 첫 거래일 리밸런싱 시 포트폴리오 교체로만.
return 99.0, 99.0
```

장중 손절/익절 트리거 0건. 3초 루프는 주문 체결 확인용으로만 동작.

### 3. 장전 분석 비활성 (08:40)

**위치**: `main.py:135-144` (`__init__`)

```python
# mom-strategy: 비활성. 09:05 분기에서 fallback evaluate_market_regime() 가
# CRISIS 발동시키지 않도록 __init__ 에서 NORMAL stub 으로 즉시 set.
self._pre_market_result = PreMarketResult(
    regime=MarketRegime.NORMAL,
    reason="mom-strategy: pre-market analysis disabled (sim parity)",
)
```

NewsQuant / yfinance / NXT 호출 0건. sim `regime_filter=off` 동일성 우선.

### 4. 재시작 시 복원

`main.py` 에서 DB(`real_trading_records` / `virtual_trading_records`) 로부터 미체결 포지션 복원. V100 동일 패턴.

## 모멘텀 스코어링

### Risk-Adjusted Momentum (mom_006676 paramset)

**위치**: `core/quant/momentum_scorer.py:25-67`

```
score[t] = (close[t-21] / close[t-273] - 1) / vol_20[t]
vol_20[t] = pct_change(close).rolling(20, min_periods=20).std()[t]   # 비-연환산
```

- lookback = 12개월 (252 영업일)
- skip = 1개월 (21 영업일, 직전 1개월 노이즈 제외)
- vol_20 은 sqrt(252) 곱하지 않음 (multiverse_min canonical 식과 diff=0.00 일치)
- 음수 score 가능 (약세 종목) — clamp 안 함

### 매수 후보 선정 (`core/quant/quant_screening_service.py`)

`min_market_cap = 3_000_000_000_000` (3조원, line 108) + 일평균 거래대금 10억 + 가격 1,000~500,000 + 상장 250 영업일+ → ~80~150 종목 풀 → momentum 점수 내림차순 top **15** 선정.

### 매도/안전 임계값 (모두 비활성)

`core/quant/quant_rebalancing_service.py:51-60`

```python
self.hard_stop_score = float('-inf')  # mom: hard stop 절대 비활성
self.soft_stop_score = float('-inf')  # mom: soft stop 절대 비활성
self.safe_score = float('inf')        # non-target 안전 통과 불가 → 항상 매도
self.safe_rank = 0                    # 안전 순위 통과 불가
self.buy_min_score = 0.0              # top-N 선정으로 충분, 임계값 비활성
```

청산 로직: target top-15 에 없으면 매도. 단순.

## 데이터 저장

- **DB**: `robotrader_quant_mom` (PostgreSQL, port 5433) — V100 의 `robotrader_quant` 와 분리 (`config/db_config.py:8-15`)
- **백테스트 DB**: `robotrader_backtest` (V100 와 공유)
- **일봉**: `daily_prices` 테이블 — 현재 0 rows (운영 진입 시 수집 시작)
- **분봉**: 메모리만
- **현재가**: API 실시간 조회

## 주요 컴포넌트

### mom 신규/대체 파일
- `core/quant/momentum_scorer.py`: 신규 — risk-adjusted momentum
- `core/quant/quant_screening_service.py`: V100 다중 팩터 → momentum 단독 (cap_min 3조)
- `core/quant/target_profit_loss_calculator.py`: 99.0 고정 반환 (TP/SL off)
- `core/quant/quant_rebalancing_service.py`: monthly 트리거 + hard/soft/safe 비활성
- `core/pre_market_analyzer.py`: 호출 코드 제거 (파일 보존, NORMAL stub 사용)
- `utils/trading_calendar.py`: 신규 — `is_first_trading_day_of_month`
- `main.py`: 09:05 monthly trigger, NORMAL stub set
- `scripts/migrate_db_to_mom.py`: 신규 — schema-only 마이그레이션
- `scripts/run_mom_backtest.py` / `scripts/compare_picks_with_sim.py`: T9 검증

### 보존 파일 (V100 패턴 유지)
- `db/database_manager.py`, `api/kis_auth.py` (전역 Rate Limiting), `core/trading_stock_manager.py`, `core/trading_decision_engine.py` 등

## 현재 설정값 (`config/constants.py`)

```python
PORTFOLIO_SIZE = 15                    # mom_006676 paramset (line 6)
QUANT_CANDIDATE_LIMIT = 50
SMART_HARD_CAP_TIERS = [(75.0,5), (72.0,3), (0.0,2)]   # 유지
BUY_RET5D_MIN = None                   # momentum sim 동일성 (line 36)
BUY_SCORE_MOMENTUM_MIN = None          # V100 sm 필터 비활성 (line 44)
```

`backtest/models.py` 의 `slippage_rate = 0.0025` (V100 실측 교정 그대로 채택).

## T9 백테스트 검증 (2026-04-28, commit `33f4332`)

| 지표 | sim | actual (운영 백테스트) | 격차 |
|---|---|---|---|
| Sharpe | 1.76 | 2.34 | +33% (운빨 추정) |
| Total return | +78.9% | +125.2% | +59% (운빨 추정) |
| MDD | -16.6% | -15.1% | -9% (개선) |

- 기간: 2024-07-01 ~ 2026-02-28 (1천만원 자본, slippage 0.0025)
- **픽 일치도 8건 평균 85.7%** — strategy 본질 sim 동급
- +49pp outperform 은 1-4 다른 픽이 우연히 winner 가 된 누적 효과 → **운영 기대값으로 사용 금지**, sim 메트릭 (sharpe 1.76, +78.9%) 기준
- 캘린더 12건 누락 fix 동시 수행 (`utils/korean_holidays.py`)
- 상세: `docs/superpowers/reports/2026-04-28-mom-strategy-backtest-result.md`

## T10 paper trading 대기 (Pending)

사전 조건:
1. KIS 신규 계좌 (V100 main 별개)
2. `config/key.ini` 작성
3. 자본 결정 (집에서, 권장 2-3M₩ 또는 그 이상)

진입 후 즉시 검증 (첫 매월 첫 거래일 매매 후):
- [ ] 픽 일치도 ≥80% vs sim panel top-15
- [ ] 슬리피지 ±0.5% (가정 0.25%)
- [ ] 텔레그램 알림 도착
- [ ] DB `real_trading_records` 15건 buy 레코드

상세: `docs/superpowers/reports/2026-04-28-mom-strategy-paper-trading-guide.md`

## 자동 스케줄

- **08:30**: 일봉 + 보유종목 데이터 수집 (재무 비활성, momentum 은 가격만 사용)
- **08:40**: 장전 분석 — **비활성** (NORMAL stub)
- **09:05~09:30**: 매월 첫 거래일에만 리밸런싱 (그 외 일은 skip)
- **15:35**: 일봉 수집 → 모멘텀 스코어 계산 → 일일 리포트

## 실행

```bash
cd D:\GIT\RoboTrader_quant_mom
python main.py
```

## ⚠️ 미진행 / 미해결 (paper trading 진입 전 반드시 검토)

### P0 — 운영 진입 전 필수 fix

- **`main.py:131` MONTHLY 강제 오버라이드 의심**:
  ```python
  self.rebalancing_service.rebalancing_period = RebalancingPeriod.DAILY  # 일간 리밸런싱
  ```
  `quant_rebalancing_service.py:40` 의 기본값 `RebalancingPeriod.MONTHLY` 를 `DAILY` 로 덮어씀. V100 main.py 의 잔존 코드로 추정. 이 상태에서 실 운영 시 매일 전 포트폴리오 교체 발생 (hard_stop=-inf + safe_score=+inf 조합으로 non-target 종목 항상 매도) → 막대한 회전·슬리피지·비용. **paper trading 진입 전 line 131 삭제 또는 `MONTHLY` 로 교체 필요**. T9 백테스트는 별도 `backtest/backtester.py` 경로라 영향 없었음.

### 그 외 잔여

- **T10 paper trading**: KIS 신규 계좌 대기
- **M-1**: `config/constants.py` 주석 보강 (영향 미미)
- **M-4**: regression 테스트 추가 (영향 미미)
- **캘린더 12건 fix V100 main 백포팅**: 권장 (선택, V100 NewsQuant/장전분석 안정성)
- **T9.5 (선택)**: sim ↔ ops +49pp 격차 정밀 조사 (universe/체결 비교, 2-3h)

## 참고 문서

- 설계: `docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md`
- 구현 plan (T1~T10): `docs/superpowers/plans/2026-04-27-mom-strategy-port-implementation.md`
- T9 백테스트 결과: `docs/superpowers/reports/2026-04-28-mom-strategy-backtest-result.md`
- T10 paper 진입 가이드: `docs/superpowers/reports/2026-04-28-mom-strategy-paper-trading-guide.md`

## 코드 검토 시 주의사항

V100 동일 원칙 (함수 전체 / Lock / 호출 함수 / 전역 인프라 / SQL 의미 / 설계 의도 확인) 에 더해 mom 특이 사항:

- **`return 99.0, 99.0` 은 의도된 비활성**, TP/SL bug 아님 (sim 동일성)
- **`hard_stop_score = -inf` 와 `safe_score = +inf` 는 의도**, 매도 임계값 무력화 + 매월 교체로 청산
- **`pre_market_analyzer.analyze()` 호출 0건 = 의도**, NORMAL stub 으로 우회
- **`buy_min_score = 0.0` 은 비활성 마커**, top-N 랭크 선정만 사용
- **백테스트 (`backtest/backtester.py`) 와 운영 (`main.py` + `quant_rebalancing_service`) 은 별개 경로** — 한 쪽만 보고 동작 추론 금지
