# 순수 리밸런싱 모드 전환 구현 완료 보고서

## 개요

문서 의도에 맞게 순수 리밸런싱 방식으로 전환하는 기능을 구현했습니다. 이제 `config/trading_config.json`에서 `rebalancing_mode` 설정을 통해 순수 리밸런싱 모드와 하이브리드 모드를 선택할 수 있습니다.

## 구현 일자

2025-01-XX

## 구현 목표

문서(`docs/quant_implementation_gap.md`)에서 제시한 순수 리밸런싱 방식 구현:
- 09:05 리밸런싱으로만 포지션 구성
- 장중 매수 판단 비활성화
- 조건검색 체크 비활성화
- 보유 종목만 모니터링 (손절/익절 판단만 수행)

## 구현 내용

### 1. `_trading_decision_task()` 수정

**위치:** `main.py` 274-281줄

**변경 사항:**
- 리밸런싱 모드일 때 `_check_condition_search()` 호출 스킵
- `rebalancing_mode` 설정값을 확인하여 조건검색 체크 비활성화

**코드:**
```python
# 🆕 장중 조건검색 체크 (장 시작 ~ 청산 시간 전까지) - 동적 시간 적용
# 리밸런싱 모드일 때는 스킵 (순수 리밸런싱 방식: 09:05 리밸런싱으로만 포지션 구성)
if (not getattr(self.config, 'rebalancing_mode', False) and
    is_market_open(current_time) and
    not MarketHours.is_eod_liquidation_time('KRX', current_time) and
    (current_time - last_condition_check).total_seconds() >= 60):  # 60초
    await self._check_condition_search()
    last_condition_check = current_time
```

### 2. `_update_intraday_data()` 수정

**위치:** `main.py` 1268-1273줄

**변경 사항:**
- 리밸런싱 모드일 때 `_analyze_buy_decision()` 호출 스킵
- 장중 매수 판단 비활성화 (보유 종목 모니터링만 수행)

**코드:**
```python
# 리밸런싱 모드일 때는 장중 매수 판단 스킵 (순수 리밸런싱 방식: 09:05 리밸런싱으로만 포지션 구성)
if getattr(self.config, 'rebalancing_mode', False):
    # 리밸런싱 모드: 장중 매수 판단 스킵 (보유 종목 모니터링만 수행)
    if minute_in_3min_cycle == 0 and current_second >= 10:
        self.logger.debug(f"ℹ️ 리밸런싱 모드: 장중 매수 판단 스킵 (09:05 리밸런싱으로만 포지션 구성) - {current_time.strftime('%H:%M:%S')}")
    return
```

### 3. `_check_condition_search()` 함수에 안전장치 추가

**위치:** `main.py` 1137-1143줄

**변경 사항:**
- 함수 내부에서도 리밸런싱 모드 체크 추가
- 이중 안전장치로 실수 방지

**코드:**
```python
async def _check_condition_search(self):
    """장중 퀀트 후보 스크리닝 결과 반영"""
    try:
        # 리밸런싱 모드일 때는 실행하지 않음 (순수 리밸런싱 방식)
        if getattr(self.config, 'rebalancing_mode', False):
            self.logger.debug("ℹ️ 리밸런싱 모드: 장중 조건검색 체크 스킵 (09:05 리밸런싱으로만 포지션 구성)")
            return
        
        quant_candidates = await self.candidate_selector.get_quant_candidates(limit=50)
        # ... 나머지 코드
```

### 4. 초기화 시점 로그 메시지 추가

**위치:** `main.py` 51-55줄

**변경 사항:**
- 초기화 시점에 리밸런싱 모드 상태를 명확히 로깅
- 사용자가 현재 모드를 쉽게 확인할 수 있도록 개선

**코드:**
```python
# 리밸런싱 모드 상태 로깅
if getattr(self.config, 'rebalancing_mode', False):
    self.logger.info("🔄 순수 리밸런싱 모드 활성화: 09:05 리밸런싱으로만 포지션 구성, 장중 매수 판단 비활성화")
else:
    self.logger.info("🔄 하이브리드 모드: 리밸런싱 + 실시간 매수 판단 병행")
```

## 동작 방식

### 순수 리밸런싱 모드 (`rebalancing_mode: true`)

