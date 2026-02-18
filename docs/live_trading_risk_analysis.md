# RoboTrader_quant 실전매매 전환 위험 분석

> 분석일: 2026-02-08  
> 대상: paper_trading=true → false 전환 시 위험 요소

---

## 요약

| 심각도 | 건수 | 설명 |
|--------|------|------|
| **P0 (치명)** | 3건 | 즉시 자금 손실 가능 |
| **P1 (높음)** | 4건 | 운영 장애 또는 부정확한 거래 |
| **P2 (보통)** | 3건 | 개선 권장 |

---

## P0 — 치명적 위험 (즉시 수정 필요)

### P0-1. main.py 주석 분기 방식 — 실전 코드가 `pass`로 무력화됨

**현상:**  
main.py L340~356에서 실제 매수 코드가 주석처리된 후 `pass`만 남아있음. 실제 매도도 L403~408 주석처리. `paper_trading=false`로 변경해도 **main.py의 주석을 직접 해제하지 않으면 매수/매도가 아예 실행되지 않음.**

```python
# [실제 매수 코드 - 주석처리]
# await self.decision_engine.execute_real_buy(...)
pass  # ← 이것만 실행됨

# [가상매매 코드 - 활성화]
await self.decision_engine.execute_virtual_buy(...)  # ← 이것도 무조건 실행
```

**문제점:**
- 가상매매 코드와 실매매 코드가 if/else 분기가 아닌 **주석 토글** 방식 → 둘 다 활성화되거나 둘 다 비활성화 가능
- 실전 코드 해제 시 가상 코드도 주석처리해야 하는데, 실수로 **둘 다 활성화하면 이중 주문** 발생
- 매도도 동일 구조: 실매도 주석 해제 + 가상매도 주석처리 모두 필요

**해결 방안:**
```python
if self.config.paper_trading:
    await self.decision_engine.execute_virtual_buy(...)
else:
    await self.decision_engine.execute_real_buy(...)
```
→ `paper_trading` 플래그 기반 자동 분기로 변경. 주석 토글 제거.

---

### P0-2. 리밸런싱 주문 간격 0.1초 — KIS API rate limit 위반 가능

**현상:**  
`REBALANCING_ORDER_INTERVAL = 0.1` (constants.py L10). 리밸런싱 시 매도 15건 + 매수 15건 = 최대 30건 주문이 0.1초 간격으로 발생.

**위험:**
- KIS API 초당 20건 제한 → 0.1초 간격이면 초당 10건이라 단독으로는 통과
- 그러나 각 주문 전 `get_current_price` API도 호출 → **주문+조회 합산 시 초당 20건 초과 가능**
- 매수 시 추가로 `get_ohlcv_data` (전일 일봉), `get_index_data` (코스피) 호출 → **burst 시 rate limit 위반**
- rate limit 위반 시 주문 실패 → 일부 종목만 매도되고 매수 안 됨 → **포트폴리오 불균형**

**해결 방안:**
- `REBALANCING_ORDER_INTERVAL`을 `0.5`초 이상으로 증가
- API 호출 레벨에서 글로벌 rate limiter 구현 (토큰 버킷)
- 조회 API와 주문 API를 분리하여 조회를 선행 배치 처리

---

### P0-3. 리밸런싱 매도 실패 시에도 매수 진행 — 자금 부족 위험

**현상:**  
`rebalancing_executor.py`에서 매도 주문 실패해도 매수 리스트를 그대로 진행.

```python
# 매도 실패한 종목이 있어도...
sell_results에 success=False 포함

# 매수는 무조건 진행
for buy_item in buy_list:
    # 매도 실패로 확보되지 않은 자금으로 매수 시도
```

**위험:**
- 매도 5건 중 3건 실패 → 현금 부족 → 매수 주문도 실패하거나 부분 체결
- 가상매매는 즉시 체결이라 이 문제가 없었지만, **실전에서는 매도 미체결 가능**

**해결 방안:**
- 매도 체결 완료 후 실제 가용 잔고 확인 → 잔고 기준으로 매수 수량 재계산
- 매도 실패 건수가 임계값 초과 시 매수 중단 및 알림

---

## P1 — 높은 위험

### P1-1. 체결 확인 로직은 있으나 부분 체결 처리 미흡

**현상:**  
`order_manager.py`에 미체결 모니터링 (`_monitor_pending_orders`)과 타임아웃 처리가 구현되어 있음. 3초 간격 체크, 5분 타임아웃, 4봉 후 취소 등.

**그러나:**
- 부분 체결(예: 100주 주문 → 70주 체결)시 잔여 30주에 대한 후속 처리 로직이 명확하지 않음
- `_handle_timeout`에서 취소 후 부분 체결분 포지션 반영이 불완전할 수 있음
- 시장가 매도(`market=True`)인데 `price=current_price`로 전달 → 실제 체결가와 기록 가격 불일치

**해결 방안:**
- 부분 체결 시 잔여 수량 재주문 또는 포지션 부분 반영 로직 명확화
- 시장가 주문 시 체결 후 실제 체결가를 조회하여 DB 업데이트

---

### P1-2. 가상매매와 실전매매가 같은 DB 테이블 사용

**현상:**  
`order_manager.py`에서 가상매매도 `save_virtual_buy/sell`을 호출하고, `VirtualTradingManager`도 동일 메서드 사용. 실전 모드 전환 시에도 `virtual_trading_records` 테이블에 기록.

