# RoboTrader 퀀트 시스템 동작 가이드

> 프로그램이 **무엇을 하는지**, **언제 하는지**, **어떻게 하는지**를 코드 기반으로 정리한 문서입니다.

---

## 목차

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
│  - DB 연결 (WAL 모드)               │
│  - 텔레그램 봇 연결                  │
│  - 자금 관리자 초기화                │
│  - 서킷 브레이커 초기화              │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 2. 상태 복원                        │
│  - DB에서 보유 포지션 복원           │
│    (수량, 매수가, 익절/손절률)       │
│  - 상태를 POSITIONED로 설정         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 3. 메인 루프 시작 (6개 태스크 병렬) │
│  - 데이터 수집 태스크               │
│  - 주문 모니터링 태스크              │
│  - 거래 모니터링 태스크              │
│  - 시스템 모니터링 태스크            │
│  - 텔레그램 알림 태스크              │
│  - 리밸런싱 태스크                   │
└─────────────────────────────────────┘
```

**코드 위치**: [main.py:252-260](main.py#L252-L260)

---

## 2. 메인 루프 구조

프로그램은 **6개의 태스크**를 동시에 실행합니다:

| 태스크 | 역할 | 주기 |
|--------|------|------|
| **데이터 수집** | 실시간 가격 데이터 수집 | 지속적 |
| **주문 모니터링** | 미체결 주문 확인 및 처리 | 지속적 |
| **거래 모니터링** | 매도 신호 감지 및 실행 | 1분마다 |
| **시스템 모니터링** | 스케줄 작업 실행 (스크리닝, 백업 등) | 5초마다 체크 |
| **텔레그램 알림** | 매매 알림 전송 | 이벤트 발생 시 |
| **리밸런싱** | 09:05 포트폴리오 재구성 | 1일 1회 |

```python
# main.py:252-260
tasks = [
    self._data_collection_task(),
    self._order_monitoring_task(),
    self.trading_manager.start_monitoring(),
    self._system_monitoring_task(),
    self._telegram_task(),
    self._rebalancing_task()
]
await asyncio.gather(*tasks)
```

---

## 3. 시간대별 동작

### 하루 일과

```
08:20  DB 백업 + 이전 완료 주문 정리
       ├─ VACUUM INTO 백업 (7일 보관)
       └─ completed_orders 당일 이전 주문 정리

08:30  전일 데이터 수집
       ├─ 퀀트 포트폴리오 10개 종목
       ├─ 보유 종목 (추가)
       ├─ 일봉 데이터 수집 (전일까지)
       └─ 재무 데이터 수집

08:55  퀀트 스크리닝
       └─ 4팩터 점수 계산 → 상위 10개 선정

09:00  장 시작
~09:05 ├─ 손절 중단 모드 (익절만 허용)
       └─ 리밸런싱 전 보호

09:05  리밸런싱 실행 (하루 1회)
~09:30 ├─ 퀀트 포트폴리오 조회
       ├─ 매도 대상 선정 (3단계 필터)
       ├─ 매수 대상 선정 (가격 검증 포함)
       ├─ 유지 대상 익절/손절률 갱신
       └─ 시장가 주문 실행

09:30~ 장중 모니터링
15:20  ├─ 1분마다 매도 신호 체크
       │   └─ 익절가 도달? → 매도
       │   └─ 손절가 도달? → 매도
       └─ 리밸런싱 모드에서는 매수 안 함

15:35  일일 매매 리포트 생성
       ├─ 오늘의 매매 내역 (손익절 + 리밸런싱)
       ├─ 현재 보유 종목
       ├─ 누적 수익률
       └─ 포트폴리오 현황

30분   포트폴리오 스냅샷 저장
주기   자금 예약 미확정 자동 해제
       시스템 헬스체크 (DB + 서킷 브레이커)
```

**코드 위치**: [main.py:560-631](main.py#L560-L631) (`_system_monitoring_task`)

---

## 4. 매수 후보 종목 선별

### 퀀트 스크리닝 (08:55 실행)

```
[KOSPI 전 종목 대상]
        ↓
