# 🤖 RoboTrader 퀀트 시스템 동작 가이드

> 프로그램이 **무엇을 하는지**, **언제 하는지**, **어떻게 하는지**를 쉽게 이해할 수 있도록 정리한 문서입니다.

---

## 📋 목차

1. [프로그램 시작 흐름](#1-프로그램-시작-흐름)
2. [메인 루프 구조](#2-메인-루프-구조)
3. [시간대별 동작](#3-시간대별-동작)
4. [매수 후보 종목 선별](#4-매수-후보-종목-선별)
5. [매수 판단](#5-매수-판단)
6. [매도 판단](#6-매도-판단)
7. [퀀트 리밸런싱](#7-퀀트-리밸런싱)
8. [장중 활동](#8-장중-활동)
9. [데이터 흐름도](#9-데이터-흐름도)
10. [데이터 관리 및 동적 조정](#10-데이터-관리-및-동적-조정)

---

## 1. 프로그램 시작 흐름

```
python main.py 실행
    ↓
┌─────────────────────────────────────┐
│ 1. 초기화 (initialize)              │
│  - API 연결                         │
│  - DB 연결                          │
│  - 텔레그램 봇 연결                  │
│  - 자금 관리자 초기화                │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 2. 상태 복원                        │
│  - DB에서 오늘 후보 종목 복원        │
│  - 보유 포지션 복원                  │
│    (수량, 매수가, 익절/손절률)       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 3. 메인 루프 시작 (6개 태스크 병렬)│
│  - 데이터 수집 태스크               │
│  - 주문 모니터링 태스크              │
│  - 거래 모니터링 태스크              │
│  - 시스템 모니터링 태스크            │
│  - 텔레그램 알림 태스크              │
│  - 리밸런싱 태스크                   │
└─────────────────────────────────────┘
```

---

## 2. 메인 루프 구조

프로그램은 **6개의 태스크**를 동시에 실행합니다:

### 🔄 동시 실행 태스크

| 태스크 | 역할 | 주기 |
|--------|------|------|
| **데이터 수집** | 실시간 가격 데이터 수집 | 지속적 |
| **주문 모니터링** | 미체결 주문 확인 및 처리 | 지속적 |
| **거래 모니터링** | 매수/매도 신호 감지 및 실행 | 1분마다 |
| **시스템 모니터링** | 스케줄 작업 실행 (스크리닝, 리밸런싱) | 5초마다 체크 |
| **텔레그램 알림** | 매매 알림 전송 | 이벤트 발생 시 |
| **리밸런싱** | 09:05 포트폴리오 재구성 | 1일 1회 |

```python
# main.py:214-221
tasks = [
    self._data_collection_task(),        # 실시간 데이터
    self._order_monitoring_task(),       # 주문 체결 확인
    self.trading_manager.start_monitoring(),  # 매수/매도 판단
    self._system_monitoring_task(),      # 스케줄 작업
    self._telegram_task(),               # 알림
    self._rebalancing_task()             # 리밸런싱
]
await asyncio.gather(*tasks)
```

---

## 3. 시간대별 동작

### 📅 하루 일과

```
08:50  프로그램 시작 (권장)
       └─ 상태 복원 및 초기화

09:00  장 시작
       └─ 실시간 데이터 수집 시작

09:05  ⭐ 리밸런싱 실행 (하루 1회)
       ├─ 퀀트 포트폴리오 조회
       ├─ 매도 대상 선정 (포트폴리오 탈락 종목)
       ├─ 매수 대상 선정 (신규 편입 종목)
       ├─ 유지 대상 익절/손절률 갱신
       └─ 시장가 주문 실행

09:06~ 장중 모니터링
15:20  ├─ 1분마다 매도 신호 체크
       │   └─ 익절가 도달? → 매도
       │   └─ 손절가 도달? → 매도
       └─ 리밸런싱 모드에서는 매수 안 함

15:00  장마감 시장가 매도 (설정 시)
       └─ 모든 보유 종목 시장가 일괄 매도

15:35  📈 일일 매매 리포트 생성
       ├─ 오늘의 매매 내역
       ├─ 현재 보유 종목
       ├─ 누적 수익률
       └─ 포트폴리오 현황

---

**다음 영업일 (장 시작 전)**

08:30  📊 전일 데이터 수집
       ├─ 퀀트 포트폴리오 30개 종목
       ├─ 보유 종목 (추가)
       ├─ 일봉 데이터 수집 (전일까지)
       └─ 재무 데이터 수집

08:55  🔍 스크리닝 (2가지 동시 진행)
       ├─ 퀀트 스크리닝 (오늘 리밸런싱용)
       │   └─ 8단계 팩터 점수 계산
       └─ ML 멀티팩터 스크리닝
           └─ 머신러닝 기반 종목 선정
```

---

## 4. 매수 후보 종목 선별

### 🎯 두 가지 방식

#### 방식 1: 퀀트 스크리닝 (08:55 실행)

```
[한국투자증권 조건검색 API]
        ↓
┌──────────────────────────────────┐
│ 1. 기본 필터링                    │
│  - 시가총액 1,000억 이상          │
│  - 거래량 충분                    │
│  - 상장 폐지 제외                 │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│ 2. 퀀트 팩터 점수 계산 (8가지)   │
│  - Value (가치): PER, PBR       │
│  - Quality (품질): ROE, 부채비율│
│  - Momentum (모멘텀): 수익률    │
│  - Size (규모): 시가총액        │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│ 3. 점수 기반 순위 매기기          │
│  - 각 팩터별 점수 합산            │
│  - 상위 30개 선정                │
└──────────────────────────────────┘
        ↓
    [오늘 09:05 리밸런싱에 사용]
```

**코드 위치**: `core/quant/quant_screening_service.py`

#### 방식 2: ML 멀티팩터 스크리닝 (08:55 실행)

```
[DB: daily_prices + financial_statements]
        ↓
┌──────────────────────────────────┐
│ 1. 머신러닝 모델로 예측           │
│  - 과거 데이터 학습              │
│  - 미래 수익률 예측              │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│ 2. 예측 점수 기반 선정            │
│  - 상위 30개 선정                │
└──────────────────────────────────┘
        ↓
    [참고용 / 백테스팅용]
```

**코드 위치**: `core/ml_screening_service.py`

---

## 5. 매수 판단

### 🛒 리밸런싱 모드 (현재 기본)

```
매수는 오직 09:05 리밸런싱 때만!
```

**동작 방식**:
1. 09:05에 퀀트 포트폴리오 조회
2. 신규 편입 종목 확인
3. 현재가로 시장가 매수 주문
4. 점수에 따라 차등 익절/손절률 설정
   - S등급 (70점 이상): 익절 20%, 손절 8%
   - A등급 (50-70점): 익절 18%, 손절 9%
   - B등급 (50점 미만): 익절 15%, 손절 10%

**코드 위치**: `core/helpers/rebalancing_executor.py:536-629`

### 🔄 하이브리드 모드 (선택사항)

```
09:05 리밸런싱 + 장중 실시간 매수
```

**장중 매수 조건** (일봉 데이터 기반):
1. 퀀트 후보 종목에 포함
2. 보유 중이지 않음
3. 25분 매수 쿨다운 아님
4. 충분한 일봉 데이터 (20개 이상)
5. 매수 신호 발생
   - 기술적 분석 통과
   - 충분한 자금 보유

**코드 위치**: `main.py:249-367` (`_analyze_buy_decision`)

---

## 6. 매도 판단

### 💰 익절 / 손절 (자동)

**1분마다 체크** (`core/trading_decision_engine.py:269-310`):

```python
현재가 조회
    ↓
익절 조건 체크
    수익률 >= 목표 익절률?
    예) 매수가 10,000원, 익절률 20%
        → 현재가 12,000원 이상이면 매도
    ↓
손절 조건 체크
    수익률 <= -손절률?
    예) 매수가 10,000원, 손절률 10%
        → 현재가 9,000원 이하면 매도
    ↓
조건 만족 시 → 시장가 매도 주문
```

**목표 익절/손절률은 어떻게 정해지나요?**

```
리밸런싱 시각 (09:05)에 종목 점수에 따라 자동 설정:

┌─────────────┬──────┬──────┐
│ 등급        │ 익절 │ 손절 │
├─────────────┼──────┼──────┤
│ S (70점+)   │ 20%  │  8%  │
│ A (50-70점) │ 18%  │  9%  │
│ B (50점-)   │ 15%  │ 10%  │
└─────────────┴──────┴──────┘

높은 점수 → 높은 익절, 낮은 손절 (리스크 감수)
낮은 점수 → 낮은 익절, 높은 손절 (보수적)
```

**코드 위치**: `core/quant/target_profit_loss_calculator.py:56-119`

### 🕒 장마감 시장가 매도 (선택사항)

15:00 모든 보유 종목을 시장가로 일괄 매도 (데이 트레이딩)

**코드 위치**: `main.py:603-651` (`_execute_end_of_day_liquidation`)

---

## 7. 퀀트 리밸런싱

### 🔄 리밸런싱이란?

**포트폴리오를 정기적으로 재구성하는 작업**

```
어제 포트폴리오: A, B, C, D, E (30개)
오늘 스크리닝: A, B, F, G, H (30개)

비교:
  - 유지: A, B (계속 보유)
  - 매도: C, D, E (탈락 → 매도)
  - 매수: F, G, H (신규 → 매수)
```

### 📅 리밸런싱 실행 (09:05)

**위치**: `core/helpers/rebalancing_executor.py`

```
1️⃣ 계획 수립 (core/quant/quant_rebalancing_service.py)
   ├─ 최신 퀀트 포트폴리오 조회 (오늘 08:55 스크리닝 결과)
   ├─ 현재 보유 종목과 비교
   └─ 매도/매수/유지 리스트 생성

2️⃣ 매도 실행
   ├─ 탈락 종목들을 시장가 매도
   ├─ 주문 체결 대기 (최대 5분)
   └─ 매도 완료 확인

3️⃣ 유지 종목 업데이트
   ├─ 계속 보유하는 종목의
   └─ 익절/손절률을 새 점수로 갱신

4️⃣ 매수 실행
   ├─ 신규 편입 종목들을 시장가 매수
   ├─ 동등 비중 (총 자금 / 30개)
   └─ 점수별 익절/손절률 설정

5️⃣ 결과 알림
   └─ 텔레그램으로 결과 전송
```

**실행 예시**:

```
📊 리밸런싱 실행 결과

매도: 5종목
  - 삼성전자 (005930) 100주 매도 완료
  - LG화학 (051910) 50주 매도 완료
  ...

매수: 5종목
  - 카카오 (035720) 80주 매수 완료 (S등급, 익절20% 손절8%)
  - 네이버 (035420) 120주 매수 완료 (A등급, 익절18% 손절9%)
  ...

유지: 20종목
  - SK하이닉스 (000660) 익절률 18%→20% 갱신
  ...
```

---

## 8. 장중 활동

### ⏰ 1분마다 (09:00 ~ 15:20)

```
[거래 모니터링 태스크]
    ↓
보유 종목 리스트 조회
    ↓
각 종목마다:
  ├─ 현재가 조회
  ├─ 익절 조건 체크 → 충족 시 매도
  ├─ 손절 조건 체크 → 충족 시 매도
  └─ 다음 종목으로
    ↓
1분 대기
    ↓
반복...
```

**코드 위치**: `core/trading_stock_manager.py:start_monitoring()`

### 📊 5초마다 (시스템 모니터링)

```
[시스템 모니터링 태스크]
    ↓
시간 체크:
  ├─ 08:30? → ML 데이터 수집 (전일 데이터)
  ├─ 08:55? → 퀀트 스크리닝 실행
  ├─ 08:55? → ML 스크리닝 실행
  └─ 15:35? → 일일 리포트 생성
    ↓
5초 대기
    ↓
반복...
```

**코드 위치**: `main.py:485-553` (`_system_monitoring_task`)

---

## 9. 데이터 흐름도

### 📈 전체 데이터 흐름

```
┌─────────────────────────────────────────────────┐
│           한국투자증권 API                       │
│  - 조건검색 (후보 종목)                          │
│  - 현재가 (실시간)                               │
│  - 일봉/분봉 (과거 데이터)                       │
│  - 재무제표 (PER, PBR, ROE 등)                  │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           데이터 수집 & 저장                     │
│  [08:30 실행 - 전일 데이터]                     │
│  - daily_prices (일봉)                          │
│  - financial_statements (재무제표)              │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           스크리닝 & 분석                        │
│  [08:55 실행 - 오늘 포트폴리오 생성]            │
│  - 퀀트 팩터 점수 계산                           │
│  - ML 모델 예측                                 │
│  - 상위 30개 선정                               │
│  - quant_portfolio (포트폴리오) 저장             │
│  - quant_factor_scores (팩터 점수) 저장          │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           리밸런싱 계획                          │
│  [09:05 실행]                                   │
│  - 매도/매수/유지 리스트 생성                    │
│  - 익절/손절률 계산                              │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           실제 매매 실행                         │
│  [09:05 시장가 주문]                            │
│  - 매도 주문 → 체결 대기                        │
│  - 매수 주문 → 포지션 기록                      │
│  - virtual_trading_records 저장                 │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           장중 모니터링                          │
│  [1분마다 체크]                                 │
│  - 현재가 조회                                  │
│  - 익절/손절 조건 확인                          │
│  - 조건 충족 시 매도                            │
└─────────────────────────────────────────────────┘
```

---

## 📌 핵심 개념 요약

### 1. **리밸런싱 = 포트폴리오 재구성**
- 매일 09:05에 1회 실행
- 어제 선정된 상위 30개 종목으로 포트폴리오 구성
- 탈락 종목 매도, 신규 종목 매수

### 2. **점수 기반 차등 관리**
- 높은 점수 → 높은 기대 → 높은 익절, 낮은 손절
- 낮은 점수 → 낮은 기대 → 낮은 익절, 높은 손절

### 3. **장중 = 모니터링만**
- 리밸런싱 모드에서는 매수 안 함
- 1분마다 보유 종목의 익절/손절만 체크
- 조건 충족 시 자동 매도

### 4. **데이터 수집 = 장 전 준비**
- 매일 08:30에 전일 데이터 수집
- 일봉 + 재무 데이터 수집
- 과거 데이터 누적으로 분석 정확도 향상
- 백테스팅 가능

### 5. **스크리닝 = 오늘 포트폴리오 생성**
- 매일 08:55에 실행
- 전일까지 데이터로 오늘 종목 선정
- 09:05 리밸런싱에 즉시 사용

---

## 🔧 설정 변경

### 리밸런싱 주기

현재: **매일** (`RebalancingPeriod.DAILY`)

변경 가능:
- `RebalancingPeriod.WEEKLY` → 주간
- `RebalancingPeriod.MONTHLY` → 월간

**위치**: `main.py:115`

### 포트폴리오 크기

현재: **30개** (`PORTFOLIO_SIZE = 30`)

**위치**: `config/constants.py:13`

### 익절/손절률

**위치**: `core/quant/target_profit_loss_calculator.py:56-119`

```python
# S등급 (70점 이상)
if composite_score >= 70:
    target_profit_rate = 0.20  # 20%
    stop_loss_rate = 0.08      # 8%
```

---

## 📚 주요 파일 위치

| 기능 | 파일 |
|------|------|
| 메인 진입점 | `main.py` |
| 리밸런싱 실행 | `core/helpers/rebalancing_executor.py` |
| 리밸런싱 계획 | `core/quant/quant_rebalancing_service.py` |
| 퀀트 스크리닝 | `core/quant/quant_screening_service.py` |
| 익절/손절률 계산 | `core/quant/target_profit_loss_calculator.py` |
| 매수/매도 판단 | `core/trading_decision_engine.py` |
| 종목 모니터링 | `core/trading_stock_manager.py` |
| 데이터 수집 | `core/ml_data_collector.py` |
| 스크리닝 태스크 | `core/helpers/screening_task_runner.py` |
| 상태 복원 | `core/helpers/state_restoration_helper.py` |

---

## ❓ 자주 묻는 질문

### Q1. 언제 매수하나요?
**A**: 리밸런싱 모드에서는 **오직 09:05**에만 매수합니다.

### Q2. 언제 매도하나요?
**A**: 두 가지 경우:
- 익절가 도달 (1분마다 체크)
- 손절가 도달 (1분마다 체크)

### Q3. 종목은 어떻게 선정하나요?
**A**: 매일 08:55 퀀트 스크리닝으로 8가지 팩터 점수를 계산하여 상위 30개 선정.

### Q4. 프로그램을 재시작하면?
**A**: DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링 재개.

### Q5. 수동으로 개입할 수 있나요?
**A**: 네, 텔레그램 봇 명령으로 종목 추가/제거, 수동 매수/매도 가능.

---

## 🎯 다음 단계

1. **백테스팅**: 과거 데이터로 전략 검증
   - `backtests/quant_monthly_backtest.py`

2. **성과 분석**: 일일 리포트 확인
   - `python after_market_report.py`

3. **데이터 품질 점검**:
   - `python scripts/check_data_quality.py`

4. **상세 시스템 구조**:
   - [CLAUDE.md](CLAUDE.md) 참조

---

## 10. 데이터 관리 및 동적 조정

이 섹션에서는 시스템이 **어떤 데이터를 언제 DB에 저장하는지**, **프로그램 재시작 시 어떻게 복원하는지**, **OHLCV와 재무데이터를 어떻게 사용하는지**, **매일 동적으로 손익비를 어떻게 조정하는지**를 상세히 설명합니다.

---

### 10.1 DB 저장 동작

#### 📊 일봉 가격 데이터 (daily_prices 테이블)

**저장 시각**: 08:30 (ML 데이터 수집 시 - 전일 데이터)

**저장 대상**:
- 퀀트 포트폴리오 상위 30개 종목
- 현재 보유 중인 종목 (포트폴리오 외 종목도 포함)

**저장 내용**:
```sql
daily_prices 테이블:
- stock_code: 종목코드
- date: 날짜 (YYYY-MM-DD)
- open, high, low, close: OHLC 가격
- volume: 거래량
- trading_value: 거래대금
- market_cap: 시가총액 (현재 시총 기준 역산)
- returns_1d: 1일 수익률 (%)
- returns_5d: 5일 수익률 (%)
- returns_20d: 20일 수익률 (%)
- volatility_20d: 20일 변동성 (%)
```

**데이터 수집 범위**:
- 기본적으로 **전 영업일까지**만 수집 ([ml_data_collector.py:122-150](core/ml_data_collector.py#L122-L150))
- 이유: 리밸런싱(09:05)은 전날 확정 데이터로 판단
- 당일 데이터는 다음날 아침에 "전 영업일"로 수집됨

**예시**:
```
12/26(목) 08:30 실행 → 12/25(수) 데이터까지 수집
12/27(금) 08:30 실행 → 12/26(목) 데이터 수집 (어제 종가)
12/30(월) 08:30 실행 → 12/27(금) 데이터 수집 (주말 건너뛰기)
```

**코드 위치**: [core/ml_data_collector.py:122-387](core/ml_data_collector.py#L122-L387)

---

#### 💼 재무제표 데이터 (financial_statements 테이블)

**저장 시각**: 08:30 (ML 데이터 수집 시 - 전일 데이터)

**저장 대상**: 일봉 수집 대상과 동일 (퀀트 포트폴리오 + 보유 종목)

**저장 내용**:
```sql
financial_statements 테이블:
- stock_code: 종목코드
- report_date: 재무제표 기준일 (YYYY-MM-DD)

[밸류에이션 지표]
- per: PER (주가수익비율)
- pbr: PBR (주가순자산비율)
- psr: PSR (주가매출액비율)
- dividend_yield: 배당수익률 (%)

[수익성 지표]
- roe: ROE (자기자본이익률, %)
- operating_margin: 영업이익률 (%)
- net_margin: 순이익률 (%)

[재무건전성 지표]
- debt_ratio: 부채비율 (%)
- current_assets: 유동자산
- current_liabilities: 유동부채
- total_equity: 자기자본

[손익 지표]
- revenue: 매출액
- operating_profit: 영업이익
- net_income: 순이익
- total_assets: 총자산
```

**API 호출**:
1. `get_financial_ratio()`: 재무비율 (PER, PBR, ROE, 부채비율 등)
2. `get_income_statement()`: 손익계산서 (매출, 영업이익, 순이익 등)
3. `get_balance_sheet()`: 대차대조표 (자산, 부채, 자본 등)

**PER/PBR 계산 로직** ([ml_data_collector.py:518-542](core/ml_data_collector.py#L518-L542)):
```python
# API에서 직접 제공하지 않는 경우 자체 계산
if not per and ratio.eps > 0:
    current_price = get_stock_market_cap(stock_code)['current_price']
    per = current_price / ratio.eps  # PER = 주가 / EPS

if not pbr and ratio.bps > 0:
    current_price = get_stock_market_cap(stock_code)['current_price']
    pbr = current_price / ratio.bps  # PBR = 주가 / BPS
```

**저장 전략** (원자성 보장):
```python
# 1) 레코드 생성 (없을 경우만)
INSERT OR IGNORE INTO financial_statements (stock_code, report_date, ...)

# 2) NULL이 아닌 값만 업데이트 (기존 데이터 보존)
UPDATE financial_statements
SET per = ?, pbr = ?, roe = ?, ...
WHERE stock_code = ? AND report_date = ?
```

**코드 위치**: [core/ml_data_collector.py:388-750](core/ml_data_collector.py#L388-L750)

---

#### 📝 가상매매 기록 (virtual_trading_records 테이블)

**저장 시각**: 매수/매도 주문 체결 시 즉시

**저장 내용**:
```sql
virtual_trading_records 테이블:
- action: 'BUY' 또는 'SELL'
- stock_code, stock_name: 종목 정보
- quantity: 수량
- price: 체결가
- timestamp: 체결 시각

[매수 시 추가 정보]
- target_profit_rate: 목표 익절률 (0.15 = 15%)
- stop_loss_rate: 목표 손절률 (0.10 = 10%)
- strategy: 전략명 ("Quant Rebalancing" 등)
- reason: 선정 이유

[매도 시 추가 정보]
- buy_record_id: 매수 기록 ID (참조)
- profit_loss: 손익금 (원)
- profit_rate: 수익률 (%)
```

**저장 예시**:
```python
# 매수 시 (09:05 리밸런싱)
db_manager.save_virtual_buy(
    stock_code="005930",
    stock_name="삼성전자",
    quantity=100,
    price=70000,
    target_profit_rate=0.20,  # S등급 20%
    stop_loss_rate=0.08,      # S등급 8%
    strategy="Quant Rebalancing",
    reason="S등급 (복합점수 75점)"
)

# 매도 시 (익절 도달)
db_manager.save_virtual_sell(
    buy_record_id=1234,
    stock_code="005930",
    stock_name="삼성전자",
    quantity=100,
    price=84000,
    profit_loss=1400000,  # +140만원
    profit_rate=0.20,     # +20%
    strategy="Stop Profit",
    reason="목표 익절 도달 (20%)"
)
```

**코드 위치**: [db/database_manager.py:1162-1251](db/database_manager.py#L1162-L1251)

---

#### 🎯 퀀트 포트폴리오 및 팩터 점수

**저장 시각**: 08:55 (퀀트 스크리닝 시)

**저장 테이블**:
1. `quant_portfolio`: 포트폴리오 구성
2. `quant_factor_scores`: 팩터 점수 상세

```sql
quant_portfolio 테이블:
- calc_date: 계산일 (YYYYMMDD)
- stock_code, stock_name: 종목 정보
- rank: 순위 (1~30)
- total_score: 종합 점수 (0~100)
- selection_reason: 선정 이유

quant_factor_scores 테이블:
- calc_date: 계산일
- stock_code: 종목코드
- value_score: Value 팩터 점수 (0~100)
- momentum_score: Momentum 팩터 점수 (0~100)
- quality_score: Quality 팩터 점수 (0~100)
- growth_score: Growth 팩터 점수 (0~100)
- total_score: 종합 점수 (0~100)
- factor_rank: 팩터 순위
```

**코드 위치**: [core/quant/quant_screening_service.py](core/quant/quant_screening_service.py)

---

### 10.2 프로그램 재시작 시 포지션 복원

프로그램이 재시작되면 DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링을 재개합니다.

#### 🔄 복원 프로세스

**실행 시각**: 프로그램 시작 시 ([main.py:1346-1395](main.py#L1346-L1395))

**복원 단계**:

```
프로그램 시작
    ↓
┌──────────────────────────────────────┐
│ 1. 오늘 후보 종목 복원                │
│  - candidate_stocks 테이블 조회       │
│  - 오늘 날짜(DATE) 기준               │
│  - TradingStockManager에 추가         │
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ 2. 보유 포지션 복원 ⭐                │
│  - virtual_trading_records 조회      │
│  - 미체결 포지션만 (BUY만 있고 SELL 없음)│
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ 3. 포지션 정보 메모리 복원            │
│  - 수량, 매수가 설정                  │
│  - 목표 익절률, 손절률 설정           │
│  - 상태를 POSITIONED로 변경           │
└──────────────────────────────────────┘
    ↓
매도 모니터링 시작 (1분마다 체크)
```

#### 📊 복원 쿼리

**미체결 포지션 조회** ([db/database_manager.py:1253-1287](db/database_manager.py#L1253-L1287)):

```sql
SELECT
    b.id,
    b.stock_code,
    b.stock_name,
    b.quantity,
    b.price as buy_price,
    b.timestamp as buy_time,
    b.strategy,
    b.reason as buy_reason,
    b.target_profit_rate,  -- ⭐ 복원 핵심
    b.stop_loss_rate       -- ⭐ 복원 핵심
FROM virtual_trading_records b
WHERE b.action = 'BUY'
    AND b.is_test = 1
    AND NOT EXISTS (
        SELECT 1 FROM virtual_trading_records s
        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
    )
ORDER BY b.timestamp DESC
```

**복원 코드** ([state_restoration_helper.py:98-147](core/helpers/state_restoration_helper.py#L98-L147)):

```python
for _, holding in holdings.iterrows():
    stock_code = holding['stock_code']
    quantity = int(holding['quantity'])
    buy_price = float(holding['buy_price'])

    # ⭐ DB에서 익절/손절률 복원
    target_profit_rate = holding.get('target_profit_rate', 0.15)
    stop_loss_rate = holding.get('stop_loss_rate', 0.10)

    # TradingStock 추가
    trading_stock = await trading_manager.add_selected_stock(...)

    # ⭐ 포지션 정보 메모리 복원
    trading_stock.set_position(quantity, buy_price)
    trading_stock.target_profit_rate = target_profit_rate
    trading_stock.stop_loss_rate = stop_loss_rate

    # ⭐ 상태 변경: POSITIONED → 매도 모니터링 활성화
    trading_manager._change_stock_state(
        stock_code,
        StockState.POSITIONED,
        f"DB 복원: {quantity}주 @{buy_price:,.0f}원 "
        f"(익절:{target_profit_rate*100:.1f}% 손절:{stop_loss_rate*100:.1f}%)"
    )
```

**복원 결과 예시**:
```
✅ 보유 종목 3/3개 복원 완료
📊 005930 포지션 복원: 100주 @70,000원, 익절가 84,000원, 손절가 64,400원
📊 035720 포지션 복원: 80주 @50,000원, 익절가 59,000원, 손절가 45,500원
📊 035420 포지션 복원: 120주 @200,000원, 익절가 236,000원, 손절가 182,000원
```

**핵심**: 프로그램이 종료되어도 아침에 설정한 동적 목표값이 DB에 저장되어 있어, 재시작 시에도 동일한 익절/손절률로 모니터링 재개 가능!

---

### 10.3 OHLCV 및 재무데이터 사용

#### 📈 OHLCV 데이터 활용

**수집 데이터**:
- **O** (Open): 시가
- **H** (High): 고가
- **L** (Low): 저가
- **C** (Close): 종가
- **V** (Volume): 거래량
- **추가**: 거래대금, 시가총액, 수익률, 변동성

**활용 목적**:

1. **퀀트 스크리닝** (08:55):
   - Momentum 팩터: 1일/5일/20일 수익률 계산
   - Size 팩터: 시가총액 기준 필터링 (1,000억 이상)
   - 변동성: 리스크 평가

2. **ML 스크리닝** (08:55):
   - 과거 OHLCV 패턴 학습
   - 미래 수익률 예측
   - 기술적 지표 계산

3. **백테스팅**:
   - 과거 전략 성과 검증
   - 리스크 분석
   - 최적 파라미터 탐색

**코드 위치**: [core/ml_data_collector.py:200-387](core/ml_data_collector.py#L200-L387)

---

#### 💰 재무데이터 활용

**수집 데이터 및 활용**:

| 지표 | API 필드 | 퀀트 팩터 | 용도 |
|------|---------|----------|------|
| **PER** | `per` or 계산 | Value | 저평가 종목 발굴 (낮을수록 좋음) |
| **PBR** | `pbr` or 계산 | Value | 저평가 종목 발굴 (낮을수록 좋음) |
| **PSR** | `psr` | Value | 매출 대비 주가 평가 |
| **ROE** | `roe_value` | Quality | 수익성 평가 (높을수록 좋음) |
| **부채비율** | `liability_ratio` | Quality | 재무건전성 (낮을수록 좋음) |
| **영업이익률** | `operating_margin` | Quality | 수익성 평가 |
| **매출액** | `revenue` | Growth | 성장성 평가 (증가율) |
| **영업이익** | `operating_profit` | Growth | 수익성 개선 추세 |
| **순이익** | `net_income` | Growth | 순이익 증가율 |

**퀀트 팩터 점수 계산 예시**:

```python
# Value Score 계산
value_score = 0
if per and per > 0:
    # PER이 낮을수록 높은 점수 (상위 25% → 100점)
    value_score += score_per(per)

if pbr and pbr > 0:
    # PBR이 낮을수록 높은 점수
    value_score += score_pbr(pbr)

value_score = value_score / 2  # 평균

# Quality Score 계산
quality_score = 0
if roe and roe > 0:
    # ROE가 높을수록 높은 점수 (상위 25% → 100점)
    quality_score += score_roe(roe)

if debt_ratio:
    # 부채비율이 낮을수록 높은 점수
    quality_score += score_debt_ratio(debt_ratio)

quality_score = quality_score / 2  # 평균

# Momentum Score 계산 (OHLCV 사용)
momentum_score = 0
if returns_20d:
    # 20일 수익률이 높을수록 높은 점수
    momentum_score = score_momentum(returns_20d)
```

**종합 점수**:
```python
total_score = (
    value_score * 0.25 +
    quality_score * 0.25 +
    momentum_score * 0.30 +
    growth_score * 0.20
)
```

**코드 위치**: [core/quant/quant_screening_service.py](core/quant/quant_screening_service.py)

---

### 10.4 동적 손익비 조정 메커니즘

#### ⚙️ 매일 동적 조정 (09:05 리밸런싱)

**핵심 개념**: 종목의 **품질과 기대수익에 따라 차등 관리**

```
고품질 종목 (S등급)
→ 높은 기대수익
→ 높은 익절률 (20%)
→ 낮은 손절률 (8%)
→ 큰 수익 기회, 작은 손실 허용

저품질 종목 (B등급)
→ 낮은 기대수익
→ 낮은 익절률 (15%)
→ 높은 손절률 (10%)
→ 작은 수익도 확보, 손실 빠르게 차단
```

---

#### 📊 계산 프로세스

**Step 1: DB에서 데이터 읽기**

09:05 리밸런싱 시 다음 데이터를 DB에서 조회:

```python
# 1) 퀀트 포트폴리오 조회
portfolio = db_manager.get_quant_portfolio(
    calc_date="20251228",  # 오늘 08:55 스크리닝 결과
    limit=30
)

# 결과:
[
    {
        'stock_code': '005930',
        'stock_name': '삼성전자',
        'rank': 1,
        'total_score': 85.2,  # ⭐ 종합 점수
        ...
    },
    ...
]

# 2) 팩터 점수 조회
factor_scores = db_manager.get_factor_scores(
    calc_date="20251228",
    stock_code="005930"
)

# 결과:
{
    'value_score': 75.3,
    'momentum_score': 92.1,    # ⭐ Momentum 점수
    'quality_score': 88.6,
    'growth_score': 79.4,
    'total_score': 85.2,
    'factor_rank': 1
}
```

**코드 위치**:
- [db/database_manager.py:595-666](db/database_manager.py#L595-L666) - `get_quant_portfolio()`
- [db/database_manager.py:668-732](db/database_manager.py#L668-L732) - `get_factor_scores()`

---

**Step 2: API 호출 (현재가 조회)**

리밸런싱 시 매수 주문을 위해 현재가를 조회:

```python
from api.kis_market_api import get_current_price

# 현재가 API 조회
current_price_info = get_current_price("005930")

# 결과:
{
    'current_price': 70000,
    'change_rate': 1.5,
    'volume': 12345678,
    ...
}
```

**용도**:
- 매수 주문 시 현재가 기준으로 주문
- 목표 익절가/손절가 계산에는 사용 안 함 (비율로 관리)

---

**Step 3: 복합 점수 계산**

종목별로 3가지 지표를 결합한 복합 점수 계산:

```python
# core/quant/target_profit_loss_calculator.py:62-76

# 1. 순위 점수 (1위=100점, 50위=0점)
rank_score = (51 - rank) / 50 * 100
# 예: rank=1 → rank_score=100
#     rank=25 → rank_score=52
#     rank=50 → rank_score=2

# 2. 종합 점수 정규화 (0-100 범위)
score_normalized = max(0, min(100, total_score))
# 예: total_score=85.2 → score_normalized=85.2

# 3. Momentum 점수 정규화 (0-100 범위)
momentum_normalized = max(0, min(100, momentum_score))
# 예: momentum_score=92.1 → momentum_normalized=92.1

# 4. 가중 평균 (기본값: 순위 40%, 점수 30%, Momentum 30%)
composite_score = (
    rank_score * 0.40 +
    score_normalized * 0.30 +
    momentum_normalized * 0.30
)

# 예시 계산:
# rank=1, total_score=85.2, momentum_score=92.1
# composite_score = 100*0.4 + 85.2*0.3 + 92.1*0.3
#                 = 40 + 25.56 + 27.63
#                 = 93.19 → S등급
```

**코드 위치**: [core/quant/target_profit_loss_calculator.py:62-76](core/quant/target_profit_loss_calculator.py#L62-L76)

---

**Step 4: 등급별 목표 설정**

복합 점수에 따라 차등 목표 설정:

```python
# core/quant/target_profit_loss_calculator.py:78-88

if composite_score >= 80:
    return 0.20, 0.08  # S등급: 익절 20%, 손절 8%
elif composite_score >= 65:
    return 0.17, 0.09  # A등급: 익절 17%, 손절 9%
elif composite_score >= 50:
    return 0.15, 0.10  # B등급: 익절 15%, 손절 10%
elif composite_score >= 35:
    return 0.13, 0.10  # C등급: 익절 13%, 손절 10%
else:
    return 0.12, 0.10  # D등급: 익절 12%, 손절 10%
```

**등급별 특징**:

| 등급 | 복합점수 | 익절률 | 손절률 | 특징 |
|------|---------|--------|--------|------|
| **S** | 80+ | 20% | 8% | 최고 품질, 큰 수익 추구 |
| **A** | 65-80 | 17% | 9% | 고품질, 적극적 관리 |
| **B** | 50-65 | 15% | 10% | 중간 품질, 균형 관리 |
| **C** | 35-50 | 13% | 10% | 보수적 관리 |
| **D** | 35 미만 | 12% | 10% | 최소 기대, 빠른 손절 |

**코드 위치**: [core/quant/target_profit_loss_calculator.py:78-88](core/quant/target_profit_loss_calculator.py#L78-L88)

---

**Step 5: DB 저장 및 메모리 설정**

계산된 목표값을 DB와 메모리에 저장:

```python
# 1) 매수 주문 실행 (virtual_trading_records에 저장)
db_manager.save_virtual_buy(
    stock_code="005930",
    stock_name="삼성전자",
    quantity=100,
    price=70000,
    target_profit_rate=0.20,  # ⭐ S등급
    stop_loss_rate=0.08,      # ⭐ S등급
    strategy="Quant Rebalancing",
    reason="S등급 (복합점수 93.2점)"
)

# 2) 메모리 객체에도 설정
trading_stock.target_profit_rate = 0.20
trading_stock.stop_loss_rate = 0.08
```

**코드 위치**:
- [core/helpers/rebalancing_executor.py:536-629](core/helpers/rebalancing_executor.py#L536-L629)
- [db/database_manager.py:1162-1201](db/database_manager.py#L1162-L1201)

---

#### 📌 실제 예시

**종목 A (삼성전자, 1위)**:
```
DB 읽기:
- rank: 1
- total_score: 85.2
- momentum_score: 92.1

복합 점수 계산:
- rank_score: 100 (1위 → 100점)
- composite_score: 100*0.4 + 85.2*0.3 + 92.1*0.3 = 93.19

등급: S등급 (93.19 ≥ 80)

목표 설정:
- target_profit_rate: 0.20 (20%)
- stop_loss_rate: 0.08 (8%)

매수 실행:
- 현재가: 70,000원
- 수량: 100주
- 익절가: 84,000원 (70,000 * 1.20)
- 손절가: 64,400원 (70,000 * 0.92)

DB 저장:
- virtual_trading_records 테이블에 기록
- target_profit_rate, stop_loss_rate 포함
```

**종목 B (중소형주, 25위)**:
```
DB 읽기:
- rank: 25
- total_score: 55.8
- momentum_score: 48.2

복합 점수 계산:
- rank_score: 52 (25위 → 52점)
- composite_score: 52*0.4 + 55.8*0.3 + 48.2*0.3 = 51.96

등급: B등급 (50 ≤ 51.96 < 65)

목표 설정:
- target_profit_rate: 0.15 (15%)
- stop_loss_rate: 0.10 (10%)

매수 실행:
- 현재가: 50,000원
- 수량: 80주
- 익절가: 57,500원 (50,000 * 1.15)
- 손절가: 45,000원 (50,000 * 0.90)
```

---

#### 🔁 유지 종목 목표 갱신

리밸런싱 시 **계속 보유하는 종목**도 새 점수로 익절/손절률 갱신:

```python
# core/helpers/keep_list_updater.py

for keep_item in keep_list:
    # 새 점수로 목표 재계산
    new_target_profit_rate, new_stop_loss_rate = calculator.calculate(
        rank=keep_item['new_rank'],
        total_score=keep_item['new_total_score'],
        momentum_score=keep_item['new_momentum_score']
    )

    # 메모리 업데이트
    trading_stock.target_profit_rate = new_target_profit_rate
    trading_stock.stop_loss_rate = new_stop_loss_rate

    # DB 업데이트 (매수 기록 갱신)
    db_manager.update_virtual_buy_targets(
        buy_record_id=keep_item['buy_record_id'],
        target_profit_rate=new_target_profit_rate,
        stop_loss_rate=new_stop_loss_rate
    )
```

**예시**:
```
어제: 10위 (A등급, 익절 17%, 손절 9%)
오늘: 5위 (S등급, 익절 20%, 손절 8%)
→ 목표율 갱신! (더 높은 익절, 더 낮은 손절)
```

**코드 위치**: [core/helpers/keep_list_updater.py](core/helpers/keep_list_updater.py)

---

#### 📊 데이터 흐름 요약

```
[DB 읽기]
quant_portfolio → rank, total_score
quant_factor_scores → momentum_score
    ↓
[API 호출]
get_current_price() → 현재가 (매수 주문용)
    ↓
[계산]
복합 점수 = rank*0.4 + total_score*0.3 + momentum*0.3
    ↓
[등급 분류]
S(80+), A(65-80), B(50-65), C(35-50), D(<35)
    ↓
[목표 설정]
등급별 차등 익절률/손절률
    ↓
[저장]
DB: virtual_trading_records (target_profit_rate, stop_loss_rate)
메모리: TradingStock 객체
    ↓
[모니터링]
1분마다 현재가 조회 → 목표가 도달 체크 → 매도
```

---

#### 🎯 핵심 요약

1. **매일 09:05** 리밸런싱 시 동적 조정
2. **DB 데이터**: 순위, 종합 점수, Momentum 점수
3. **API 데이터**: 현재가 (매수 주문용)
4. **복합 점수**: 3가지 지표를 가중 평균 (40% + 30% + 30%)
5. **5단계 등급**: S/A/B/C/D (차등 관리)
6. **DB 저장**: 익절/손절률을 virtual_trading_records에 기록
7. **재시작 복원**: DB에서 목표율 읽어서 모니터링 재개

---

**마지막 업데이트**: 2025-12-28
**문서 버전**: 1.1