**위험:**
- 실전 거래 기록이 "virtual" 테이블에 혼재 → 가상/실전 구분 불가
- `state_restoration_helper.py`의 `_restore_holdings_from_real_account`는 실제 계좌 API 조회 기반이라 DB 테이블과 무관하게 동작하지만, 수익률 계산/리포트에서 가상 기록과 혼동

**해결 방안:**
- 실전 모드에서는 별도 `real_trading_records` 테이블 사용, 또는 `mode` 컬럼 추가
- 최소한 기록 시 `paper_trading` 플래그를 함께 저장

---

### P1-3. 손익절 시 슬리피지 미고려

**현상:**  
`execute_real_sell`에서 `price=0` (시장가)으로 매도. 가상매매는 현재가로 즉시 체결 가정하지만 실전에서는:
- 호가 스프레드에 의한 슬리피지
- 거래량 부족 종목의 충격 비용
- 15종목 동시 손절 시 순차 처리 지연 (0.1초 간격이라도 15건 ≈ 1.5초)

**위험:**
- 손절가 -10%에서 트리거되었지만 실제 체결은 -12%
- 동시 다수 손절 시 먼저 매도되는 종목과 나중 종목의 체결가 차이

**해결 방안:**
- 손절 시뮬레이션에 슬리피지 버퍼 추가 (예: 손절 트리거를 -9%로 앞당김)
- 손절 우선순위: 손실 큰 종목부터, 또는 유동성 낮은 종목부터

---

### P1-4. 프로그램 재시작 시 미체결 주문 복원 없음

**현상:**  
`order_manager.py`의 `pending_orders`는 메모리 딕셔너리. 프로그램 재시작 시 미체결 주문 정보 소실.

**시나리오:**
1. 09:05 리밸런싱 → 매도 3건 미체결 상태
2. 프로그램 크래시/재시작
3. 미체결 매도 주문은 거래소에 살아있지만 프로그램은 모름
4. `state_restoration_helper`가 실제 계좌 조회로 포지션은 복원하지만, 미체결 주문은 복원 안 됨
5. 동일 종목 중복 매도 주문 가능

**해결 방안:**
- 시작 시 KIS API `get_inquire_psbl_rvsecncl_lst` (미체결 조회)로 기존 주문 확인
- 미체결 주문을 `pending_orders`에 복원하거나, 전량 취소 후 재주문

---

## P2 — 보통 위험

### P2-1. config 전환 시 추가 변경 필요 사항

**변경 목록:**
1. `trading_config.json`: `paper_trading: false` ← **필수**
2. `main.py`: 실전 매수/매도 코드 주석 해제 + 가상 코드 주석처리 ← **P0-1 해결 전까지 필수**
3. `config/key.ini`: 실전 계좌 APP_KEY/SECRET 확인 (모의투자 키와 다름)
4. `kis_order_api.py`: TR ID 확인 — 현재 `TTTC0012U`(실전 매수), `TTTC0011U`(실전 매도) 사용 중 → **실전용 맞음** ✅
   - 단, 모의투자 시 `VTTC0802U/0801U`를 써야 하는데 현재 하드코딩 → 모의투자 테스트 불가

**해결 방안:**
- 전환 체크리스트 스크립트 작성 (`scripts/switch_to_live.py`)
- 환경별 config 프로파일 (dev/paper/live)

---

### P2-2. VirtualTradingManager 잔고 조회 시점

**현상:**  
`_initialize_real_balance()`에서 프로그램 시작 시 1회만 계좌 잔고 조회. 이후 매수/매도 시 `virtual_balance`를 메모리에서 증감.

**위험:**
- 외부(HTS/MTS)에서 수동 매매 시 잔고 불일치
- 장시간 운영 중 메모리 잔고 drift

**해결 방안:**
- `refresh_balance()` 메서드가 이미 구현되어 있으므로, 주기적 호출 (예: 30분마다) 추가

---

### P2-3. 실전 계좌 보유종목 ↔ DB 불일치 감지 후 처리

**현상:**  
`state_restoration_helper.py`의 `_detect_holdings_mismatch`에서 불일치를 감지하고 텔레그램 알림을 보냄. 그러나 **자동 보정은 하지 않음** — DB에 없는 종목은 기본 익절/손절률 적용.

**위험:**
- DB에 기록 없는 외부 매수 종목이 기본 익절 15%/손절 10%로 관리됨
- 의도와 다른 손익절 트리거 가능

**해결 방안:**
- 불일치 종목을 DB에 자동 등록하거나, 해당 종목은 손익절 판단에서 제외하는 옵션 추가

---

## 실전 전환 체크리스트

```
[ ] 1. P0-1 수정: main.py 주석 분기 → config 기반 if/else 분기로 리팩토링
[ ] 2. P0-2 수정: REBALANCING_ORDER_INTERVAL 0.1 → 0.5초 이상
[ ] 3. P0-3 수정: 매도 실패 시 매수 중단 로직 추가
[ ] 4. P1-4 수정: 시작 시 미체결 주문 조회/정리 로직 추가
[ ] 5. trading_config.json: paper_trading → false
[ ] 6. key.ini: 실전 계좌 키 확인
[ ] 7. 소액 테스트: 1~2종목으로 실전 매수/매도 1회 검증
[ ] 8. 리밸런싱 테스트: 장전에 2~3종목 소규모 리밸런싱 검증
[ ] 9. 모니터링: 첫 실전 운영일은 전일 모니터링
```