┌──────────────────────────────────┐
│ 1단계: 1차 필터링                 │
│  - 시가총액 ≥ 1,000억원          │
│  - 일평균 거래대금 ≥ 10억원 (20일)│
│  - 주가 1,000 ~ 500,000원       │
│  - 상장 250거래일 이상           │
│  - 재무데이터 존재               │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│ 2단계: 4팩터 점수 계산            │
│  - Value (30%): PER, PBR, PSR   │
│  - Momentum (30%): 수익률, RSI  │
│  - Quality (20%): ROE 등 5지표  │
│  - Growth (20%): 매출/순이익    │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│ 3단계: 종합 순위 매기기           │
│  - 각 팩터 가중 합산              │
│  - 동점 시 Momentum 우선         │
│  - 상위 10개 선정                │
└──────────────────────────────────┘
        ↓
    [오늘 09:05 리밸런싱에 사용]
```

**코드 위치**: [core/quant/quant_screening_service.py:48-282](core/quant/quant_screening_service.py#L48-L282)

### 팩터 점수 상세

#### Value 팩터 (30%) — `_calc_value_score()`

```python
# quant_screening_service.py:388-394
value_score = PER(30%) + PBR(35%) + PSR(35%)
```

| 지표 | 가중치 | 점수 방식 |
|------|--------|----------|
| PER | 30% | 낮을수록 고득점 (0~50 범위 → 0~100점) |
| PBR | 35% | 낮을수록 고득점 (0~5 범위 → 0~100점) |
| PSR | 35% | 낮을수록 고득점 (0~10 범위 → 0~100점) |

- EPS, BPS < 0 (적자/자본잠식) → 0점 처리

#### Momentum 팩터 (30%) — `_calc_momentum_score()`

```python
# quant_screening_service.py:450-457
momentum_score = 1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
```

| 지표 | 기간 | 가중치 |
|------|------|--------|
| 1M 수익률 | 20거래일 | 15% |
| 3M 수익률 | 60거래일 | 25% |
| 6M 수익률 | 120거래일 | 30% |
| 12M 수익률 | 250거래일 | 20% |
| RSI (14) | 14기간 | 10% |

- 수익률 → 점수 변환: `clamp(50 + ret, 0, 100)`
- RSI 30~70 → 선형 변환, 과매수/과매도 구간은 감점

#### Quality 팩터 (20%) — `_calc_quality_score()`

```python
# quant_screening_service.py:520-527
quality_score = ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
```

| 지표 | 가중치 | 점수 방식 |
|------|--------|----------|
| ROE | 30% | 높을수록 고득점 |
| ROA | 20% | 높을수록 고득점 |
| 부채비율 | 20% | 낮을수록 고득점 (`100 - debt_ratio`) |
| 유동비율 | 15% | 높을수록 고득점 (`current_ratio / 2`) |
| 영업이익률 | 15% | 높을수록 고득점 (`margin * 10`) |

#### Growth 팩터 (20%) — `_calc_growth_score()`

```python
# quant_screening_service.py:563-569
growth_score = 1Y매출(30%) + 3Y매출(25%) + 1Y순이익(25%) + 1Y EPS(20%)
```

- 성장률 → 점수 변환: `clamp(50 + growth / 2, 0, 100)`

### 종합 점수 및 선정

```python
# quant_screening_service.py:312-318
total_score = (
    value_score * 0.30 +
    momentum_score * 0.30 +
    quality_score * 0.20 +
    growth_score * 0.20
)

