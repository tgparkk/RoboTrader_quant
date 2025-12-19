# RoboTrader 퀀트 시스템 아키텍처

## 시스템 개요

한국투자증권 API를 사용한 자동매매 시스템으로, 퀀트 팩터 기반 종목 선정과 점수 기반 리밸런싱을 수행합니다.

## 핵심 동작 흐름

### 1. 아침 09:05 리밸런싱 (1회 실행)

**위치**: `core/quant/target_profit_loss_calculator.py:56-119`

종목별 복합 점수를 계산하여 차등 목표 익절/손절률을 설정합니다:

```python
# 종목별 복합 점수 계산
composite_score = (rank_score * 0.4) + (factor_score * 0.3) + (momentum_score * 0.3)

# 점수 기반 차등 목표 익절/손절률
if composite_score >= 70:    # S등급
    target_profit_rate = 0.20  # 20%
    stop_loss_rate = 0.08      # 8%
elif composite_score >= 50:   # A등급
    target_profit_rate = 0.18  # 18%
    stop_loss_rate = 0.09      # 9%
else:                         # B등급
    target_profit_rate = 0.15  # 15%
    stop_loss_rate = 0.10      # 10%
```

**저장 위치**: `virtual_trading_records` 테이블의 `target_profit_rate`, `stop_loss_rate` 컬럼

### 2. 장중 모니터링 (1분마다 주기적 체크)

**위치**: `core/trading_decision_engine.py:269-310`

현재가 API를 호출하여 손익절 조건을 체크합니다:

```python
# 현재가 API 조회
current_price_info = self.intraday_manager.get_current_price_for_sell(stock_code)
current_price = current_price_info['current_price']

# 손익절 조건 체크
def _check_simple_stop_profit_conditions(trading_stock, current_price):
    buy_price = trading_stock.position.buy_price
    profit_rate = (current_price - buy_price) / buy_price

    # 익절: 목표 수익률 도달
    if profit_rate >= trading_stock.target_profit_rate:
        return (True, f"목표 익절 도달 ({profit_rate:.1%})")

    # 손절: 손절률 도달
    if profit_rate <= -trading_stock.stop_loss_rate:
        return (True, f"손절 실행 ({profit_rate:.1%})")

    return (False, None)
```

**데이터 소스**: 실시간 현재가 API (메모리 캐시 또는 직접 호출)

### 3. 프로그램 재시작 시 복원 (장중)

**위치**: `main.py:1346-1395`

DB에서 미체결 포지션을 로드하여 메모리에 복원합니다:

```python
# DB에서 미체결 포지션 로드
holdings = self.db_manager.get_virtual_open_positions()

for _, holding in holdings.iterrows():
    quantity = int(holding['quantity'])
    buy_price = float(holding['buy_price'])
    target_profit_rate = holding.get('target_profit_rate', 0.15)  # DB 복원
    stop_loss_rate = holding.get('stop_loss_rate', 0.10)          # DB 복원

    # 포지션 정보 메모리 복원
    trading_stock.set_position(quantity, buy_price)
    trading_stock.target_profit_rate = target_profit_rate
    trading_stock.stop_loss_rate = stop_loss_rate

    # 상태 변경: POSITIONED → 매도 모니터링 활성화
    self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, ...)
```

**복원 항목**: 수량, 매수가, 목표 익절률, 손절률, 상태

## 데이터 저장 전략

### 저장하는 데이터
- **일봉 데이터**: DB에 저장 (`daily_prices` 테이블)
  - 보유 종목은 매일 계속 저장
  - 퀀트 포트폴리오 30개 종목 저장

### 저장하지 않는 데이터
- **분봉 데이터**: 메모리에만 보관 (DB 저장 안 함)
- **현재가**: API로 실시간 조회 (DB 저장 안 함)

## 주요 컴포넌트

### 핵심 파일
- `main.py`: 메인 오케스트레이터 (1,641 lines)
- `core/trading_decision_engine.py`: 매매 판단 엔진
- `core/quant/target_profit_loss_calculator.py`: 동적 목표 익절/손절률 계산기
- `core/trading_stock_manager.py`: 종목 상태 관리
- `db/database_manager.py`: DB 인터페이스
- `config/constants.py`: 시스템 상수 정의

### 상태 전이
```
SELECTED → POSITIONED → SELL_CANDIDATE
```

### 데이터베이스 테이블
- `virtual_trading_records`: 가상매매 기록 (매수/매도, 목표 익절/손절률 포함)
- `daily_prices`: 일봉 가격 데이터
- `quant_portfolio`: 퀀트 포트폴리오 구성 기록
- `quant_factor_scores`: 팩터 점수 기록

## 중요 상수 (config/constants.py)

```python
PORTFOLIO_SIZE = 30                    # 퀀트 포트폴리오 종목 수
QUANT_CANDIDATE_LIMIT = 50             # 장중 퀀트 후보 종목 최대 수
REBALANCING_ORDER_INTERVAL = 0.1       # 리밸런싱 주문 간 대기 시간 (초)
SELL_ORDER_WAIT_TIMEOUT = 300          # 매도 주문 체결 대기 시간 (초, 5분)
ORDER_CHECK_INTERVAL = 5               # 주문 체결 확인 주기 (초)
OHLCV_LOOKBACK_DAYS = 7                # 일봉 조회 기간 (일)
BUY_DECISION_AFTER_CANDLE_CLOSE = 10   # 3분봉 완성 후 매수 대기 시간 (초)
```

## 실행 방법

```bash
python main.py
```

## 레거시 제거 내역

다음 기능들은 과거 전략의 흔적으로 제거되었습니다:
- 3분봉 기술적 매도 로직 (과거 전략)
- `_update_intraday_data()` 메서드 (삭제됨)
- `_generate_post_market_charts()` 메서드 (삭제됨)
- `get_combined_chart_data()` (과거 흔적, 미사용)

## 핵심 원칙

1. **09:05 리밸런싱**: 점수 기반 차등 목표율 계산 → DB 저장
2. **장중 1분마다**: 현재가 API 조회 → 목표가 도달 체크 → 매도 실행
3. **재시작 시**: DB에서 전체 포지션 정보 복원 → 모니터링 재개

프로그램이 재시작되어도 아침에 설정한 동적 목표값이 유지되며, 지속적인 손익절 모니터링이 가능합니다.