1. **15:40**: 퀀트 스크리닝 실행
   - 전체 종목 → 필터링 → 팩터 계산 → 상위 50개 선정
   - 결과를 DB `quant_portfolio` 테이블에 저장

2. **익일 09:05**: 리밸런싱 실행
   - 현재 보유 종목 vs 목표 포트폴리오(상위 50개) 비교
   - 매도: 보유 중이지만 목표 포트에 없는 종목 → 시장가 전량 매도
   - 매수: 목표 포트에 있지만 보유하지 않은 종목 → 동등 비중 시장가 매수

3. **장중**: 보유 종목만 모니터링
   - 손절/익절 판단만 수행
   - 장중 매수 판단 비활성화 ✅
   - 조건검색 체크 비활성화 ✅

### 하이브리드 모드 (`rebalancing_mode: false`)

- 기존과 동일하게 리밸런싱 + 실시간 매수 판단 병행
- 09:05 리밸런싱으로 기본 포지션 구성
- 장중 실시간 매수 판단으로 추가 기회 포착

## 설정 방법

`config/trading_config.json` 파일에서 설정:

```json
{
  "data_collection": {
    "interval_seconds": 30,
    "candidate_stocks": []
  },
  "order_management": {
    "buy_timeout_seconds": 300,
    "sell_timeout_seconds": 180,
    "max_adjustments": 3,
    "adjustment_threshold_percent": 0.5,
    "market_order_threshold_percent": 2.0,
    "buy_budget_ratio": 0.05,
    "buy_cooldown_minutes": 25
  },
  "risk_management": {
    "max_position_count": 20,
    "max_position_ratio": 0.3,
    "stop_loss_ratio": 0.025,
    "take_profit_ratio": 0.035,
    "max_daily_loss": 0.1
  },
  "strategy": {
    "name": "simple_momentum",
    "parameters": {
      "momentum_period": 5,
      "volume_threshold": 1.5,
      "price_change_threshold": 0.01
    }
  },
  "duplicate_signal_prevention": {
    "enabled": true,
    "overlap_threshold": 0.5,
    "time_filter_hours": 2,
    "min_loss_threshold": -0.5
  },
  "logging": {
    "level": "INFO",
    "file_retention_days": 30
  },
  "paper_trading": true,
  "rebalancing_mode": true  // 순수 리밸런싱 모드 활성화
}
```

## 테스트 방법

1. **설정 변경**
   ```json
   "rebalancing_mode": true
   ```

2. **프로그램 실행**
   - 초기화 로그에서 "🔄 순수 리밸런싱 모드 활성화" 메시지 확인

3. **장중 동작 확인**
   - 로그에서 "ℹ️ 리밸런싱 모드: 장중 매수 판단 스킵" 메시지 확인
   - 로그에서 "ℹ️ 리밸런싱 모드: 장중 조건검색 체크 스킵" 메시지 확인
   - `_check_condition_search()` 호출되지 않음 확인
   - `_analyze_buy_decision()` 호출되지 않음 확인

4. **09:05 리밸런싱 확인**
   - 리밸런싱 계획 계산 및 실행 확인
   - 매도 → 매수 순서로 진행 확인

## 장점

1. **문서 의도와 일치**: 순수 리밸런싱 방식 구현
2. **포지션 관리 단순화**: 리밸런싱으로만 포지션 구성
3. **리밸런싱 전략의 순수성 유지**: 백테스트 결과와 일치
4. **설정으로 전환 가능**: 하이브리드 모드와 순수 리밸런싱 모드 선택 가능

## 참고 문서

- `docs/quant_implementation_gap.md`: 문서 의도 vs 현재 구현 차이점 분석
- `docs/quant_transition_guide.md`: 퀀트 투자 전략 전환 가이드
- `docs/quant_strategy_plan.md`: 퀀트 전략 구현 작업 순서

## 다음 단계

1. ✅ 순수 리밸런싱 모드 전환 구현 완료
2. 테스트 및 검증
3. 팩터 계산 정밀화 (PCR, EV/EBITDA 추가)
4. 리밸런싱 실행 개선 (매도 완료 대기 로직 개선)
5. 모니터링 및 알림 강화