# 정렬: total_score 내림차순, 동점 시 momentum_score 내림차순
# 상위 10개 → quant_portfolio, quant_factor_scores 테이블 저장
```

---

## 5. 매수 판단

### 리밸런싱 모드 (현재 기본)

```
매수는 오직 09:05 리밸런싱 때만!
```

**동작 방식**:
1. 09:05에 퀀트 포트폴리오 조회
2. 신규 편입 종목 확인 (목표에 있지만 미보유)
3. **3중 안전장치** 통과 확인:
   - 당일 손절 종목 재매수 차단
   - 가격 밴드 검증 (전일저가 -5% ~ 전일종가 +10%)
   - 시장 대비 상대강도 (-5%p 이상 약세 차단)
4. fund_manager 자금 예약 → 시장가 매수 주문
5. 복합 점수에 따라 차등 익절/손절률 설정

**복합 점수 계산** (`target_profit_loss_calculator.py:62-76`):

```python
# 순위 40% + 종합점수 30% + Momentum 30%
rank_score = (51 - rank) / 50 * 100   # 1위=100점, 50위=0점
composite_score = (
    rank_score * 0.40 +
    total_score * 0.30 +
    momentum_score * 0.30
)
```

**등급별 익절/손절률** (`target_profit_loss_calculator.py:79-88`):

| 등급 | 복합 점수 | 익절률 | 손절률 |
|------|----------|--------|--------|
| **S** | 80 이상 | 20% | 8% |
| **A** | 65~80 | 17% | 9% |
| **B** | 50~65 | 15% | 10% |
| **C** | 35~50 | 13% | 10% |
| **D** | 35 미만 | 12% | 10% |

**코드 위치**: [core/helpers/rebalancing_executor.py](core/helpers/rebalancing_executor.py)

### 하이브리드 모드 (선택사항)

`rebalancing_mode: false` 설정 시 리밸런싱 + 장중 실시간 매수 병행.

---

## 6. 매도 판단

### 익절 / 손절 (자동, 1분마다 체크)

```python
# trading_decision_engine.py:620-626
현재가 조회
    ↓
익절 조건 체크 (항상 활성)
    수익률 >= 목표 익절률?
    예) 매수가 10,000원, 익절률 20%
        → 현재가 12,000원 이상이면 매도
    ↓
손절 조건 체크 (09:00-09:05는 비활성)
    수익률 <= -손절률?
    예) 매수가 10,000원, 손절률 10%
        → 현재가 9,000원 이하면 매도
    ↓
조건 만족 시 → 시장가 매도 주문
```

**09:00-09:05 손절 중단 모드** (`trading_decision_engine.py:596-632`):

리밸런싱 직전 5분간은 **익절만 허용**, 손절은 중단합니다.
- 갭하락으로 인한 조급한 손절 방지
- 리밸런싱에서 재평가 기회 제공
- `rebalancing_in_progress` 플래그 활성 시에도 손절 중단 (10분 타임아웃 안전장치)

**코드 위치**: [core/trading_decision_engine.py:590-637](core/trading_decision_engine.py#L590-L637)

---

## 7. 퀀트 리밸런싱

### 리밸런싱이란?

**포트폴리오를 매일 재구성하는 작업**

```
어제 포트폴리오: A, B, C, D, E (10개)
오늘 스크리닝: A, B, F, G, H (10개)

비교:
  - 유지: A, B (계속 보유, 익절/손절률 갱신)
  - 매도: C, D, E (기준 미달 → 매도)
  - 매수: F, G, H (신규 편입 → 매수)
```

### 매도 대상 결정 — 3단계 필터링

**위치**: [core/quant/quant_rebalancing_service.py:197-232](core/quant/quant_rebalancing_service.py#L197-L232)

**1단계: 긴급 매도 (Hard Stop)**
```python
if total_score < 65.0:  # hard_stop_score
    # 무조건 매도
    reason = "[리밸런싱] 긴급 매도 (점수 xx < 65)"
```

**2단계: 조건부 매도 (Soft Stop)**
```python
elif 65.0 <= total_score < 67.0:  # hard_stop ~ soft_stop_score
    if factor_rank > 30:           # soft_stop_rank
        # 순위도 낮으면 매도
        reason = "[리밸런싱] 조건부 매도 (점수 xx, 순위 xx)"
