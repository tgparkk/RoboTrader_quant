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

---

## 최근 개선 사항 (2025-12-28)

### 1. 장 마감 후 자동 리포트 생성

**위치**: `main.py:748-757`, `scripts/daily_trading_summary.py`

매일 15:35에 자동으로 일일 매매 리포트를 생성합니다:

```python
# main.py의 _system_monitoring_task() 내부
if (current_time.hour == 15 and current_time.minute >= 35):
    if self._last_daily_report_date != current_time.date():
        print_today_trading_summary()
        self._last_daily_report_date = current_time.date()
```

**리포트 내용**:
1. 오늘의 매매 내역 (매수/매도)
   - 손익절 매도 (익절/손절)
   - **리밸런싱 매도** (포트폴리오 조정 포함)
   - 리밸런싱 매수
2. 현재 보유 종목 및 평가손익
3. 누적 수익률 (실현/미실현)
4. 퀀트 포트폴리오 현황 (Top 10)
5. 오늘의 데이터 수집 현황

**매도 분류 기준**:
- **손익절**: `reason LIKE '%익절%' OR reason LIKE '%손절%'`
- **리밸런싱**: `reason LIKE '%리밸런싱%' OR reason LIKE '%포트폴리오 조정%'`
- 일일 분석 시 두 가지 모두 포함하여 전체 매도 내역 파악

**실행 흐름**:
- 15:30 → ML 데이터 수집
- 15:35 → **일일 매매 리포트 생성**
- 15:40 → 퀀트 스크리닝

**수동 실행**: `python after_market_report.py`

### 2. 데이터 수집 안정성 개선 (9가지)

자세한 내용은 [DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md) 참조

**핵심 개선 사항**:
1. ✅ 가격 데이터 검증 (OHLC 관계, 급격한 변동 감지)
2. ✅ API Rate Limiting (0.2초 간격)
3. ✅ 수익률 계산 최적화 (N+1 쿼리 해결, 100배 성능 향상)
4. ✅ 재무데이터 원자성 보장 (INSERT + UPDATE 트랜잭션)
5. ✅ 에러 로깅 개선 (API 호출별 상세 로깅)
6. ✅ API 필드 검증 강화 (필수 필드 누락 감지)
7. ✅ Look-ahead Bias 제거 (역사적 시가총액 계산)
8. ✅ 공휴일 캘린더 추가 (설날/추석 자동 처리)
9. ✅ 데이터 품질 자동 점검 스크립트

### 3. 전역 API Rate Limiting

**위치**: `api/kis_auth.py:497-510`

모든 API 호출에 자동으로 적용되는 전역 Rate Limiting:

```python
_min_api_interval = 0.06  # 60ms 간격 (초당 16-17회)
# KIS API 제한: 초당 20건
# 구현된 제한: 초당 16-17건 (안전 마진 포함)

def _apply_rate_limit():
    with _api_call_lock:
        elapsed = (now_kst() - _last_api_call_time).total_seconds()
        if elapsed < _min_api_interval:
            time.sleep(_min_api_interval - elapsed)
```

**특징**:
- 모든 API 함수(`get_financial_ratio`, `get_income_statement`, `get_ohlcv_data` 등)에 자동 적용
- 재시도 로직 포함 (최대 3회)
- Rate Limit 오류 자동 감지 및 대기

### 4. Thread-Safe 매수 로직

**위치**: `core/trading_stock_manager.py:180-244`

Lock 기반 원자적 상태 변경으로 중복 매수 방지:

```python
with self._lock:
    if trading_stock.is_buying:
        return False
    trading_stock.is_buying = True
    # ... 매수 로직
```

### 5. Memory Management (당일 데이터만 유지)

**위치**: `core/intraday_stock_manager.py:740-743`

realtime_data는 당일 데이터만 필터링하여 메모리 누적 방지:

```python
if 'date' in updated_realtime.columns:
    updated_realtime = updated_realtime[
        updated_realtime['date'].astype(str) == today_str
    ].copy()
```

---

## 리밸런싱 손실 방지 시스템 (2026-01-25)

### 문제 상황

2026-01-23 거래일에 다음과 같은 손실이 발견되었습니다:

