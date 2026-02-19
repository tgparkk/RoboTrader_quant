# 🤖 RoboTrader 퀀트 자동매매 시스템

> 한국투자증권 API 기반 **멀티팩터 퀀트 전략** + **점수 기반 동적 손익절** 자동매매 시스템

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Private-red.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-success.svg)]()

---

## 📋 빠른 시작

```bash
# 1. 클론 및 설치
git clone <repository_url>
cd RoboTrader_quant
pip install -r requirements.txt

# 2. API 설정
cp config/app_config.json.example config/app_config.json
# app_config.json 편집 (APP_KEY, APP_SECRET 입력)

# 3. 실행
python main.py
```

**⚠️ 처음 사용하시나요?** → [SYSTEM_FLOW.md](SYSTEM_FLOW.md)를 먼저 읽어보세요!

---

## 🎯 핵심 개념 (30초 요약)

### 이 프로그램은 무엇을 하나요?

```
매일 퀀트 점수 계산 → 상위 30개 종목 선정 → 자동 매매
                                         ↓
                        점수 높은 종목 = 높은 기대 = 공격적 목표
                        점수 낮은 종목 = 낮은 기대 = 보수적 목표
```

### 언제 매매하나요?

| 시간 | 동작 |
|------|------|
| **08:30** | 📊 전일 데이터 수집 (일봉/재무) |
| **08:55** | 🔍 오늘의 스크리닝 (포트폴리오 생성) |
| **09:05** | 🔄 리밸런싱 (매도/매수/유지 자동 결정) |
| **09:05~15:20** | 👀 모니터링 (1분마다 익절/손절 체크) |

### 어떻게 종목을 고르나요?

```
8가지 퀀트 팩터 → 점수 계산 → 상위 30개
 ├─ Value (가치): PER, PBR 등
 ├─ Quality (품질): ROE, 부채비율 등
 ├─ Momentum (모멘텀): 수익률 추세
 └─ Growth (성장): 매출/이익 성장
```

### 언제 매도하나요?

```
익절: 수익률 >= 목표 익절률 (15~20%)
손절: 수익률 <= -손절률 (-8~-10%)
```

**더 자세한 설명**: [SYSTEM_FLOW.md](SYSTEM_FLOW.md) 📖

---

## 🌟 주요 특징

### ✨ 완전 자동화

- **자동 데이터 수집**: 08:30 전일 일봉/재무 데이터 수집
- **자동 스크리닝**: 08:55 오늘의 포트폴리오 생성
- **자동 리밸런싱**: 09:05 포트폴리오 재구성
- **자동 손익절**: 1분마다 조건 체크, 자동 매도
- **자동 리포트**: 15:35 일일 매매 결과 정리

### 🎯 점수 기반 차등 관리

종목 점수에 따라 목표를 다르게 설정합니다:

| 등급 | 점수 | 익절 목표 | 손절 한도 | 전략 |
|------|------|----------|----------|------|
| **S** | 70점+ | 20% | 8% | 공격적 |
| **A** | 50-70점 | 18% | 9% | 균형 |
| **B** | 50점- | 15% | 10% | 보수적 |

### 🔄 스마트 리밸런싱

```
어제 포트폴리오: 종목 A, B, C (30개)
오늘 스크리닝: 종목 A, B, D (30개)

자동 판단:
  ✅ A, B → 유지 (점수 갱신)
  ❌ C → 매도 (탈락)
  ➕ D → 매수 (신규)
```

### 🛡️ 안정성 & 복원력

- **프로그램 재시작해도 OK**: DB에서 포지션 자동 복원
- **API Rate Limit 보호**: 전역 Rate Limiting (초당 16회)
- **에러 재시도**: 실패 시 자동 재시도 (최대 3회)
- **데이터 검증**: OHLC 관계, 급격한 변동 감지

---

## 📊 프로그램 동작 흐름

### 하루 일과 타임라인