```

**3단계: 포트폴리오 조정**
```python
elif stock_code not in target_codes:
    # 안전 종목 체크 — 아래 조건이면 유지
    if total_score >= 75.0:  # safe_score → 유지
        continue
    if factor_rank <= 25:     # safe_rank → 유지
        continue
    # 그 외: 모멘텀 약화 + 상승 가능성 평가 → 매도 결정
```

**리밸런싱 설정값 요약** (`quant_rebalancing_service.py:45-54`):

| 설정 | 값 | 의미 |
|------|-----|------|
| `hard_stop_score` | 65.0 | 긴급 매도 기준 |
| `soft_stop_score` | 67.0 | 조건부 매도 기준 |
| `soft_stop_rank` | 30 | 조건부 매도 순위 |
| `safe_score` | 75.0 | 안전 유지 점수 |
| `safe_rank` | 25 | 안전 유지 순위 |
| `momentum_decline_threshold` | -3.0 | 모멘텀 하락 임계값 |
| `weak_momentum_score` | 50.0 | 약한 모멘텀 기준 |

### 매수 안전장치

**위치**: [core/helpers/rebalancing_executor.py:119-178](core/helpers/rebalancing_executor.py#L119-L178)

**1. 당일 손절 종목 재매수 차단**
```python
today_stop_loss_stocks = db_manager.get_today_stop_loss_stocks()
if stock_code in today_stop_loss_stocks:
    # 오늘 손절한 종목은 매수 금지
```

**2. 절대 가격 밴드 검증**
```python
lower_band = prev_low * 0.95      # 전일 저가 -5% (급락 방지)
upper_band = prev_close * 1.10    # 전일 종가 +10% (과열 방지)
```

**3. 시장 대비 상대강도 검증**
```python
relative_change = (stock_change - market_change) * 100  # %p
if relative_change < -5.0:   # 시장 대비 -5%p 이상 약세 → 차단
if relative_change > 8.0:    # 시장 대비 +8%p 이상 강세 → 로그
```

### 리밸런싱 실행 흐름

```
1. 계획 수립 (quant_rebalancing_service.py)
   ├─ 최신 퀀트 포트폴리오 조회 (08:55 스크리닝 결과)
   ├─ 현재 보유 종목과 비교
   └─ 매도/매수/유지 리스트 생성

2. rebalancing_in_progress = True (손절 중단)

3. 매도 실행
   ├─ 탈락 종목 시장가 매도
   ├─ 주문 체결 대기 (최대 5분)
   └─ 매도 완료 확인

4. 유지 종목 업데이트
   └─ 익절/손절률을 새 점수로 갱신

5. 매수 실행
   ├─ 3중 안전장치 확인
   ├─ fund_manager 자금 예약
   ├─ 동등 비중 시장가 매수 (총 자금 / 10개)
   └─ 등급별 익절/손절률 설정

6. rebalancing_in_progress = False

7. 텔레그램 결과 알림
```

**코드 위치**: [core/helpers/rebalancing_executor.py](core/helpers/rebalancing_executor.py)

---

## 8. 장중 활동

### 1분마다 (09:00 ~ 15:20)

```
[거래 모니터링 태스크]
    ↓
보유 종목 리스트 조회
    ↓
각 종목마다:
  ├─ 현재가 조회
  ├─ 익절 조건 체크 → 충족 시 매도
  ├─ 손절 조건 체크 → 충족 시 매도
  │   (09:00-09:05는 손절 스킵)
  └─ 다음 종목으로
    ↓
1분 대기
    ↓
반복...
```

**코드 위치**: [core/trading_stock_manager.py](core/trading_stock_manager.py) `start_monitoring()`

### 5초마다 (시스템 모니터링)

```
[시스템 모니터링 태스크]
    ↓
시간 체크:
  ├─ 08:20? → DB 백업 + 완료 주문 정리
  ├─ 08:30? → 전일 데이터 수집 (일봉 + 재무)
  ├─ 08:55? → 퀀트 스크리닝 실행
  ├─ 15:35? → 일일 매매 리포트 생성
  └─ 30분?  → 포트폴리오 스냅샷 + 헬스체크
    ↓
