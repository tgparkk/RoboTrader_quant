# 멀티버스 분석 가이드

## 개요

멀티버스 = 파라미터 조합을 대량으로 백테스트하여 최적값을 탐색하는 방식.
데이터를 1회 로드 후 캐시를 재사용하므로 빠르게 수백 개 조합을 테스트할 수 있다.

## 공통 패턴

모든 멀티버스 스크립트는 동일한 구조:
```
python scripts/<script>.py --start 2023-01-01 --end 2026-03-31
```

**기본 기간**: 2023-01-01 ~ 2026-03-31 (787거래일)
**DB**: robotrader_backtest (PostgreSQL, port 5433)
**데이터**: daily_prices + quant_portfolio + quant_factors

## 현재 라이브 설정 (베이스라인)

```python
# 2026-05-07 갱신 — V100 단일 팩터 + 6단계 매수 게이트
portfolio_size=10, target_profit_rate=0.12, stop_loss_rate=0.06
hard_stop=65, soft_stop=67, soft_stop_rank=30, safe=75, safe_rank=25
buy_min_score=95.0  # V100 전환 (2026-04-14)
rebalancing_sell_cooldown_days=3

# 매수 게이트 (적용 순서)
BUY_RET5D_MIN = -3.0           # 5일 급락 차단
BUY_RET5D_MAX = 17.0           # 5일 모멘텀 천장 (2026-05-06)
BUY_RET20D_MAX = 30.0          # 20일 모멘텀 천장 (2026-05-07)
BUY_MOMENTUM_SCORE_MIN = 30.0  # momentum_score 합성 점수 하한 (2026-05-07)
BUY_SCORE_MOMENTUM_MIN = None  # V100 전환 후 비활성

# 백테스트 비용 (실측 교정)
slippage_rate = 0.0025         # 왕복 0.45% (2026-04-13 실측)
buy_cost_rate = 0.00015
sell_cost_rate = 0.00245
```

---

## 멀티버스 스크립트 목록

### 1. 파라미터 최적화 (기존 파라미터 튜닝)

| 스크립트 | 탐색 대상 | 조합 수 | 소요 시간 |
|----------|-----------|---------|-----------|
| `tp_sl_multiverse.py` | TP/SL 비율 (11x9=99) | ~99 | ~75초 |
| `buy_min_score_multiverse.py` | 매수 최소 점수 (0~75) | ~9 | ~4초 |
| `max_hold_days_multiverse.py` | 최대 보유일수 (0~60) | ~10 | ~30초 |
| `cooldown_multiverse.py` | 리밸런싱 매도 쿨다운 (0~7일) | ~8 | ~30초 |
| `combined_optimization_multiverse.py` | 다차원 (hold, size, score, sl, ret5d) | 가변 | 수분 |
| `multi_dimension_multiverse.py` | 포트크기+TP+SL+보유일+점수 | 가변 | 수분 |

### 2. 시장 레짐 필터

| 스크립트 | 탐색 대상 | 설명 |
|----------|-----------|------|
| `regime_multiverse.py` | KOSPI갭/S&P/VIX 임계값 | 장전 레짐 판단 기준 최적화 |
| `crisis_sell_multiverse.py` | CRISIS 전량매도 조건 | 전량매도 트리거 조건 최적화 |
| `market_halt_multiverse.py` | 시장 하락 시 매수 중단 | 갭하락/VIX 기준 매수 중단 |

### 3. 신호 필터 (2026-04-04 신규)

| 스크립트 | 용도 | 설명 |
|----------|------|------|
| `blind_pattern_discovery.py` | 승/패 차이 자동 탐색 | 47개 피처 생성 + 통계 검정 + Decision Tree |
| `signal_filter_multiverse.py` | 신호 필터 멀티버스 | FilteredBacktester로 5종 필터 탐색 |
| `signal_filter_walkforward.py` | 연도별 워크포워드 검증 | 2023/2024/2025/2026Q1 분할 일관성 |
| `signal_filter_fixed_capital.py` | 고정 자본 검증 | 복리 제거, 현실적 손익 측정 |

### 4. 검증/분석 도구

| 스크립트 | 용도 |
|----------|------|
| `tp_sl_walkforward.py` | TP/SL 워크포워드 안정성 검증 |
| `score_profit_correlation.py` | 퀀트 점수 vs 수익률 상관분석 |
| `strategy_analysis.py` | SL 회복률, CRISIS 사후분석, KOSPI 비교 |
| `tpsl_yearly_analysis.py` | 연도별 TP/SL 성과 분해 |
| `sl_recovery_analysis.py` | 손절 후 회복 가능성 분석 |
| `cooldown_skip_analysis.py` | 쿨다운 효과 분석 |

---

## 사용 시나리오

### "전략 전반을 재검토하고 싶다"
```bash
# 1. 승/패 차이부터 파악
python scripts/blind_pattern_discovery.py --start 2023-01-01 --end 2026-03-31

# 2. 발견된 신호를 멀티버스로 검증
python scripts/signal_filter_multiverse.py

# 3. 연도별 일관성 확인
python scripts/signal_filter_walkforward.py

# 4. 고정 자본으로 현실 검증
python scripts/signal_filter_fixed_capital.py
```

### "TP/SL을 재최적화하고 싶다"
```bash
python scripts/tp_sl_multiverse.py --start 2023-01-01 --end 2026-03-31
python scripts/tp_sl_walkforward.py  # 안정성 검증
python scripts/tpsl_yearly_analysis.py  # 연도별 분해
```

### "새 필터 아이디어를 테스트하고 싶다"
`signal_filter_multiverse.py`의 `FilteredBacktester`를 확장:
1. `__init__`에 새 파라미터 추가
2. `_execute_rebalancing`의 매수 루프에 필터 조건 추가
3. `individual_tests`에 탐색 값 추가

### "시장 방어 메커니즘을 강화하고 싶다"
```bash
python scripts/regime_multiverse.py
python scripts/crisis_sell_multiverse.py
python scripts/market_halt_multiverse.py
```

---

## 결과 해석 주의사항

1. **샤프 비율만 보지 말 것** - 거래수 감소가 샤프를 인위적으로 올림
2. **고정 자본 총손익 확인** - 복리 효과 제거 후 실제 개선인지 확인
3. **워크포워드 일관성** - 4/4 연도 일관이면 신뢰, 2/4 이하면 과적합 의심
4. **거래수 감소율** - 70%+ 감소는 과적합 위험, 50% 이하가 안전
5. **2026Q1 결과 중시** - 가장 최근 = 실전에 가장 가까운 기간

## 새 멀티버스 추가 시 체크리스트

- [ ] 데이터 1회 로드 + 캐시 재사용 패턴 따르기
- [ ] `--start`, `--end` 인자 지원
- [ ] 베이스라인(현재 설정) 포함하여 비교 가능하게
- [ ] 결과를 샤프 순 정렬로 출력
- [ ] 이 가이드에 스크립트 추가