```
08:50  🚀 프로그램 시작
       └─ 포지션 복원, API 연결

09:00  🔔 장 시작
       └─ 데이터 수집 시작

09:05  ⭐ 리밸런싱 (핵심!)
       ├─ 어제 스크리닝 결과 조회
       ├─ 매도 대상: 탈락 종목
       ├─ 매수 대상: 신규 편입 종목
       ├─ 유지 대상: 익절/손절률 갱신
       └─ 시장가 주문 실행

08:30  📊 전일 데이터 수집
       ├─ 일봉 가격 데이터
       └─ 재무제표 데이터

08:55  🔍 오늘의 스크리닝
       ├─ 퀀트 팩터 점수 계산
       └─ 상위 30개 선정 → 오늘 포트폴리오

09:06  👀 장중 모니터링 (15:20까지)
~      ├─ 1분마다: 익절/손절 체크
15:20  └─ 조건 만족 시 즉시 매도

15:35  📈 일일 리포트 생성
       └─ 매매 내역, 손익 정리
```

**자세한 설명**: [SYSTEM_FLOW.md - 시간대별 동작](SYSTEM_FLOW.md#3-시간대별-동작)

### 메인 루프 구조

프로그램은 **6개 태스크를 동시에** 실행합니다:

```python
asyncio.gather(
    데이터_수집_태스크(),        # 실시간 가격
    주문_모니터링_태스크(),      # 체결 확인
    거래_모니터링_태스크(),      # 매수/매도 판단
    시스템_모니터링_태스크(),    # 스케줄 작업
    텔레그램_알림_태스크(),      # 알림 전송
    리밸런싱_태스크()           # 09:05 리밸런싱
)
```

---

## 🎓 매매 전략 상세

### 1. 종목 선정 (퀀트 스크리닝)

**언제**: 매일 08:55
**방법**: 8단계 퀀트 팩터 분석

```
1️⃣ 기본 필터
   - 시가총액 1,000억 이상
   - 거래량 충분
   - 상장폐지 제외

2️⃣ 팩터 점수 계산
   - Value: PER, PBR (저평가 선호)
   - Quality: ROE, 부채비율 (우량 선호)
   - Momentum: 수익률 (상승 추세 선호)
   - Size: 시가총액

3️⃣ 종합 점수 산출
   - 각 팩터 점수 합산
   - 상위 30개 선정

4️⃣ 내일 09:05 리밸런싱에 사용
```

**코드**: `core/quant/quant_screening_service.py`

### 2. 매수 전략

**리밸런싱 매수 (09:05)**

```python
# 신규 편입 종목만 매수
if 종목 in 목표_포트폴리오 and 종목 not in 현재_보유:
    매수_금액 = 총자금 / 30  # 동등 비중
    매수_수량 = 매수_금액 / 현재가

    # 점수 기반 목표 설정
    if 점수 >= 70:
        익절률 = 20%, 손절률 = 8%   # S등급: 공격적
    elif 점수 >= 50:
        익절률 = 18%, 손절률 = 9%   # A등급: 균형
    else:
        익절률 = 15%, 손절률 = 10%  # B등급: 보수적

    시장가_매수_주문()
```

**코드**: `core/helpers/rebalancing_executor.py:536-629`

### 3. 매도 전략

**리밸런싱 매도 (09:05)**

```python
for 보유종목 in 현재_포트폴리오:
    if 보유종목 not in 목표_포트폴리오:
        시장가_전량_매도()  # 탈락 종목
```

**익절/손절 매도 (장중 1분마다)**

```python
현재_수익률 = (현재가 - 매수가) / 매수가

if 현재_수익률 >= 목표_익절률:
    시장가_전량_매도()  # 익절

if 현재_수익률 <= -목표_손절률:
    시장가_전량_매도()  # 손절
```

**코드**: `core/trading_decision_engine.py:269-310`

---

## 💾 데이터 관리

### 저장하는 데이터

| 데이터 | 저장 시각 | 용도 |
|--------|----------|------|
| 일봉 (daily_prices) | 08:30 | 퀀트 팩터 계산, 백테스팅 |
| 재무제표 (financial_statements) | 08:30 | PER, ROE 등 계산 |
| 퀀트 포트폴리오 (quant_portfolio) | 08:55 | 오늘 리밸런싱 |
| 매매 기록 (virtual_trading_records) | 실시간 | 손익 관리, 리포트 |

### 저장하지 않는 데이터

- **분봉 데이터**: 메모리에만 (DB 저장 X)
- **현재가**: API로 실시간 조회 (DB 저장 X)

**이유**: 디스크 공간 절약, 쿼리 속도 향상

---

## 💾 데이터 관리 및 동적 조정

### 핵심 데이터 흐름

시스템이 **어떤 데이터를 언제 DB에 저장**하고, **어떻게 활용**하는지 요약:

#### 1. DB 저장 동작

| 데이터 | 저장 시각 | 테이블 | 용도 |
|--------|----------|--------|------|
| 📊 **일봉 가격** | 08:30 | `daily_prices` | 퀀트 팩터 계산, 백테스팅 |
| 💼 **재무제표** | 08:30 | `financial_statements` | Value/Quality 점수 |
| 📝 **매매 기록** | 즉시 | `virtual_trading_records` | 손익 관리, 포지션 복원 |
| 🎯 **퀀트 점수** | 08:55 | `quant_portfolio`, `quant_factor_scores` | 리밸런싱 |

**특징**:
- **전 영업일 데이터**: 08:30에 "어제까지" 일봉 수집 (백테스팅 일관성)
- **익절/손절률 저장**: 매수 시 `target_profit_rate`, `stop_loss_rate` DB 기록
- **원자성 보장**: `INSERT OR IGNORE` + `UPDATE` 전략으로 데이터 보존

#### 2. 프로그램 재시작 시 포지션 복원

```
프로그램 시작
    ↓
DB에서 미체결 포지션 조회
    ↓
포지션 정보 메모리 복원
  - 수량, 매수가
  - 목표 익절률 ⭐
  - 목표 손절률 ⭐
    ↓
매도 모니터링 재개 (1분마다 체크)
```

**핵심**: 아침에 설정한 동적 목표값이 DB에 저장되어 있어, 재시작 시에도 동일한 익절/손절률로 모니터링 재개!

**SQL 쿼리**:
```sql
SELECT stock_code, quantity, buy_price,
       target_profit_rate,  -- ⭐ 복원 핵심
       stop_loss_rate       -- ⭐ 복원 핵심
FROM virtual_trading_records
WHERE action = 'BUY' AND NOT EXISTS (
    SELECT 1 FROM virtual_trading_records s
    WHERE s.buy_record_id = b.id AND s.action = 'SELL'
)
```

#### 3. OHLCV 및 재무데이터 활용

**OHLCV 데이터**:
- **Momentum 팩터**: 1일/5일/20일 수익률 계산
- **Size 팩터**: 시가총액 필터링 (1,000억 이상)
- **변동성**: 20일 변동성으로 리스크 평가

**재무데이터**:
- **PER, PBR** (Value 팩터): 저평가 종목 발굴
- **ROE, 부채비율** (Quality 팩터): 우량 종목 선별
- **매출, 영업이익** (Growth 팩터): 성장성 평가

**API 호출**:
1. `get_financial_ratio()`: 재무비율 (PER, PBR, ROE, 부채비율)
2. `get_income_statement()`: 손익계산서 (매출, 영업이익, 순이익)
3. `get_balance_sheet()`: 대차대조표 (자산, 부채, 자본)

#### 4. 동적 손익비 조정 메커니즘

**매일 09:05 리밸런싱 시 자동 조정**:

```
[Step 1] DB에서 데이터 읽기
  - quant_portfolio: rank, total_score
  - quant_factor_scores: momentum_score
    ↓
[Step 2] API 호출
  - get_current_price(): 현재가 (매수 주문용)
    ↓
[Step 3] 복합 점수 계산
  - composite_score = rank*0.4 + total_score*0.3 + momentum*0.3
    ↓
[Step 4] 등급 분류
  - S등급 (80+): 익절 20%, 손절 8%
  - A등급 (65-80): 익절 17%, 손절 9%
  - B등급 (50-65): 익절 15%, 손절 10%
    ↓
[Step 5] DB & 메모리 저장
  - virtual_trading_records 테이블 기록
  - TradingStock 객체 설정
```

**실제 예시**:

**종목 A (1위, 점수 85.2)**:
```
복합 점수: 100*0.4 + 85.2*0.3 + 92.1*0.3 = 93.19 → S등급
목표: 익절 20%, 손절 8%
매수가 70,000원 → 익절가 84,000원, 손절가 64,400원
```

**종목 B (25위, 점수 55.8)**:
```
복합 점수: 52*0.4 + 55.8*0.3 + 48.2*0.3 = 51.96 → B등급
목표: 익절 15%, 손절 10%
매수가 50,000원 → 익절가 57,500원, 손절가 45,000원
```

**핵심 요약**:
1. ✅ **매일 09:05** 종목별 점수 기반 동적 목표 설정
2. ✅ **DB 저장** 익절/손절률을 virtual_trading_records에 기록
3. ✅ **재시작 복원** DB에서 목표율 읽어서 모니터링 재개
4. ✅ **유지 종목 갱신** 매일 새 점수로 익절/손절률 업데이트

**상세 설명**: [SYSTEM_FLOW.md - 데이터 관리 및 동적 조정](SYSTEM_FLOW.md#10-데이터-관리-및-동적-조정) 📖

---

## 🔧 설정 및 커스터마이징

### 포트폴리오 크기 변경

```python
# config/constants.py
PORTFOLIO_SIZE = 30  # 보유 종목 수 (원하는 값으로 변경)
```

### 익절/손절률 변경

```python
# core/quant/target_profit_loss_calculator.py:56-119

# S등급 (70점 이상)
if composite_score >= 70:
    target_profit_rate = 0.20  # 익절 20%
    stop_loss_rate = 0.08      # 손절 8%

# 원하는 값으로 수정 가능
```

### 리밸런싱 주기 변경

```python
# main.py:115
self.rebalancing_service.rebalancing_period = RebalancingPeriod.DAILY   # 매일
# RebalancingPeriod.WEEKLY   # 주간
# RebalancingPeriod.MONTHLY  # 월간
```

### 가상매매 ↔ 실제매매

```python
# core/fund_manager.py:__init__
self.virtual_mode = True   # 가상매매 (테스트)
self.virtual_mode = False  # 실제매매 (운영)
```

---

## 📚 문서 가이드

### 🚀 처음 사용자

1. **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** ⭐ 필독!
   - 프로그램이 무엇을 하는지
   - 언제, 어떻게 매매하는지
   - 초보자도 쉽게 이해

### 🔧 개발자

2. **[CLAUDE.md](CLAUDE.md)**
   - 시스템 아키텍처
   - 핵심 동작 원리
   - 코드 위치 및 구조

3. **[MAIN_PY_REFACTORING_SAFETY_PLAN.md](MAIN_PY_REFACTORING_SAFETY_PLAN.md)**
   - 리팩토링 계획 및 진행 상황
   - Phase별 변경 내역

### 📊 운영 및 모니터링

4. **[DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md)**
   - 데이터 수집 안정성 개선 (9가지)
   - API Rate Limiting
   - 에러 처리

5. **일일 리포트**
   ```bash
   python after_market_report.py
   ```
   - 오늘의 매매 내역
   - 현재 보유 종목
   - 누적 수익률

6. **데이터 품질 점검**
   ```bash
   python scripts/check_data_quality.py
   ```
   - 일봉 데이터 검증
   - 재무 데이터 검증
   - 퀀트 팩터 검증

---

## 🗂️ 주요 파일 구조

```
RoboTrader_quant/
├─ 📄 main.py (1,017 lines)           # 메인 실행 파일
│
├─ 📁 core/                            # 핵심 로직
│  ├─ trading_stock_manager.py        # 종목 상태 관리
│  ├─ trading_decision_engine.py      # 매매 판단
│  ├─ order_manager.py                # 주문 실행
│  ├─ 📁 quant/                       # 퀀트 전략
│  │  ├─ quant_screening_service.py  # 스크리닝
│  │  ├─ quant_rebalancing_service.py # 리밸런싱
│  │  └─ target_profit_loss_calculator.py  # 익절/손절률
│  └─ 📁 helpers/                     # 헬퍼 모듈
│     ├─ rebalancing_executor.py     # 리밸런싱 실행
│     ├─ screening_task_runner.py    # 스크리닝 태스크
│     └─ state_restoration_helper.py # 상태 복원
│
├─ 📁 api/                             # API 래퍼
│  ├─ kis_api_manager.py              # 통합 관리
│  ├─ kis_auth.py                     # 인증 + Rate Limit
│  ├─ kis_order_api.py                # 주문
│  └─ kis_financial_api.py            # 재무 데이터
│
├─ 📁 db/                              # 데이터베이스
│  ├─ database_manager.py             # DB 인터페이스
│  └─ quant_db_manager.py             # 퀀트 전용 DB
│
├─ 📁 config/                          # 설정
│  ├─ constants.py                    # 시스템 상수
│  ├─ market_hours.py                 # 시장 시간
│  └─ app_config.json                 # API 키 (직접 생성)
│
├─ 📁 utils/                           # 유틸리티
│  ├─ korean_time.py                  # 한국 시간
│  └─ korean_holidays.py              # 공휴일
│
└─ 📁 scripts/                         # 스크립트
   ├─ daily_trading_summary.py        # 일일 리포트
   └─ check_data_quality.py           # 데이터 검증
```

---

## ❓ 자주 묻는 질문 (FAQ)

### Q1. 매수는 언제 하나요?
**A**: 리밸런싱 모드에서는 **오직 09:05에만** 매수합니다.

### Q2. 매도는 언제 하나요?
**A**:
- 익절가 도달 시 (1분마다 체크)
- 손절가 도달 시 (1분마다 체크)
- 리밸런싱 시 탈락 종목 (09:05)

### Q3. 종목은 어떻게 선정하나요?
**A**: 매일 08:55에 8가지 퀀트 팩터 점수를 계산하여 상위 30개 선정.

### Q4. 프로그램을 재시작하면?
**A**: DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링 재개.

### Q5. 가상매매와 실제매매 차이는?
**A**:
- 가상매매: DB에만 기록, 실제 주문 X
- 실제매매: 한국투자증권 API로 실제 주문

### Q6. 손익은 어떻게 확인하나요?
**A**:
```bash
python after_market_report.py  # 일일 리포트
```
또는 DB 직접 조회:
```sql
SELECT * FROM virtual_trading_records
WHERE action='SELL'
ORDER BY timestamp DESC;
```

---

## 🚨 주의사항

### ⚠️ 투자 위험

- 이 소프트웨어는 **교육 및 연구 목적**입니다
- 실제 투자 시 **모든 손실은 사용자 책임**입니다
- 과거 성과 ≠ 미래 수익 보장
- 반드시 **충분한 테스트 후** 실제 운영하세요

### 🛡️ 안전 운영 가이드

1. **가상매매로 시작**
   ```python
   # core/fund_manager.py
   self.virtual_mode = True  # 최소 1개월 테스트
   ```

2. **소액으로 시작**
   ```python
   # 실제 운영 시작 시
   VIRTUAL_INITIAL_CAPITAL = 1_000_000  # 100만원부터
   ```

3. **정기 모니터링**
   - 매일 15:35 리포트 확인
   - 주간 데이터 품질 점검
   - 월간 성과 분석

4. **백테스팅 필수**
   ```bash
   python backtests/quant_monthly_backtest.py
   ```

---

## 🔄 최근 업데이트 (2025-12-28)

### ✨ 주요 개선사항

1. **main.py 리팩토링** (-41% 라인 감소)
   - 1,732 lines → 1,017 lines
   - 7개 헬퍼 모듈로 분리
   - 가독성 및 유지보수성 대폭 향상

2. **데이터 수집 안정성 9가지 개선**
   - API Rate Limiting 전역 적용
   - OHLC 데이터 검증
   - Look-ahead Bias 제거
   - 공휴일 캘린더 추가

3. **자동 리포트 생성**
   - 매일 15:35 자동 실행
   - 매매 내역 및 손익 정리

4. **Thread-Safe 매수 로직**
   - Lock 기반 중복 매수 방지
   - 25분 쿨다운 추가

5. **메모리 관리 개선**
   - 당일 데이터만 유지
   - 메모리 누적 방지

**상세 내역**: [REFACTORING_PLAN.md](REFACTORING_PLAN.md)

---

## 📞 지원 및 기여

### 버그 리포트
Issues에 등록해주세요.

### 개선 제안
Pull Request 환영합니다!

---

## 📄 라이선스

이 프로젝트는 개인 투자 용도로 제작되었습니다.

---

## 🙏 감사의 말

- 한국투자증권 API
- Python 커뮤니티
- 오픈소스 기여자들

---

**마지막 업데이트**: 2025-12-28
**문서 버전**: 2.0
**프로그램 버전**: Refactored (1,017 lines)

---

## 🎯 다음 단계

### 처음 사용자

1. ✅ [SYSTEM_FLOW.md](SYSTEM_FLOW.md) 읽기 (필독!)
2. ✅ 가상매매로 테스트
3. ✅ 백테스팅으로 검증
4. ✅ 소액 실제 운영

### 개발자

1. ✅ [CLAUDE.md](CLAUDE.md) 읽기
2. ✅ 코드 구조 파악
3. ✅ 커스터마이징
4. ✅ 백테스팅 및 최적화

**행운을 빕니다! 🚀**
