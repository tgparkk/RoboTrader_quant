# RoboTrader 퀀트 자동매매 시스템

한국투자증권 API를 사용한 **퀀트 팩터 기반 자동매매 시스템**입니다.

- **전략**: 멀티팩터 퀀트 스코어링 + 점수 기반 동적 손익절
- **리밸런싱**: 매일 09:05 자동 실행
- **모드**: 가상매매 / 실제매매 지원
- **안정성**: 프로그램 재시작 시 포지션 자동 복원

---

## 📋 목차

1. [시스템 개요](#시스템-개요)
2. [핵심 기능](#핵심-기능)
3. [프로그램 실행 흐름](#프로그램-실행-흐름)
4. [시간대별 자동 작업](#시간대별-자동-작업)
5. [매매 전략](#매매-전략)
6. [설치 및 실행](#설치-및-실행)
7. [주요 컴포넌트](#주요-컴포넌트)
8. [데이터베이스 구조](#데이터베이스-구조)
9. [설정](#설정)
10. [문서](#문서)

---

## 시스템 개요

### 핵심 특징

- **멀티팩터 퀀트 전략**: Value, Quality, Momentum, Growth 4가지 팩터 복합 평가
- **동적 손익절**: 종목별 점수에 따라 차등 익절률(12-20%) / 손절률(8-10%) 적용
- **일간 리밸런싱**: 매일 09:05 포트폴리오 자동 재조정
- **실시간 모니터링**: 장중 3초마다 손익절 조건 체크
- **자동 복원**: 프로그램 재시작 시 모든 포지션 및 설정 자동 복원

### 시스템 구조

```
RoboTrader 퀀트 시스템
│
├─ 데이터 수집 (15:30)
│  ├─ 일봉 가격 데이터
│  └─ 재무 데이터
│
├─ 퀀트 스크리닝 (15:40)
│  ├─ 4가지 팩터 계산
│  ├─ 복합 점수 산출
│  └─ 상위 30개 종목 선정
│
├─ 리밸런싱 (09:05)
│  ├─ 점수 기반 매도 판단
│  ├─ 신규 매수 종목 선정
│  └─ 동적 손익절률 설정
│
└─ 장중 모니터링 (09:05-15:00)
   ├─ 실시간 손익절 체크 (3초마다)
   └─ 조건 만족 시 자동 매도
```

---

## 핵심 기능

### 1. 퀀트 팩터 기반 종목 선정

4가지 팩터를 종합 평가하여 상위 30개 종목 선정:

| 팩터 | 평가 요소 | 가중치 |
|------|---------|--------|
| **Value** | PER, PBR, PSR | 25% |
| **Quality** | ROE, 부채비율, 매출성장 | 25% |
| **Momentum** | 12개월 모멘텀, 변동성 | 25% |
| **Growth** | 매출/이익 성장률 | 25% |

### 2. 점수 기반 동적 손익절

종목별 복합 점수에 따라 차등 목표 설정:

```python
복합점수 = (포트폴리오 순위 40%) + (팩터 점수 30%) + (모멘텀 30%)

# 등급별 목표율
S등급 (80점 이상):  익절 20%, 손절 8%
A등급 (65-79점):   익절 17%, 손절 9%
B등급 (50-64점):   익절 15%, 손절 10%
C등급 (35-49점):   익절 13%, 손절 10%
D등급 (35점 미만):  익절 12%, 손절 10%
```

### 3. 자동 리밸런싱 (09:05)

매일 아침 포트폴리오를 자동으로 재조정:

1. **매도 판단** (점수 기반 3단계)
   - 긴급 매도: 점수 62점 미만
   - 조건부 매도: 점수 64점 미만 + 순위 50위 밖
   - 안전 유지: 점수 65점 이상 또는 순위 40위 이내

2. **매수 실행**
   - 목표 포트폴리오에는 있지만 현재 미보유 종목
   - 동등 비중 배분

3. **유지 종목 관리**
   - 목표 익절/손절률 재계산 및 업데이트

### 4. 실시간 손익절 모니터링

장중 3초마다 모든 보유 종목의 손익 확인:

```python
현재 수익률 = (현재가 - 매수가) / 매수가

if 현재 수익률 >= 목표 익절률:
    → 즉시 매도 (익절)

if 현재 수익률 <= -목표 손절률:
    → 즉시 매도 (손절)
```

---

## 프로그램 실행 흐름

### 프로그램 생애주기

```
시작: python main.py
  ↓
1. 초기화 (DayTradingBot.__init__)
  ├─ API 매니저 생성
  ├─ DB 매니저 생성
  ├─ 주문 관리자 생성
  ├─ 매매 판단 엔진 생성
  └─ 리밸런싱 서비스 생성
  ↓
2. 시스템 초기화 (initialize)
  ├─ API 연결 확인
  ├─ 계좌 잔고 조회
  ├─ DB에서 후보 종목 복원
  └─ DB에서 보유 종목 복원 (포지션 + 목표율)
  ↓
3. 메인 루프 실행 (run_daily_cycle)
  ├─ 6개 비동기 태스크 병렬 실행:
  │  1) 데이터 수집 태스크
  │  2) 주문 모니터링 태스크
  │  3) 종목 상태 모니터링 (3초마다)
  │  4) 시스템 모니터링 (5초마다)
  │  5) 텔레그램 태스크
  │  6) 리밸런싱 태스크 (09:05 정각)
  └─ 무한 루프 (is_running = True)
  ↓
4. 종료 (Ctrl+C 또는 시스템 종료)
  ├─ 모든 태스크 중단
  ├─ API 연결 종료
  └─ PID 파일 삭제
```

### 상태 머신

종목은 다음 상태를 순환합니다:

```
SELECTED (조건검색 선정)
   ↓ [리밸런싱 매수 신호]
BUY_PENDING (매수 주문 중)
   ↓ [체결 확인]
POSITIONED (포지션 보유)
   ↓ [손익절 조건 만족]
SELL_CANDIDATE (매도 후보)
   ↓ [매도 주문 실행]
SELL_PENDING (매도 주문 중)
   ↓ [체결 확인]
COMPLETED (거래 완료)
   ↓ [재거래 허용]
SELECTED (다시 매수 대상으로)
```

---

## 시간대별 자동 작업

| 시간 | 작업 | 내용 | 주기 |
|------|------|------|------|
| **08:50** | 시스템 시작 | - 프로그램 실행 권장 시간<br>- 포지션 복원<br>- API 연결 확인 | 수동 |
| **09:05** | 리밸런싱 | - 점수 기반 매도 판단<br>- 신규 매수 실행<br>- 유지 종목 목표율 갱신 | 1회 |
| **09:05-15:00** | 장중 모니터링 | - 손익절 조건 체크 (3초마다)<br>- 조건 만족 시 즉시 매도 | 연속 |
| **15:00** | 장마감 청산 | - 모든 포지션 시장가 전량 매도<br>- (설정에 따라 비활성화 가능) | 1회 |
| **15:30** | 데이터 수집 | - 일봉 가격 데이터 수집<br>- 재무 데이터 수집<br>- 보유 종목 우선 수집 | 1회 |
| **15:35** | 리포트 생성 | - 일일 매매 내역 정리<br>- 손익 집계<br>- 텔레그램 알림 | 1회 |
| **15:40** | 퀀트 스크리닝 | - 전체 종목 팩터 계산<br>- 상위 30개 종목 선정<br>- DB 저장 (내일 리밸런싱용) | 1회 |

---

## 매매 전략

### 1. 종목 선정 기준

**1차 필터링** (기본 조건)
- 시가총액 500억원 이상
- 거래대금 10억원 이상
- 상장 1년 이상
- 관리종목/정리매매 제외

**2차 평가** (퀀트 팩터)
- Value: PER, PBR, PSR 저평가
- Quality: ROE 높음, 부채비율 낮음
- Momentum: 12개월 수익률 양호
- Growth: 매출/이익 성장률 높음

**최종 선정**
- 복합 점수 상위 30개 종목

### 2. 매수 전략

**리밸런싱 매수 (09:05)**
- 목표 포트폴리오 30개 종목 중 미보유 종목
- 동등 비중 배분 (1/30)
- 시장가 매수
- 종목별 동적 목표 익절/손절률 설정

**포지션 크기**
```
종목당 투자금 = 총 투자 가능 금액 / 30
매수 수량 = 종목당 투자금 / 현재가
```

### 3. 매도 전략

**리밸런싱 매도 (09:05)**
- 점수 62점 미만: 긴급 전량 매도
- 점수 64점 미만 + 순위 50위 밖: 조건부 매도
- 점수 65점 이상 또는 순위 40위 이내: 유지

**손익절 매도 (장중)**
- 익절: 목표 익절률 도달 시 전량 매도
- 손절: 목표 손절률 도달 시 전량 매도

**장마감 청산 (15:00, 선택적)**
- 모든 포지션 시장가 전량 매도
- 설정으로 활성화/비활성화 가능

---

## 설치 및 실행

### 필수 요구사항

- Python 3.8 이상
- 한국투자증권 API 키 (APP_KEY, APP_SECRET)
- SQLite3

### 설치

```bash
# 1. 저장소 클론
git clone <repository_url>
cd RoboTrader_quant

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 설정 파일 생성
cp config/app_config.json.example config/app_config.json

# 4. API 키 설정
# config/app_config.json 편집
{
  "app_key": "YOUR_APP_KEY",
  "app_secret": "YOUR_APP_SECRET",
  "account_number": "YOUR_ACCOUNT_NUMBER"
}
```

### 실행

```bash
# 메인 프로그램 실행
python main.py

# 장 마감 후 리포트만 확인
python after_market_report.py

# 데이터 품질 점검
python scripts/check_data_quality.py

# 치명적 버그 검증
python verify_critical_fixes.py
```

### 가상매매 vs 실제매매

```python
# core/trading_decision_engine.py
self.is_virtual_mode = True   # 가상매매 (테스트)
self.is_virtual_mode = False  # 실제매매 (운영)
```

---

## 주요 컴포넌트

### 핵심 파일 구조

```
RoboTrader_quant/
├─ main.py (1,732 lines)              # 메인 오케스트레이터
├─ config/
│  ├─ settings.py                     # 설정 로드
│  ├─ constants.py                    # 시스템 상수
│  └─ market_hours.py                 # 시장 시간 관리
├─ core/
│  ├─ trading_stock_manager.py        # 종목 상태 관리
│  ├─ trading_decision_engine.py      # 매매 판단 엔진
│  ├─ order_manager.py                # 주문 실행/관리
│  ├─ intraday_stock_manager.py       # 분봉 데이터 관리
│  ├─ ml_data_collector.py            # 데이터 수집
│  └─ quant/
│     ├─ quant_screening_service.py   # 퀀트 스크리닝
│     ├─ quant_rebalancing_service.py # 리밸런싱 실행
│     └─ target_profit_loss_calculator.py  # 동적 손익절률
├─ db/
│  ├─ database_manager.py             # DB 인터페이스
│  └─ quant_db_manager.py             # 퀀트 DB 관리
├─ api/
│  ├─ kis_api_manager.py              # KIS API 매니저
│  ├─ kis_auth.py                     # 인증 및 Rate Limiting
│  ├─ kis_order_api.py                # 주문 API
│  ├─ kis_current_price_api.py        # 현재가 API
│  └─ kis_financial_api.py            # 재무 데이터 API
├─ scripts/
│  ├─ daily_trading_summary.py        # 일일 리포트 생성
│  └─ check_data_quality.py           # 데이터 품질 점검
└─ utils/
   ├─ korean_time.py                  # 한국 시간 유틸리티
   └─ korean_holidays.py              # 공휴일 캘린더
```

### 컴포넌트 역할

| 컴포넌트 | 역할 |
|---------|------|
| **TradingStockManager** | 종목 상태 관리, 주문 실행, 체결 확인 |
| **TradingDecisionEngine** | 매수/매도 판단, 손익절 조건 체크 |
| **OrderManager** | 주문 전송, 체결 모니터링 |
| **IntradayStockManager** | 분봉 데이터 수집 및 관리 |
| **QuantRebalancingService** | 리밸런싱 계획 수립 및 실행 |
| **MLDataCollector** | 일봉/재무 데이터 수집 |
| **DatabaseManager** | DB 읽기/쓰기 통합 인터페이스 |
| **KISAPIManager** | 한국투자증권 API 래퍼 |

---

## 데이터베이스 구조

### 주요 테이블

#### 1. virtual_trading_records (가상매매 기록)

```sql
CREATE TABLE virtual_trading_records (
    id INTEGER PRIMARY KEY,
    stock_code TEXT,
    stock_name TEXT,
    action TEXT,              -- 'BUY' or 'SELL'
    quantity INTEGER,
    price REAL,
    timestamp TEXT,
    strategy TEXT,
    reason TEXT,
    profit_loss REAL,         -- 매도 시 손익
    profit_rate REAL,         -- 매도 시 수익률
    target_profit_rate REAL,  -- 리밸런싱 매수 시 설정
    stop_loss_rate REAL,      -- 리밸런싱 매수 시 설정
    buy_record_id INTEGER,    -- 매도 시 매수 기록 연결
    is_test INTEGER,          -- 가상매매 플래그
    created_at TEXT
);
```

#### 2. daily_prices (일봉 데이터)

```sql
CREATE TABLE daily_prices (
    stock_code TEXT,
    date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    market_cap INTEGER,       -- 시가총액 (종가 기준 계산)
    returns_1d REAL,
    returns_5d REAL,
    returns_20d REAL,
    volatility_20d REAL,
    PRIMARY KEY (stock_code, date)
);
```

#### 3. quant_portfolio (퀀트 포트폴리오)

```sql
CREATE TABLE quant_portfolio (
    stock_code TEXT,
    stock_name TEXT,
    rank INTEGER,
    total_score REAL,
    value_score REAL,
    quality_score REAL,
    momentum_score REAL,
    growth_score REAL,
    calc_date TEXT,
    PRIMARY KEY (stock_code, calc_date)
);
```

#### 4. financial_statements (재무제표)

```sql
CREATE TABLE financial_statements (
    stock_code TEXT,
    statement_date TEXT,
    revenue REAL,
    operating_income REAL,
    net_income REAL,
    total_assets REAL,
    total_equity REAL,
    total_liabilities REAL,
    roe REAL,
    liability_ratio REAL,
    per REAL,
    pbr REAL,
    PRIMARY KEY (stock_code, statement_date)
);
```

---

## 설정

### 주요 설정 파일

#### config/constants.py

```python
# 포트폴리오 설정
PORTFOLIO_SIZE = 30                    # 보유 종목 수
QUANT_CANDIDATE_LIMIT = 50             # 후보 종목 최대 수

# 리밸런싱 설정
REBALANCING_ORDER_INTERVAL = 0.1       # 주문 간 대기 (초)

# 주문 설정
SELL_ORDER_WAIT_TIMEOUT = 300          # 매도 체결 대기 (초)
ORDER_CHECK_INTERVAL = 5               # 체결 확인 주기 (초)

# 데이터 설정
OHLCV_LOOKBACK_DAYS = 7                # 일봉 조회 기간 (일)
```

#### config/market_hours.py

```python
# 시장 시간 설정
MARKET_OPEN = time(9, 0)               # 장 시작
MARKET_CLOSE = time(15, 30)            # 장 마감
REBALANCING_TIME = time(9, 5)          # 리밸런싱 시각
EOD_LIQUIDATION_TIME = time(15, 0)     # 장마감 청산 시각
```

### 가상매매 설정

```python
# core/trading_decision_engine.py
self.is_virtual_mode = True            # 가상매매 활성화

# core/fund_manager.py
VIRTUAL_INITIAL_CAPITAL = 10_000_000   # 가상 초기 자금 (천만원)
```

---

## 문서

### 시스템 문서

- [CLAUDE.md](CLAUDE.md) - 시스템 아키텍처 및 핵심 동작 흐름
- [DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md) - 데이터 수집 개선 사항 (9가지)
- [CRITICAL_FIXES_MARKET_CAP.md](CRITICAL_FIXES_MARKET_CAP.md) - 치명적 버그 수정 내역
- [BACKTEST_DATA_COLLECTION.md](BACKTEST_DATA_COLLECTION.md) - 백테스팅 데이터 전략

### 일일 리포트

```bash
# 장 마감 후 실행 (15:35 자동 실행)
python after_market_report.py
```

**리포트 내용**:
1. 오늘의 매매 내역 (매수/매도)
2. 현재 보유 종목 및 평가손익
3. 누적 수익률 (실현/미실현)
4. 퀀트 포트폴리오 현황 (Top 10)
5. 오늘의 데이터 수집 현황

### 데이터 품질 점검

```bash
python scripts/check_data_quality.py
```

**점검 항목**:
- 일봉 데이터 품질 (OHLC 관계, 급격한 변동)
- 재무 데이터 품질 (NULL 비율, 범위 검증)
- 퀀트 팩터 품질 (점수 범위, NULL 비율)
- 종합 평가 (PASS/WARNING/FAIL)

---

## 최근 개선 사항 (2025-12-28)

### 1. 장 마감 후 자동 리포트 생성
- 매일 15:35 자동 실행
- 일일 매매 내역 및 손익 집계
- 텔레그램 자동 알림

### 2. 데이터 수집 안정성 개선 (9가지)
1. ✅ 가격 데이터 검증 (OHLC 관계, 급격한 변동 감지)
2. ✅ API Rate Limiting (0.2초 간격)
3. ✅ 수익률 계산 최적화 (N+1 쿼리 해결, 100배 성능 향상)
4. ✅ 재무데이터 원자성 보장
5. ✅ 에러 로깅 개선
6. ✅ API 필드 검증 강화
7. ✅ Look-ahead Bias 제거 (역사적 시가총액 계산)
8. ✅ 공휴일 캘린더 추가 (설날/추석 자동 처리)
9. ✅ 데이터 품질 자동 점검 스크립트

### 3. 전역 API Rate Limiting
- 모든 API 호출에 자동 적용 (초당 16-17회)
- 재시도 로직 포함 (최대 3회)
- Rate Limit 오류 자동 감지 및 대기

### 4. Thread-Safe 매수 로직
- Lock 기반 원자적 상태 변경
- 중복 매수 방지
- 쿨다운 체크

### 5. Memory Management
- realtime_data는 당일 데이터만 유지
- 메모리 누적 방지

---

## 라이선스

이 프로젝트는 개인 투자 용도로 제작되었습니다.

---

## 면책 조항

이 소프트웨어는 **교육 및 연구 목적**으로 제공됩니다.
- 실제 투자에 사용 시 발생하는 **모든 손실은 사용자 책임**입니다.
- 과거 성과가 미래 수익을 보장하지 않습니다.
- 투자 결정 전 반드시 **충분한 검증과 테스트**를 거치세요.

---

## 기여

버그 리포트 및 개선 제안은 Issues에 등록해주세요.

---

**마지막 업데이트**: 2025-12-28
