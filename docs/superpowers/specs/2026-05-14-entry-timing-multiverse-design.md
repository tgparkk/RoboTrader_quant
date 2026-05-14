# 진입시점 멀티버스 설계 (Entry Timing Multiverse)

- 작성일: 2026-05-14
- 작성자: sttgpark
- 상태: 설계 승인 대기 → 사용자 리뷰 → writing-plans 인계

---

## 1. 목적

현행 운영(`D+1 09:05` 매수)이 일중 진입 시각·T+N 지연 축에서 최적인지를 14개월 백테스트로 검증하고, 더 나은 조합이 있다면 운영 적용 후보 1~3개를 제시한다.

장 운영(`main.py`)에 영향을 주지 않도록 별도 워크트리에서 DB 읽기 전용으로 수행한다.

## 2. 범위

### A축 — 일중 진입 시각 (7 버킷)

| 시각 코드 | 시각 | 가격 컨벤션 |
|----------|------|------------|
| `090000` | 09:00 | 분봉 **open** (= 일봉 시가) |
| `090500` | 09:05 | 분봉 close |
| `091500` | 09:15 | 분봉 close |
| `093000` | 09:30 | 분봉 close |
| `100000` | 10:00 | 분봉 close |
| `110000` | 11:00 | 분봉 close |
| `145000` | 14:50 | 분봉 close |

### B축 — 신호 후 진입 지연 (4 버킷)

`D` = 신호일 (장마감 15:35 스크리닝 시점).

- `D+1` (현행 운영 기준)
- `D+2`
- `D+3`
- `D+5`

D+N이 휴장이면 다음 영업일로 시프트.

### 총 조합: 7 × 4 = **28**

### 기간

- 분봉 데이터 가용 범위: `2025-02-24 ~ 2026-05-13` (~300영업일)
- 리포트는 시대별 분할:
  - **Hybrid 시대**: 2025-02-24 ~ 2026-04-13 (~278영업일, 표본 충분)
  - **V100 시대**: 2026-04-14 ~ 2026-05-13 (~22영업일, 표본 적음 — 추세만 참고)

## 3. 운영 격리

- 신규 워크트리: `D:\GIT\RoboTrader_quant_entry`, branch `entry-timing-multiverse` (main 분기)
- 운영 repo 무수정, KIS API 호출 0회
- DB는 SELECT만:
  - `robotrader.minute_candles` (분봉)
  - `robotrader_quant.quant_portfolio` (D-day 신호)
  - `robotrader_quant.daily_prices` (TP/SL용 일봉 OHLC)
  - `robotrader_quant.quant_factors` (리밸런싱·매수 게이트 점수)
- 결과는 워크트리 내 `results/entry_timing_multiverse_YYYYMMDD.parquet` (DuckDB 미사용)

## 4. 신호 소스·매수 종목 결정

**원칙**: 우리가 평가하는 건 "이미 선정된 종목을 언제 사야 유리한가"이지 "어떤 종목을 사야 하나"가 아니다. 시그널 시스템(Hybrid/V100)이 그날 무엇을 골랐든 그 리스트 위에서 진입 시점만 바꿔 비교한다.

### 처리 로직

1. 각 D(영업일)에 대해 `quant_portfolio`에서 그날 저장된 상위 N종목 조회 (운영 `PORTFOLIO_SIZE=10` 일치)
   - Hybrid 시대(~04-13): hybrid_score 상위 10
   - V100 시대(04-14~): value_score 상위 10
   - 즉 "시대 구분에 무신경하게 그날 quant_portfolio에 들어있던 종목"만 신뢰
2. 시그널 종목 X를 `D+N` 영업일 시각 hh:mm에 매수 시도
   - D+N이 휴장: 다음 영업일로 시프트
   - 해당 분봉 누락: 그 종목 그날 매수 실패(skip), 로그 기록
3. 매수 후 보유는 **현행 운영 로직 그대로**:
   - TP 12% / SL 6%
   - 리밸런싱 3단계(hard_stop 65 / soft_stop 67 / safe 75)
   - 매수 게이트(BUY_RET5D_MIN/MAX, BUY_RET20D_MAX, BUY_MOMENTUM_SCORE_MIN)도 동일
   - 매수 게이트는 **D+N 시점의** ret_5d/20d/momentum_score로 재평가 (시그널 D 시점이 아님 — 진입 직전 가격이 기준이 맞다)

> ⚠️ Note: 백테스트는 cache 기반이라 운영의 silent-fail(2026-03-27~05-10) 이슈와 무관. 백테스트에서는 게이트가 시점 무관하게 정상 작동한다고 가정.

## 5. 백테스터 변경 지점

운영 `backtest/backtester.py`를 워크트리에서 fork → `backtest/entry_timing_backtester.py` 신규 파일.

### 변경 (2곳)

**1. 매수 가격 함수 교체**

```python
def get_entry_price(stock_code, signal_date, delay_days, entry_time, slippage_rate):
    entry_date = next_business_day(signal_date, delay_days)
    bar = query_minute_bar(stock_code, entry_date, entry_time)
    if bar is None:
        return None  # 매수 실패
    raw_price = bar['open'] if entry_time == '090000' else bar['close']
    return raw_price * (1 + slippage_rate)
```

