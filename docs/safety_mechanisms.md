# 안전 메커니즘 상세

> CLAUDE.md에서 분리된 상세 문서 (2026-01-25 ~ 02-03 구현)

## 1. 리밸런싱 직전 손절 중단 (09:00-09:05)

**위치**: `core/trading_decision_engine.py`

리밸런싱 직전 5분간은 익절만 허용하고 손절은 중단합니다.

```python
def _check_simple_stop_profit_conditions(self, trading_stock, current_price):
    current_time = now_kst()

    # 09:00~09:05 사이에는 손절 체크 안 함 (익절만)
    is_before_rebalancing = (
        current_time.hour == 9 and current_time.minute < 5
    )

    buy_price = trading_stock.position.buy_price
    profit_rate = (current_price - buy_price) / buy_price

    # 익절 조건 확인 (항상 활성)
    if profit_rate >= target_profit_rate:
        return True, f"목표 익절 도달 (...)"

    # 손절 조건 확인 (리밸런싱 전에는 스킵)
    if not is_before_rebalancing:
        if profit_rate <= -stop_loss_rate:
            return True, f"손절 실행 (...)"

    return False, None
```

**배경**: 2026-01-23 갭하락으로 3개 종목 손절 후 5분 뒤 리밸런싱에서 재매수 → 35만원 손실 발생

---

## 2. 당일 손절 종목 재매수 차단

**위치**:
- DB 조회: `db/database_manager.py` → `get_today_stop_loss_stocks()`
- 리밸런싱 적용: `core/helpers/rebalancing_executor.py`

오늘 손절한 종목을 DB에서 조회하여 리밸런싱 시 재매수 금지:

```python
today_stop_loss_stocks = self.db_manager.get_today_stop_loss_stocks()

for buy_item in buy_list:
    if stock_code in today_stop_loss_stocks:
        logger.warning(f"매수 스킵: 오늘 손절한 종목 - 재매수 금지")
        continue
```

---

## 3. 2단계 매수 가격 검증

**위치**: `core/helpers/rebalancing_executor.py` → `_validate_buy_price()`

리밸런싱 매수 시 가격 적정성을 2단계로 검증:

**1단계: 절대 가격 밴드 검증**
- 하한: 전일 저가의 -5% (급락 방지)
- 상한: 전일 종가의 +10% (과열 방지)

**2단계: 시장 대비 상대 강도 검증**
- 코스피 지수 대비 -5%p 이상 약세 종목 제외
- 시장 대비 +8%p 이상 강세 종목은 로그 표시

**데이터 소스**:
- 전일 OHLCV: API 조회 (주말/공휴일 자동 처리)
- 코스피 지수: `get_index_data("0001")` → `bstp_nmix_prdy_ctrt` 필드 사용

---

## 4. Thread-Safe 매수 로직

**위치**: `core/trading_stock_manager.py`

Lock 기반 원자적 상태 변경으로 중복 매수 방지:

```python
with self._lock:
    if trading_stock.is_buying:
        return False
    trading_stock.is_buying = True
```

---

## 5. Race Condition 방지 - 중복 매도 차단

**위치**: `db/database_manager.py`

UNIQUE 인덱스로 동일 `buy_record_id`에 대해 SELL 1건만 허용:

```sql
CREATE UNIQUE INDEX idx_virtual_trading_unique_sell
ON virtual_trading_records(buy_record_id)
WHERE action = 'SELL' AND buy_record_id IS NOT NULL
```

IntegrityError 발생 시 중복 매도로 판단하여 차단.

---

## 6. Memory Management (당일 데이터만 유지)

**위치**: `core/intraday_stock_manager.py`

realtime_data는 당일 데이터만 필터링하여 메모리 누적 방지.

---

## 7. 전역 API Rate Limiting

**위치**: `api/kis_auth.py`

모든 API 호출에 자동 적용:
- 60ms 간격 (초당 16-17회, KIS 제한 20회 대비 안전 마진)
- 재시도 로직 포함 (최대 3회)
- Rate Limit 오류 자동 감지 및 대기

---

## 8. 리밸런싱 매도 reason 구분

리밸런싱 매도와 장중 손익절을 reason 접두사로 구분:

```python
# 리밸런싱 매도
"[리밸런싱] 긴급 매도 (점수 xx < 65)"
"[리밸런싱] 조건부 매도 (점수 xx, 순위 xx)"
"[리밸런싱] 포트폴리오 조정 (...)"

# 장중 손익절
"손절 실행 (-8.5% <= -8.0%)"
"목표 익절 도달 (16.3% >= 16.0%)"
```

SQL로 필터링 시 `reason LIKE '%리밸런싱%'` 또는 `reason LIKE '%손절%'`로 구분 가능.