5초 대기
    ↓
반복...
```

**코드 위치**: [main.py:560-631](main.py#L560-L631) (`_system_monitoring_task`)

---

## 9. 데이터 흐름도

```
┌─────────────────────────────────────────────────┐
│           한국투자증권 API                       │
│  - 현재가 (실시간)                               │
│  - 일봉 (과거 데이터)                            │
│  - 재무제표 (PER, PBR, ROE 등)                  │
│  - 코스피 지수 (시장 대비 검증용)                │
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
│           퀀트 스크리닝                          │
│  [08:55 실행 - 오늘 포트폴리오 생성]            │
│  - 1차 필터링 (시총, 거래대금 등)               │
│  - 4팩터 점수 계산                               │
│  - 상위 10개 선정                               │
│  - quant_portfolio 저장                         │
│  - quant_factor_scores 저장                     │
└─────────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────────┐
│           리밸런싱 계획 & 실행                   │
│  [09:05 실행]                                   │
│  - 3단계 매도 필터 (점수/순위 기반)             │
│  - 3중 안전장치 매수 검증                        │
│  - 동등 비중 시장가 주문                         │
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

## 핵심 개념 요약

### 1. **리밸런싱 = 포트폴리오 재구성**
- 매일 09:05에 1회 실행
- 스크리닝 결과 상위 10개 종목으로 포트폴리오 구성
- 3단계 매도 필터 + 3중 안전장치 매수 검증

### 2. **점수 기반 차등 관리**
- 복합 점수 = 순위(40%) + 종합점수(30%) + Momentum(30%)
- S등급(80+) ~ D등급(35-): 5단계 익절/손절률

### 3. **장중 = 모니터링만**
- 리밸런싱 모드에서는 매수 안 함
- 1분마다 보유 종목의 익절/손절만 체크
- 09:00-09:05 손절 중단 (리밸런싱 전 보호)

### 4. **데이터 수집 = 장 전 준비**
- 매일 08:30에 전일 데이터 수집
- 일봉 + 재무 데이터 수집
- 08:20 DB 백업 (VACUUM INTO, 7일 보관)

### 5. **스크리닝 = 오늘 포트폴리오 생성**
- 매일 08:55에 실행
- 전일까지 데이터로 오늘 종목 선정
- 09:05 리밸런싱에 즉시 사용

---

## 설정 변경

### 리밸런싱 주기

현재: **매일** (`RebalancingPeriod.DAILY`)

변경 가능:
- `RebalancingPeriod.WEEKLY` → 주간
- `RebalancingPeriod.MONTHLY` → 월간

