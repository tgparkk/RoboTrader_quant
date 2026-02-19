# 가상매매 DB 저장 기능 개선

## 📅 날짜: 2025-12-03

## 🎯 목적
리밸런싱 시 실행되는 가상매수/매도 주문이 DB에 저장되지 않는 문제 해결

## ❌ 기존 문제

### 증상
- 리밸런싱 실행 시 50개 종목 가상매수 완료
- 로그에 "🧪(가상) 매수 체결" 메시지 출력
- **하지만 `virtual_trading_records` 테이블에 기록 없음**
- 시스템 재시작 시 매수 기록 사라짐

### 원인
```python
# core/order_manager.py (기존)
if getattr(self.config, "paper_trading", False):
    # 주문 생성 및 completed_orders에 추가
    order = Order(...)
    self.completed_orders.append(order)
    # ❌ DB 저장 로직 없음!
    return fake_order_id
```

## ✅ 해결 방법

### 1. OrderManager에 DB 매니저 추가

**파일**: `core/order_manager.py`

```python
# __init__ 메서드 수정
def __init__(self, config, api_manager, telegram_integration=None, db_manager=None):
    self.db_manager = db_manager  # 🆕 추가
    # ... 기존 코드 ...
```

### 2. 가상매수 시 DB 저장 로직 추가

**파일**: `core/order_manager.py` - `place_buy_order` 메서드

```python
# 가상매매 모드
if getattr(self.config, "paper_trading", False):
    # ... 주문 생성 ...
    
    # 🆕 DB에 가상매매 기록 저장
    if self.db_manager:
        try:
            stock_name = f'Stock_{stock_code}'
            if self.trading_manager:
                trading_stock = self.trading_manager.get_stock(stock_code)
                if trading_stock:
                    stock_name = trading_stock.stock_name
            
            buy_record_id = self.db_manager.save_virtual_buy(
                stock_code=stock_code,
                stock_name=stock_name,
                price=price,
                quantity=quantity,
                strategy="리밸런싱",
                reason="퀀트 포트폴리오"
            )
            if buy_record_id:
                self.logger.info(f"💾 가상매매 기록 저장 완료: {stock_code} (ID: {buy_record_id})")
        except Exception as db_err:
            self.logger.error(f"❌ 가상매매 DB 저장 오류: {db_err}")
```

### 3. 가상매도 시 DB 저장 로직 추가

**파일**: `core/order_manager.py` - `place_sell_order` 메서드

```python
# 가상매매 모드
if getattr(self.config, "paper_trading", False):
    # ... 주문 생성 ...
    
    # 🆕 DB에 가상매도 기록 저장
    if self.db_manager:
        try:
            stock_name = f'Stock_{stock_code}'
            buy_record_id = None
            
            if self.trading_manager:
                trading_stock = self.trading_manager.get_stock(stock_code)
                if trading_stock:
                    stock_name = trading_stock.stock_name
                    if hasattr(trading_stock, '_virtual_buy_record_id'):
                        buy_record_id = trading_stock._virtual_buy_record_id
            
            success = self.db_manager.save_virtual_sell(
                stock_code=stock_code,
                stock_name=stock_name,
                price=price,
                quantity=quantity,
                strategy="리밸런싱",
                reason="포트폴리오 조정",
                buy_record_id=buy_record_id
            )
            if success:
                self.logger.info(f"💾 가상매도 기록 저장 완료: {stock_code}")
        except Exception as db_err:
            self.logger.error(f"❌ 가상매도 DB 저장 오류: {db_err}")
```

### 4. main.py에서 DB 매니저 전달

**파일**: `main.py`

```python
# 변경 전
self.order_manager = OrderManager(self.config, self.api_manager, self.telegram)

# 변경 후
self.order_manager = OrderManager(self.config, self.api_manager, self.telegram, self.db_manager)
```

## 📊 기대 효과

### Before (기존)
```
09:05:08 | 🧪(가상) 매수 체결: VT-BUY-019180-xxx
→ 메모리에만 저장 (completed_orders)
→ DB 기록 없음
→ 재시작 시 사라짐
```

### After (개선)
```
09:05:08 | 🧪(가상) 매수 체결: VT-BUY-019180-xxx
09:05:08 | 💾 가상매매 기록 저장 완료: 019180 (ID: 123)
→ 메모리 + DB 모두 저장
→ virtual_trading_records 테이블에 영구 기록
→ 재시작 후에도 조회 가능
```

## 🔍 테스트 방법

### 1. 단위 테스트
```bash
python test_virtual_trading_db.py
```

### 2. 실제 리밸런싱 후 확인
```python
import sqlite3
conn = sqlite3.connect('data/robotrader.db')
cursor = conn.cursor()

# 오늘 가상매매 기록 조회
cursor.execute('''
    SELECT stock_code, stock_name, action, quantity, price, timestamp
    FROM virtual_trading_records
    WHERE DATE(timestamp) = date('now')
    ORDER BY timestamp
''')

for row in cursor.fetchall():
    print(f"{row[5]}: {row[2]} {row[0]} {row[1]} {row[3]}주 @{row[4]:,.0f}원")
```

## 📝 변경 파일 목록

1. ✅ `core/order_manager.py` - DB 저장 로직 추가
2. ✅ `main.py` - DB 매니저 전달
3. ✅ `test_virtual_trading_db.py` - 테스트 스크립트 (신규)
4. ✅ `CHANGELOG_가상매매DB저장.md` - 변경 이력 (신규)

## 🎯 다음 리밸런싱 시 확인사항

### 예상 로그
```
09:05:08 | 🔄 리밸런싱 시작: 20251204
09:05:08 | 📈 매수 주문 시도: 019180 25주 @7,910원
09:05:08 | 🧪(가상) 매수 체결: VT-BUY-019180-xxx
09:05:08 | 💾 가상매매 기록 저장 완료: 019180 (ID: xxx)  ← 🆕 이 로그 확인!
09:05:08 | ✅ 리밸런싱 매수 주문: 019180(티에이치엔) 25주 시장가
```

### DB 확인
```sql
SELECT COUNT(*) FROM virtual_trading_records 
WHERE DATE(timestamp) = '2025-12-04';
-- 예상 결과: 50개 (리밸런싱 매수 종목 수)
```

## ⚠️ 주의사항

1. **기존 데이터**: 12월 3일 이전 가상매매는 기록 없음 (정상)
2. **실전 모드**: `paper_trading: false` 시에는 실전 API 사용 (변경 없음)
3. **손익 계산**: 매도 시 buy_record_id 연결로 손익 자동 계산

## ✅ 완료

- [x] OrderManager에 DB 매니저 추가
- [x] 가상매수 DB 저장 로직 구현
- [x] 가상매도 DB 저장 로직 구현
- [x] main.py 연동
- [x] 테스트 스크립트 작성
- [x] 변경 이력 문서화

---

**작성자**: AI Assistant
**검토자**: 사용자 확인 필요
**적용일**: 2025-12-03