**2. P3(매수 당일 TP/SL 차단) 기준일 갱신**: `buy_date`를 D(시그널일)가 아닌 **실제 진입일 D+N** 기준으로. 이 한 줄로 "매수 당일 일봉 OHLC TP/SL 트리거" 문제가 자동 해소됨 (D+N 일자 자체가 차단 대상).

### 유지 (변경 없음)

- 슬리피지 0.0025 (실측 교정값)
- 매수 비용 0.015% / 매도 비용 0.245%
- TP 12% / SL 6%
- 리밸런싱 3단계, 매수 게이트, 시대별 점수 산정
- D+N+1부터 일봉 OHLC로 TP/SL 평가

## 6. 멀티버스 러너·출력

### 파일

`scripts/entry_timing_multiverse.py` (워크트리 내 신규)

### 실행 흐름

```python
for entry_time in [090000, 090500, 091500, 093000, 100000, 110000, 145000]:
    for delay_days in [1, 2, 3, 5]:
        result = run_backtest(
            start='2025-02-24',
            end='2026-05-13',
            entry_time=entry_time,
            delay_days=delay_days,
        )
        results.append({
            'combo_id': f"{entry_time}_D+{delay_days}",
            'entry_time': entry_time,
            'delay_days': delay_days,
            **metrics(result),
            **regime_split_metrics(result),
        })

save_parquet(results, 'results/entry_timing_multiverse_YYYYMMDD.parquet')
```

### parquet 스키마

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `combo_id` | str | `"093000_D+1"` |
| `entry_time` | str | `"093000"` |
| `delay_days` | int | 1, 2, 3, 5 |
| `total_return_pct` | float | 전체 기간 누적 수익률 (%) |
| `annualized_return_pct` | float | 연환산 수익률 (%) |
| `sharpe` | float | 샤프 비율 |
| `mdd_pct` | float | 최대 낙폭 (%) |
| `win_rate_pct` | float | 승률 (%) |
| `trades` | int | 거래 수 |
| `avg_holding_days` | float | 평균 보유일 |
| `buy_fail_count` | int | 분봉 누락 등으로 매수 실패한 케이스 |
| `hybrid_return_pct` | float | Hybrid 시대만 누적 수익률 |
| `hybrid_sharpe` | float | Hybrid 시대 샤프 |
| `hybrid_trades` | int | Hybrid 시대 거래 수 |
| `v100_return_pct` | float | V100 시대만 누적 수익률 |
| `v100_sharpe` | float | V100 시대 샤프 |
| `v100_trades` | int | V100 시대 거래 수 |

### 콘솔 리포트 형식

- Top 5 by Sharpe (전체)
- 베이스라인(09:00+D+1) 행 강조
- A×B 히트맵 3종 (Sharpe / Return / MDD)
- V100 시대 Top 3 별도 (표본 적음 경고 포함)
- 권고 조합 1~3개 (전체 샤프 + V100 일관성 + 거래수 ≥ 50)

## 7. 실행·검증 계획

### 단계

| # | 단계 | 예상 시간 |
|---|------|----------|
| 0 | 사전 정합성 확인 (quant_portfolio 커버리지, minute_candles 종목 매칭, 베이스라인 재현) | 10분 |
| 1 | 워크트리 + 백테스터 fork | 1시간 |
| 2 | Smoke run (1개월 × 4 조합) | 15분 |
| 3 | 본 멀티버스 (14개월 × 28 조합, 백그라운드) | 1.5~3.5시간 |
| 4 | 분석·리포트 | 30분 |
| 5 | 의사결정 권고 | 변동 |

### 검증 체크리스트 (단계 2·3 후 필수)

- [ ] 베이스라인 sharpe가 운영 backtester 결과와 ±10% 일치
- [ ] 매수 실패율 < 5%
- [ ] 거래수 총합이 28 조합 간 ±10% 이내
- [ ] V100 시대 거래수 ≥ 20
- [ ] Hybrid 시대 거래수 ≥ 100

## 8. 완료 기준 / 비-스코프

### 이 멀티버스가 답하는 것

- 일중 진입 시각·T+N 지연이 수익률에 미치는 영향
- 현행 D+1 09:05이 28 조합 중 어디에 위치하는가
- Top 1~3 후보 조합 (운영 적용 후보)

### 이 멀티버스가 답하지 않는 것 (별도 작업)

- VWAP·TWAP 같은 가격 함수형 진입
- 분할 매수 / 부분 체결 시뮬
- 일중 신호 (장중 스크리닝)
- VWAP 대비 진입 슬리피지 측정 (별도 운영 측정 항목)

## 9. 리스크·완화

| 리스크 | 완화 |
|--------|------|
| 분봉 데이터 일부 종목 누락 | `buy_fail_count` 컬럼 기록, 5% 초과 시 결과 무효 처리 |
| V100 시대 표본 부족(22일) | 리포트에 표본 적음 표기, 전체 + Hybrid 시대 결과 우선 |
| 베이스라인 불일치 | 단계 0 사전 정합성 확인에서 ±10% 검증, 불일치 시 멀티버스 중단·원인 분석 |
| 28 조합 실행 중 운영 영향 우려 | DB SELECT only, 별도 worktree 프로세스, KIS API 0 호출로 원천 차단 |
| 매수 게이트의 D vs D+N 시점 차이 해석 | spec 4절에 명시: D+N 시점 가격으로 게이트 재평가 (진입 직전 가격이 의사결정 시점) |