**위치**: [core/quant/quant_rebalancing_service.py:38](core/quant/quant_rebalancing_service.py#L38)

### 포트폴리오 크기

현재: **10개** (`PORTFOLIO_SIZE = 10`)

**위치**: [config/constants.py:6](config/constants.py#L6)

### 익절/손절률

**위치**: [core/quant/target_profit_loss_calculator.py:79-88](core/quant/target_profit_loss_calculator.py#L79-L88)

```python
if composite_score >= 80:    return 0.20, 0.08  # S등급
elif composite_score >= 65:  return 0.17, 0.09  # A등급
elif composite_score >= 50:  return 0.15, 0.10  # B등급
elif composite_score >= 35:  return 0.13, 0.10  # C등급
else:                        return 0.12, 0.10  # D등급
```

### 시스템 상수

**위치**: [config/constants.py](config/constants.py)

| 상수 | 값 | 의미 |
|------|-----|------|
| `PORTFOLIO_SIZE` | 10 | 포트폴리오 종목 수 |
| `QUANT_CANDIDATE_LIMIT` | 50 | 장중 퀀트 후보 최대 수 |
| `REBALANCING_ORDER_INTERVAL` | 0.1초 | 리밸런싱 주문 간 대기 |
| `SELL_ORDER_WAIT_TIMEOUT` | 300초 | 매도 주문 체결 대기 (5분) |
| `ORDER_CHECK_INTERVAL` | 5초 | 주문 체결 확인 주기 |
| `OHLCV_LOOKBACK_DAYS` | 7일 | 일봉 조회 기간 |
| `QUANT_SCREENING_MAX_RETRIES` | 3회 | 스크리닝 최대 재시도 |

---

## 주요 파일 위치

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
| 유지 종목 갱신 | `core/helpers/keep_list_updater.py` |

---

## FAQ

### Q1. 언제 매수하나요?
**A**: 리밸런싱 모드에서는 **오직 09:05**에만 매수합니다.

### Q2. 언제 매도하나요?
**A**: 세 가지 경우:
- 익절가 도달 (1분마다 체크)
- 손절가 도달 (1분마다 체크, 09:00-09:05 제외)
- 리밸런싱 매도 (09:05, 점수 기반 3단계 필터)

### Q3. 종목은 어떻게 선정하나요?
**A**: 매일 08:55 퀀트 스크리닝으로 4팩터 점수를 계산하여 상위 10개 선정.

### Q4. 프로그램을 재시작하면?
**A**: DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링 재개.

### Q5. 수동으로 개입할 수 있나요?
**A**: 네, 텔레그램 봇 명령으로 종목 추가/제거, 수동 매수/매도 가능.

### Q6. 같은 날 손절한 종목을 다시 사나요?
**A**: 아니요. `get_today_stop_loss_stocks()`로 당일 손절 종목을 조회하여 재매수를 차단합니다.

---

## 10. 데이터 관리 및 동적 조정

### 10.1 DB 저장 동작

#### 일봉 가격 데이터 (daily_prices 테이블)

**저장 시각**: 08:30 (전일 데이터 수집 시)

**저장 대상**:
- 퀀트 포트폴리오 상위 10개 종목
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
- 기본적으로 **전 영업일까지**만 수집
- 이유: 리밸런싱(09:05)은 전날 확정 데이터로 판단
- 당일 데이터는 다음날 아침에 "전 영업일"로 수집됨

**코드 위치**: [core/ml_data_collector.py](core/ml_data_collector.py)

---

#### 재무제표 데이터 (financial_statements 테이블)

**저장 시각**: 08:30 (전일 데이터 수집 시)

**저장 대상**: 일봉 수집 대상과 동일 (퀀트 포트폴리오 + 보유 종목)

**저장 내용**:
```sql
financial_statements 테이블:
- stock_code: 종목코드
- report_date: 재무제표 기준일

[밸류에이션] per, pbr, psr, dividend_yield
[수익성] roe, operating_margin, net_margin
[재무건전성] debt_ratio, current_assets, current_liabilities, total_equity
[손익] revenue, operating_profit, net_income, total_assets
```

**API 호출**:
1. `get_financial_ratio()`: 재무비율 (PER, PBR, ROE, 부채비율 등)
2. `get_income_statement()`: 손익계산서 (매출, 영업이익, 순이익 등)
3. `get_balance_sheet()`: 대차대조표 (자산, 부채, 자본 등)

**저장 전략** (원자성 보장):
```python
# 1) 레코드 생성 (없을 경우만)
INSERT OR IGNORE INTO financial_statements (stock_code, report_date, ...)

# 2) NULL이 아닌 값만 업데이트 (기존 데이터 보존)
UPDATE financial_statements SET per = ?, pbr = ?, ...
WHERE stock_code = ? AND report_date = ?
```

---

#### 가상매매 기록 (virtual_trading_records 테이블)

**저장 시각**: 매수/매도 주문 체결 시 즉시

**저장 내용**:
```sql
virtual_trading_records 테이블:
- action: 'BUY' 또는 'SELL'
- stock_code, stock_name: 종목 정보
- quantity: 수량 (int 타입 보장)
- price: 체결가 (float 타입 보장)
- timestamp: 체결 시각 (Unix epoch 정수)

[매수 시 추가 정보]
- target_profit_rate: 목표 익절률 (0.20 = 20%)
- stop_loss_rate: 목표 손절률 (0.08 = 8%)
- strategy: 전략명 ("Quant Rebalancing" 등)
- reason: 선정 이유

[매도 시 추가 정보]
- buy_record_id: 매수 기록 ID (참조, UNIQUE 제약)
- profit_loss: 손익금 (원)
- profit_rate: 수익률 (%)
- reason: 매도 사유 ("[리밸런싱] ...", "손절 실행 ...", "목표 익절 ...")
```

**중복 매도 방지**: `idx_virtual_trading_unique_sell` UNIQUE 인덱스
```sql
CREATE UNIQUE INDEX idx_virtual_trading_unique_sell
ON virtual_trading_records(buy_record_id)
WHERE action = 'SELL' AND buy_record_id IS NOT NULL
```

**코드 위치**: [db/database_manager.py](db/database_manager.py)

---

#### 퀀트 포트폴리오 및 팩터 점수

**저장 시각**: 08:55 (퀀트 스크리닝 시)

```sql
quant_portfolio 테이블:
- calc_date: 계산일 (YYYYMMDD)
- stock_code, stock_name: 종목 정보
- rank: 순위 (1~10)
- total_score: 종합 점수 (0~100)

quant_factor_scores 테이블:
- calc_date: 계산일
- stock_code: 종목코드
- value_score, momentum_score, quality_score, growth_score: 팩터별 점수
- total_score: 종합 점수 (0~100)
- factor_rank: 팩터 순위
```

---

### 10.2 프로그램 재시작 시 포지션 복원

프로그램이 재시작되면 DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링을 재개합니다.

**코드 위치**: [core/helpers/state_restoration_helper.py:101-150](core/helpers/state_restoration_helper.py#L101-L150)

```
프로그램 시작
    ↓
┌──────────────────────────────────────┐
│ 1. 보유 포지션 복원                   │
│  - virtual_trading_records 조회      │
│  - 미체결 포지션만                    │
│    (BUY만 있고 SELL 없음)            │
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ 2. 포지션 정보 메모리 복원            │
│  - 수량, 매수가 설정                  │
│  - 목표 익절률 (기본값 15%)          │
│  - 손절률 (기본값 10%)               │
│  - 상태를 POSITIONED로 변경           │
└──────────────────────────────────────┘
    ↓
매도 모니터링 시작 (1분마다 체크)
```

**미체결 포지션 조회 쿼리**:
```sql
SELECT b.id, b.stock_code, b.stock_name, b.quantity,
       b.price as buy_price, b.target_profit_rate, b.stop_loss_rate
FROM virtual_trading_records b
WHERE b.action = 'BUY'
    AND NOT EXISTS (
        SELECT 1 FROM virtual_trading_records s
        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
    )
ORDER BY b.timestamp DESC
```

---

### 10.3 동적 손익비 조정 메커니즘

#### 매일 동적 조정 (09:05 리밸런싱)

```
[DB 읽기]
quant_portfolio → rank, total_score
quant_factor_scores → momentum_score
    ↓
[복합 점수 계산]
composite = rank_score(40%) + total_score(30%) + momentum(30%)
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

#### 유지 종목 목표 갱신

리밸런싱 시 **계속 보유하는 종목**도 새 점수로 익절/손절률 갱신:

```python
# core/helpers/keep_list_updater.py
for keep_item in keep_list:
    new_target, new_stop = calculator.calculate(
        rank=new_rank, total_score=new_score, momentum_score=new_momentum
    )
    trading_stock.target_profit_rate = new_target
    trading_stock.stop_loss_rate = new_stop
    db_manager.update_virtual_buy_targets(buy_record_id, new_target, new_stop)
```

**예시**:
```
어제: 10위 (A등급, 익절 17%, 손절 9%)
오늘: 5위 (S등급, 익절 20%, 손절 8%)
→ 목표율 갱신!
```

---

**마지막 업데이트**: 2026-02-23
**문서 버전**: 2.0 (코드 기반 전면 업데이트)
