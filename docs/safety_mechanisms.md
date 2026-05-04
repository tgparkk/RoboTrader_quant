# 안전 메커니즘 상세

> CLAUDE.md에서 분리된 상세 문서 (2026-01-25 ~ 02-03 구현)

## 1. 09:00 즉시 손절/익절 허용

**위치**: `core/trading_decision_engine.py`, `core/trading_stock_manager.py`

장 시작(09:00)과 동시에 TP/SL 모두 즉시 작동합니다. 09:05 리밸런싱과 독립적으로 동작.

**목표가**: `target_profit_rate = 0.12` (12% 익절), `stop_loss_rate = 0.06` (6% 손절)

```python
def _check_simple_stop_profit_conditions(self, trading_stock, current_price):
    # 익절 조건 확인
    if profit_rate >= target_profit_rate:
        return True, f"목표 익절 도달 ({profit_rate:.2%} >= {target_profit_rate:.0%})"

    # 손절 조건 확인 (09:00부터 즉시 허용)
    if profit_rate <= -stop_loss_rate:
        return True, f"손절 실행 ({profit_rate:.2%} <= {-stop_loss_rate:.0%})"

    return False, None
```

**변경 이력**: 
- 2026-01-23: 갭하락 사건 후 09:00-09:05 손절 중단 도입
- 2026-03-31: 백테스트 검증 결과 hold 유예가 역효과(샤프 -3.25)임을 확인하여 제거
  - 사유: 당일 손절 종목 재매수 차단(안전장치 #2)이 갭하락 재매수를 방지하므로, 추가 유예 불필요
  - 결과: TP/SL이 정상 작동하여 수익 창출

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
- **간격**: 60ms (초당 16-17회, KIS 공식 제한 20회 대비 안전 마진)
- **재시도 로직**: 최대 3회 (지수 백오프, 최대 3초 캡)
- **서킷 브레이커**: 연속 10회 실패 시 60초 차단
- **Rate Limit 오류 자동 감지**: 429 상태코드 감지 시 자동 대기
- **영향**: 모든 모듈에 투명하게 적용 (kis_auth.py 경유 필수)

---

## 8. 리밸런싱 3단계 매도 로직

**위치**: `core/quant/quant_rebalancing_service.py` → `calculate_rebalancing_plan()` (라인 200~234)

보유 종목 점수를 3단계로 검증하여 매도 대상 결정:

**1단계: 긴급 매도 (Hard Stop)**
- 조건: `score < 65.0`
- 액션: 즉시 매도
- 사유: 기본 임계값 하한 돌파

**2단계: 조건부 매도 (Soft Stop)**
- 조건: `65.0 ≤ score < 67.0 AND rank > 30`
- 액션: 조건부 매도 (순위가 충분히 낮으면 매도)
- 사유: 점수는 최소선 근처이지만 순위까지 낮으면 매도

**3단계: 포트폴리오 리밸런싱**
- 조건: 목표 포트폴리오에 제외된 종목 중 `score < 75 AND rank > 25`
- 액션: 조건부 매도 (안전 종목은 유지)
- 사유: 점수나 순위가 우수하면 리밸런싱에도 불구하고 유지

---

## 9. 리밸런싱 매도 reason 구분

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
