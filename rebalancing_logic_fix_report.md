# 리밸런싱 로직 수정 보고서

**수정 날짜**: 2025-12-16

---

## 🔍 발견된 문제

### 문제점
1. **보유 종목 수**: 54개 (목표: 최대 30개)
2. **리밸런싱 매도가 제대로 실행되지 않음**

### 원인 분석

#### 1. 보유 종목 조회 로직 문제
- **위치**: `core/quant/quant_rebalancing_service.py` - `_get_current_holdings()`
- **문제**: 실제 계좌 API(`kis_account_api.get_inquire_balance()`)를 사용하여 보유 종목 조회
- **영향**: 가상 매매 모드에서는 실제 계좌에 보유 종목이 없거나 적을 수 있어, 매도 대상이 제대로 산출되지 않음

#### 2. 매도 시 buy_record_id 누락 문제
- **위치**: `core/order_manager.py` - `place_sell_order()`
- **문제**: 리밸런싱 매도 시 `buy_record_id`가 제대로 조회되지 않을 수 있음
- **영향**: 매도 기록이 제대로 저장되지 않거나 손익 계산이 누락될 수 있음

---

## ✅ 수정 내용

### 1. 보유 종목 조회 로직 수정

**파일**: `core/quant/quant_rebalancing_service.py`

**변경 사항**:
- 가상 매매 모드일 때 `virtual_trading_records` 테이블에서 보유 종목 조회
- 실제 계좌 조회는 가상 매매 모드가 아니거나 DB 조회 실패 시에만 사용

**수정된 로직**:
```python
def _get_current_holdings(self) -> List[Dict[str, Any]]:
    """
    현재 보유 종목 조회
    
    가상 매매 모드: virtual_trading_records 테이블에서 조회
    실제 매매 모드: 실제 계좌 API에서 조회
    """
    # 1. 가상 매매 모드: virtual_trading_records에서 조회
    if self.db_manager:
        # 종목코드별 보유 수량 집계
        # 매수 기록 - 매도 기록 = 보유 수량
    
    # 2. 실제 계좌 조회 (fallback)
    # kis_account_api.get_inquire_balance()
```

### 2. 매도 시 buy_record_id 조회 로직 추가

**파일**: `core/order_manager.py`

**변경 사항**:
- `trading_manager`에서 `buy_record_id`를 찾지 못하면 DB에서 직접 조회
- `get_last_open_virtual_buy()` 함수 사용

**수정된 로직**:
```python
# buy_record_id가 없으면 DB에서 조회
if not buy_record_id and self.db_manager:
    buy_record_id = self.db_manager.get_last_open_virtual_buy(stock_code, quantity)
```

### 3. 가상 매매용 buy_record_id 조회 함수 추가

**파일**: `db/database_manager.py`

**추가된 함수**:
```python
def get_last_open_virtual_buy(self, stock_code: str, quantity: int = None) -> Optional[int]:
    """
    가상 매매: 해당 종목의 미매칭 매수(가장 최근) ID 조회
    
    Args:
        stock_code: 종목코드
        quantity: 매도할 수량 (지정 시 해당 수량만큼 매도되지 않은 매수 기록 조회)
    
    Returns:
        매수 기록 ID 또는 None
    """
```

---

## 📊 예상 효과

### 수정 전
- 보유 종목 조회: 실제 계좌 API 사용 → 가상 매매 모드에서 빈 결과
- 매도 대상 산출: 빈 보유 종목 리스트 → 매도 대상 없음
- 결과: 이전 매수 기록들이 남아있음 (54개)

### 수정 후
- 보유 종목 조회: `virtual_trading_records` 테이블에서 조회 → 정확한 보유 종목
- 매도 대상 산출: 정확한 보유 종목 리스트 → 매도 대상 정확히 산출
- 결과: 리밸런싱 시 목표 포트폴리오에 없는 종목이 제대로 매도됨 (최대 30개 유지)

---

## 🔄 다음 리밸런싱 실행 시

1. **보유 종목 조회**: `virtual_trading_records` 테이블에서 54개 종목 조회
2. **목표 포트폴리오**: 30개 종목 조회
3. **매도 대상 산출**: 54개 - 30개(교집합) = 약 24개 종목 매도 대상
4. **매도 실행**: 24개 종목 시장가 전량 매도
5. **매수 실행**: 목표 포트에 있지만 보유하지 않은 종목 매수
6. **최종 결과**: 최대 30개 종목만 보유

---

## 📝 참고사항

- 수정된 로직은 다음 리밸런싱 실행 시 적용됩니다
- 현재 보유 중인 54개 종목 중 목표 포트폴리오에 없는 종목은 다음 리밸런싱 시 매도됩니다
- 가상 매매 모드와 실제 매매 모드 모두 지원합니다

---

**수정 완료 시간**: 2025-12-16