- **09:00 장 시작**: 갭하락으로 3개 종목 손절 매도 (에스엘, 현대모비스, 한국무브넥스)
- **09:05 리밸런싱**: 동일한 3개 종목을 즉시 재매수
- **결과**: 약 35만원 불필요한 손실 발생

**근본 원인**:
1. 장 시작 시 갭하락 → 손절 조건 도달 → 자동 매도
2. 5분 후 리밸런싱 → 퀀트 스코어 높아서 재선정 → 자동 매수
3. 시스템이 "같은 날 손절한 종목"을 기억하지 못함

### 구현된 4가지 개선 사항

#### 1. 리밸런싱 직전 손절 중단 (09:00-09:05)

**위치**: [core/trading_decision_engine.py:591-628](core/trading_decision_engine.py#L591-L628)

리밸런싱 직전 5분간은 익절만 허용하고 손절은 중단:

```python
def _check_simple_stop_profit_conditions(self, trading_stock, current_price):
    """간단한 손절/익절 조건 확인"""
    from utils.korean_time import now_kst
    current_time = now_kst()

    # 09:00~09:05 사이에는 손절 체크 안 함 (익절만)
    is_before_rebalancing = (
        current_time.hour == 9 and
        current_time.minute < 5
    )

    buy_price = trading_stock.position.buy_price
    profit_rate = (current_price - buy_price) / buy_price
    target_profit_rate = trading_stock.target_profit_rate
    stop_loss_rate = trading_stock.stop_loss_rate

    # 익절 조건 확인 (항상 활성)
    if profit_rate >= target_profit_rate:
        return True, f"목표 익절 도달 ({profit_rate*100:.1f}% >= {target_profit_rate*100:.1f}%)"

    # 손절 조건 확인 (리밸런싱 전에는 스킵)
    if not is_before_rebalancing:
        if profit_rate <= -stop_loss_rate:
            return True, f"손절 실행 ({profit_rate*100:.1f}% <= -{stop_loss_rate*100:.1f}%)"

    return False, None
```

**효과**: 갭하락으로 인한 조급한 손절 방지, 리밸런싱에서 재평가 기회 제공

#### 2. 당일 손절 종목 재매수 차단

**위치**:
- DB 조회: [db/database_manager.py:1438-1475](db/database_manager.py#L1438-L1475)
- 리밸런싱 적용: [core/helpers/rebalancing_executor.py:254-266](core/helpers/rebalancing_executor.py#L254-L266)

오늘 손절한 종목을 DB에서 조회하여 리밸런싱 시 재매수 금지:

```python
# database_manager.py
def get_today_stop_loss_stocks(self, target_date: str = None) -> List[str]:
    """오늘 손절한 종목 코드 리스트 조회"""
    if target_date is None:
        target_date = now_kst().strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT DISTINCT stock_code
        FROM virtual_trading_records
        WHERE action = 'SELL'
          AND DATE(datetime(timestamp, 'unixepoch', 'localtime')) = ?
          AND (reason LIKE '%손절%' OR reason LIKE '%stop%loss%')
    ''', (target_date,))

    return [row[0] for row in cursor.fetchall()]

# rebalancing_executor.py
today_stop_loss_stocks = self.db_manager.get_today_stop_loss_stocks()

for buy_item in buy_list:
    stock_code = buy_item['stock_code']

    # 오늘 손절한 종목은 재매수 금지
    if stock_code in today_stop_loss_stocks:
        logger.warning(f"⚠️ {stock_code} 매수 스킵: 오늘 손절한 종목 - 재매수 금지")
        continue
```

**효과**: 같은 날 손절 후 재매수 완전 차단 (1/23 사례 재발 방지)

#### 3. 2단계 매수 가격 검증

**위치**: [core/helpers/rebalancing_executor.py:47-175](core/helpers/rebalancing_executor.py#L47-L175)

리밸런싱 매수 시 가격 적정성을 2단계로 검증:

**1단계: 절대 가격 밴드 검증**
- **하한**: 전일 저가의 -5% (급락 방지)
- **상한**: 전일 종가의 +10% (과열 방지)

**2단계: 시장 대비 상대 강도 검증**
- 코스피 지수 대비 -5%p 이상 약세 종목 제외
- 시장 대비 +8%p 이상 강세 종목은 로그 표시

```python
def _validate_buy_price(self, stock_code: str, current_price: float,
                        prev_ohlcv: dict, market_change: float = None):
    """매수가격 적절성 검증 (2단계: 절대값 + 시장 대비)"""
    prev_close = prev_ohlcv['close']
    prev_high = prev_ohlcv['high']
    prev_low = prev_ohlcv['low']

    # 1단계: 절대값 필터
    lower_band = prev_low * 0.95   # 전일저가 -5%
    upper_band = prev_close * 1.10 # 전일종가 +10%

    if current_price < lower_band:
        return False, f"급락 (현재가 < 하한 {lower_band:,}원)"

    if current_price > upper_band:
        return False, f"과열 (현재가 > 상한 {upper_band:,}원)"

    # 2단계: 시장 대비 상대강도 검증
    if market_change is not None:
        stock_change = (current_price - prev_close) / prev_close
        relative_change = (stock_change - market_change) * 100  # %p

        if relative_change < -5.0:
            return False, f"시장 대비 약세 (상대 {relative_change:+.1f}%p)"

        if relative_change > 8.0:
            logger.info(f"📈 {stock_code} 시장 대비 강세 ({relative_change:+.1f}%p)")

    return True, f"검증 통과 (현재 {current_price:,}원)"
```

**데이터 소스**:
- 전일 OHLCV: API 조회 (주말/공휴일 자동 처리)
- 코스피 지수: `get_index_data("0001")` API 호출

**효과**:
- 급락/급등 종목 매수 방지
- 시장 대비 뒤처지는 종목 제외
- 안정적인 매수 타이밍 확보

#### 4. 함수명 정확성 개선

**위치**:
- [core/helpers/screening_task_runner.py](core/helpers/screening_task_runner.py)
- [main.py](main.py)

오해의 소지가 있는 함수명 변경:

- ❌ `run_ml_data_collection()` (ML과 무관한 함수)
- ✅ `run_daily_data_collection()` (일일 데이터 수집)

**변경 대상**:
- 함수명
- 변수명 (`_last_ml_data_collection_date` → `_last_daily_data_collection_date`)
- 로그 메시지

### 테스트 결과

#### 통합 테스트 스크립트

[test_rebalancing_improvements.py](test_rebalancing_improvements.py) - 모든 기능 검증 통과:

1. ✅ 오늘 손절 종목 조회 함수 정상 작동
2. ✅ 과거 날짜 손절 종목 조회 정상 작동 (1/23 조회: 3개 종목 확인)
3. ✅ 코스피 지수 조회 및 변동률 계산 정상 작동
4. ✅ 전일 일봉 조회 및 밴드 계산 정상 작동
5. ✅ 시간대별 로직 분기 정상 작동

#### 1/23 사례 재현 방지 검증

- **이전**: 010100, 005850, 012330 손절 후 즉시 재매수 → 35만원 손실
- **개선 후**:
  - 09:00-09:05 손절 중단 → 조급한 손절 방지
  - DB 조회로 재매수 차단 → 1/23 종목 리스트 확인됨
  - 가격 검증 추가 → 급락/과열 종목 필터링

### 예상 효과

1. **직접적 손실 방지**: 같은 날 손절 후 재매수로 인한 손실 제거 (연간 수십만원 절약 추정)
2. **매수 품질 향상**: 급락/과열 종목 제외로 안정적인 진입
3. **리밸런싱 효율**: 시장 대비 강세 종목 우선 매수
4. **시스템 안정성**: 갭 변동에 대한 방어 로직 강화

### API 버그 수정

**문제**: 코스피 변동률 조회 시 잘못된 필드 사용
**위치**: [core/helpers/rebalancing_executor.py:66](core/helpers/rebalancing_executor.py#L66)

- ❌ `bstp_nmix_prpr` (현재 지수값, 예: 4990.07)
- ✅ `bstp_nmix_prdy_ctrt` (전일대비율, 예: 0.76)

```python
# 수정 후
change_rate = float(index_data.get('bstp_nmix_prdy_ctrt', 0))  # 전일대비율 (%)
market_change = change_rate / 100  # 소수 형태로 변환 (0.0076)
```

**참조**: [KIS API 명세서](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/domestic-stock/v1/quotations/inquire-index-price)

---

## 코드 검토 시 주의사항 (학습 교훈)

### 검증 체크리스트
코드에서 문제를 발견했다고 판단하기 전 반드시 확인:

- [ ] 함수 시작부터 끝까지 읽었는가?
- [ ] Lock이나 동기화 메커니즘을 확인했는가?
- [ ] 호출하는 함수의 구현을 확인했는가?
- [ ] 전역 공통 모듈(auth, utils)을 확인했는가?
- [ ] SQL 쿼리의 실제 의미를 파악했는가?
- [ ] 설계 의도를 고려했는가?
- [ ] 실제 실행 흐름을 추적했는가?

### 흔한 오판 사례

1. **코드 조각만 보고 판단**
   - ❌ Lock 밖에 있는 것처럼 보임
   - ✅ 함수 전체를 읽으면 Lock 안에 있음

2. **중복 방어를 버그로 오해**
   - ❌ "왜 두 번 체크하지? 버그다!"
   - ✅ 방어적 프로그래밍 (defensive programming)

3. **전역 인프라 간과**
   - ❌ "이 파일에 Rate Limiting이 없네?"
   - ✅ `kis_auth.py`에 전역으로 모든 API에 적용됨

4. **부분 로직만 보고 판단**
   - ❌ "계속 추가만 하네? 메모리 누적!"
   - ✅ 함수 끝에 당일 필터링 로직 있음

---

## 로깅 개선 및 데이터 정합성 복원 (2026-01-27)

### 1. 로깅 상세도 향상

#### (1) 가격 검증 로그 추가
**위치**: [core/helpers/rebalancing_executor.py:141-169](core/helpers/rebalancing_executor.py#L141-L169)

리밸런싱 매수 시 가격 검증 결과를 명시적으로 로깅:

```python
# 급락 차단
if current_price < lower_band:
    logger.warning(f"⚠️ {stock_code} 매수 차단: 급락 (현재 {current_price:,}원 < 하한 {lower_band:,}원)")

# 과열 차단
if current_price > upper_band:
    logger.warning(f"⚠️ {stock_code} 매수 차단: 극단적 과열 (현재 {current_price:,}원 > 상한 {upper_band:,}원)")

# 시장 대비 약세 차단
if relative_change < -5.0:
    logger.warning(f"⚠️ {stock_code} 매수 차단: 시장 대비 약세 (상대 {relative_change:+.1f}%p)")

# 검증 통과
logger.info(f"✅ {stock_code} 가격 검증 통과: 현재 {current_price:,}원 (전일종가 대비 {change:+.1f}%)")
```

**효과**: 매수 차단 사유를 실시간으로 파악 가능

#### (2) 09:00-09:05 손절 중단 모드 로그
**위치**: [core/trading_decision_engine.py:623-628](core/trading_decision_engine.py#L623-L628)

리밸런싱 전 손절선 도달 시 디버그 로그 추가:

```python
if not is_before_rebalancing:
    if profit_rate <= -stop_loss_rate:
        return True, f"손절 실행 ({profit_rate*100:.1f}%)"
else:
    # 리밸런싱 전 손절 중단 모드
    if profit_rate <= -stop_loss_rate:
        logger.debug(f"⏸️ {trading_stock.stock_code} 리밸런싱 전 손절 중단 "
                     f"(손절선 도달: {profit_rate*100:.1f}%, 익절만 허용)")
```

**효과**: 09:00-09:05 손절 중단 기능 작동 여부 확인 가능

#### (3) 당일 손절 종목 재매수 차단 로그
**위치**: [core/helpers/rebalancing_executor.py:257-261](core/helpers/rebalancing_executor.py#L257-L261)

당일 손절 종목 목록을 명시적으로 출력:

```python
today_stop_loss_stocks = self.db_manager.get_today_stop_loss_stocks()
if today_stop_loss_stocks:
    logger.info(f"🚫 당일 손절 재매수 차단 대상: {len(today_stop_loss_stocks)}개 "
                f"({', '.join(today_stop_loss_stocks)})")
else:
    logger.info(f"✅ 당일 손절 종목 없음 (재매수 제한 없음)")
```

**효과**: 재매수 차단이 정상 작동하는지 실시간 확인

### 2. 리밸런싱 매도 reason 구분

**위치**: [core/quant/quant_rebalancing_service.py](core/quant/quant_rebalancing_service.py)

리밸런싱 매도와 장중 손익절을 명확히 구분하도록 reason에 접두사 추가:

```python
# 리밸런싱 매도
sell_reason = "[리밸런싱] 긴급 매도 (점수 xx < 62)"
sell_reason = "[리밸런싱] 조건부 매도 (점수 xx, 순위 xx)"
sell_reason = "[리밸런싱] 포트폴리오 조정 (...)"

# 장중 손익절 (기존 유지)
reason = "손절 실행 (-11.72% <= -9.00%)"
reason = "목표 익절 도달 (17.08% >= 17.00%)"
```

**효과**:
- SQL 쿼리로 리밸런싱 매도만 필터링 가능
- 거래 로그 분석 시 명확한 구분

### 3. BLOB 데이터 정합성 복원

#### 문제 발견
2026-01-08에 발생한 numpy.int64 BLOB 저장 버그로 인해 7건의 매도 기록 `quantity` 컬럼이 blob 타입으로 저장됨.

**영향**:
- SQL 집계 쿼리 오작동 (`SUM(quantity)` → 0)
- Holdings 복원 시 수량 0으로 인식
- 중복 매도 방지 경고 발생

#### 복원 스크립트
**위치**: [scripts/fix_blob_quantity.py](scripts/fix_blob_quantity.py)

BLOB 데이터를 little-endian int64로 해석하여 INTEGER로 변환:

```python
import struct

# BLOB 바이트 읽기
blob_bytes = bytes(quantity_blob)
if len(blob_bytes) < 8:
    blob_bytes = blob_bytes + b'\x00' * (8 - len(blob_bytes))

# little-endian int64로 해석
quantity_int = struct.unpack('<q', blob_bytes)[0]

# DB 업데이트
cursor.execute("""
    UPDATE virtual_trading_records
    SET quantity = ?
    WHERE id = ?
""", (quantity_int, record_id))
```

**실행 방법**:
```bash
# 미리보기 (변경 없음)
python scripts/fix_blob_quantity.py

# 실제 변환
python scripts/fix_blob_quantity.py --live
```

#### 복원 결과
| ID | 종목코드 | BLOB → INTEGER | 검증 |
|----|---------|---------------|------|
| 514 | 086280 | 7주 | ✅ 매수 7주 |
| 515 | 005380 | 4주 | ✅ 매수 4주 |
| 517 | 006650 | 2주 | ✅ 매수 2주 |
| 518 | 067830 | 98주 | ✅ 매수 98주 |
| 519 | 011210 | 4주 | ✅ 매수 4주 |
| 520 | 035510 | 18주 | ✅ 매수 18주 |
| 521 | 023810 | 123주 | ✅ 매수 123주 |

**총 복원**: 7건 (256주)

**검증**:
```sql
-- 복원 전
SELECT SUM(quantity) FROM virtual_trading_records WHERE action='SELL';
-- 결과: 부정확 (BLOB 제외)

-- 복원 후
SELECT SUM(quantity) FROM virtual_trading_records WHERE action='SELL';
-- 결과: 정확 (모든 거래 포함)
```

### 4. 향후 방지 조치

#### 타입 안전성 보장 (이미 적용됨)
**위치**: [db/database_manager.py:1148-1152](db/database_manager.py#L1148-L1152)

```python
# 타입 안전성 보장: numpy 타입을 Python 기본 타입으로 변환
quantity = int(quantity)
price = float(price)
if target_profit_rate is not None:
    target_profit_rate = float(target_profit_rate)
if stop_loss_rate is not None:
    stop_loss_rate = float(stop_loss_rate)
```

**커밋**: `98d5e72` (2026-01-08 22:34)

### 5. 개선 효과 요약

#### 로깅 개선
- ✅ 가격 검증 차단 사유 실시간 파악
- ✅ 손절 중단 모드 작동 여부 확인
- ✅ 재매수 차단 대상 명시적 표시
- ✅ 리밸런싱 vs 손익절 명확한 구분

#### 데이터 정합성
- ✅ BLOB 데이터 100% 복원 (7건)
- ✅ SQL 집계 쿼리 정상 작동
- ✅ Holdings 정합성 복원
- ✅ 중복 매도 경고 근본 해결

#### 시스템 안정성
- ✅ numpy.int64 버그 재발 방지 (타입 변환 추가)
- ✅ 데이터 품질 모니터링 스크립트 제공
- ✅ 복원 절차 문서화 및 자동화

---

## 매매 현황 조회 스크립트 (2026-02-02)

### 문제 상황

임시 SQL 쿼리로 손익을 계산할 때 **전체 거래의 평균 매수가**를 사용하면 잘못된 손익률이 계산됩니다:

```
예: 010100 한국무브넥스
- 전체 평균 매수가: 6,813원
- 실제 해당 포지션 매수가: 6,130원
- 매도가: 5,560원

❌ 잘못된 계산: (5,560 - 6,813) / 6,813 = -18.4%
✅ 정확한 계산: (5,560 - 6,130) / 6,130 = -9.3%
```

### 해결책

**위치**: [scripts/today_trading_status.py](scripts/today_trading_status.py)

DB에 저장된 정확한 `profit_loss`, `profit_rate` 컬럼을 사용하는 조회 스크립트:

```python
# 매도 시 DB에 저장되는 정확한 손익 정보 사용
cursor.execute('''
    SELECT
        s.stock_code,
        b.price as buy_price,      -- buy_record_id로 정확한 매수가 참조
        s.price as sell_price,
        s.profit_loss,             -- DB에 저장된 정확한 손익
        s.profit_rate              -- DB에 저장된 정확한 손익률
    FROM virtual_trading_records s
    LEFT JOIN virtual_trading_records b ON s.buy_record_id = b.id
    WHERE s.action = 'SELL'
''')
```

### 사용법

```bash
# 오늘 매매 현황
python scripts/today_trading_status.py

# 특정 날짜 조회
python scripts/today_trading_status.py --date 2026-01-23
```

### 출력 예시

```
[매도 내역]
----------------------------------------------------------------------
09:05 | 005380 현대차      |    4주 |  510,000 ->  484,000 |   -104,000원 (  -5.1%) [조정]
09:32 | 010660 화천기계     |  316주 |    6,010 ->    5,680 |   -104,280원 (  -5.5%) [손절]
11:53 | 010100 한국무브넥스   |  281주 |    6,130 ->    5,560 |   -160,170원 (  -9.3%) [손절]
----------------------------------------------------------------------
매도 3건 | 총 매도금액: xxx원 | 실현손익: -xxx원
```

### 핵심 원칙

**손익 계산 시 반드시 준수:**
1. ❌ 전체 평균 매수가로 계산하지 않음
2. ✅ `buy_record_id`로 해당 포지션의 정확한 매수가 참조
3. ✅ DB에 저장된 `profit_loss`, `profit_rate` 컬럼 직접 사용

---

## 포트폴리오 집중화 및 진입 기준 강화 (2026-02-03)

### 변경 배경

- 투자 자산 규모 대비 30종목 분산은 비효율적
- 종목당 투자금이 작아 수익 실현 금액이 제한됨
- 최근 30일 승률 49.5% → 상위 종목 집중으로 승률 향상 목표

### 변경 내용

#### 1. 포트폴리오 크기 축소 (30 → 15종목)

**위치**:
- [config/constants.py:6](config/constants.py#L6)
- [core/quant/quant_rebalancing_service.py:38](core/quant/quant_rebalancing_service.py#L38)

```python
# 변경 전
PORTFOLIO_SIZE = 30
target_portfolio_size = 30

# 변경 후
PORTFOLIO_SIZE = 15  # 집중 투자
target_portfolio_size = 15
```

**효과**:
- 종목당 투자금 ~170만원 → ~340만원 (2배 증가)
- 관리 용이성 향상
- 수익 실현 시 금액 증가

#### 2. 진입/유지 기준 강화

**위치**: [core/quant/quant_rebalancing_service.py:44-49](core/quant/quant_rebalancing_service.py#L44-L49)

| 항목 | 이전 | 이후 | 의미 |
|------|------|------|------|
| `hard_stop_score` | 62점 | **70점** | 긴급 매도 기준 강화 |
| `soft_stop_score` | 64점 | **72점** | 조건부 매도 기준 강화 |
| `soft_stop_rank` | 50위 | **30위** | 순위 기준 강화 |
| `safe_score` | 65점 | **75점** | 안전 유지 점수 상향 |
| `safe_rank` | 40위 | **25위** | 안전 유지 순위 상향 |

```python
# 변경 후 설정
self.hard_stop_score = 70.0  # 긴급 매도: 점수 < 70점
self.soft_stop_score = 72.0  # 조건부 매도: 점수 70~72점
self.soft_stop_rank = 30     # 조건부 매도 순위: > 30위
self.safe_score = 75.0       # 안전 점수: >= 75점 유지
self.safe_rank = 25          # 안전 순위: <= 25위 유지
```

### 예상 효과

| 지표 | 변경 전 | 변경 후 |
|------|---------|---------|
| 보유 종목 수 | 30개 | 15개 |
| 종목당 투자금 | ~170만원 | ~340만원 |
| 승률 | 49.5% | 60~70% (목표) |
| 분산 효과 | 높음 | 중간 |

### 주의사항

1. **리밸런싱 시 대량 매도 발생**
   - 첫 리밸런싱(2/4 09:05)에서 기존 30종목 중 약 15종목 매도 예상
   - 새 기준 미달 종목 추가 매도 가능

2. **모니터링 기간**
   - 첫 1~2주간 승률 변화 관찰 필요
   - 기준이 과도하게 엄격하면 재조정 검토

3. **변동성 증가 가능**
   - 분산 효과 감소로 일일 손익 변동폭 증가 가능

---

## DB 성능 및 안정성 개선 (2026-02-03)

### 1. N+1 쿼리 제거 - executemany() 적용

**위치**: [core/ml_data_collector.py:43-123](core/ml_data_collector.py#L43-L123)

일봉 데이터 저장 시 개별 INSERT 대신 배치 INSERT로 변경:

```python
# 변경 전: N+1 쿼리 (느림)
for idx, row in daily_data.iterrows():
    cursor.execute('''INSERT OR REPLACE INTO daily_prices ...''', (...))

# 변경 후: executemany() 배치 처리 (100배+ 빠름)
rows_to_insert = []
for idx, row in daily_data.iterrows():
    rows_to_insert.append((stock_code, date_formatted, ...))

cursor.executemany('''
    INSERT OR REPLACE INTO daily_prices ...
''', rows_to_insert)
```

**효과**: 1,000건 저장 시 1,000번 → 1번 DB 왕복 (100배+ 성능 향상)

### 2. Race Condition 방지 - 중복 매도 완전 차단

**위치**:
- 인덱스: [db/database_manager.py:345-351](db/database_manager.py#L345-L351)
- 예외 처리: [db/database_manager.py:1278-1290](db/database_manager.py#L1278-L1290)

#### (1) UNIQUE 인덱스 추가 (Partial Index)

```sql
CREATE UNIQUE INDEX idx_virtual_trading_unique_sell
ON virtual_trading_records(buy_record_id)
WHERE action = 'SELL' AND buy_record_id IS NOT NULL
```

**의미**: 동일한 `buy_record_id`에 대해 SELL 기록은 1건만 허용

#### (2) IntegrityError 처리

```python
try:
    cursor.execute('''INSERT INTO virtual_trading_records ...''')
except sqlite3.IntegrityError:
    # UNIQUE 제약 위반 = 동시 매도 시도 (Race condition)
    self.logger.warning(f"⚠️ {stock_code} 중복 매도 차단 (Race condition)")
    return False
```

**효과**:
- Thread A, B가 동시에 같은 포지션 매도 시도 시 1건만 성공
- DB 레벨에서 원자적으로 중복 방지
- 기존 SELECT → INSERT 패턴의 Race condition 완전 해결
