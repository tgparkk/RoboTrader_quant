# RoboTrader 퀀트 자동매매 시스템

> 한국투자증권 API 기반 **멀티팩터 퀀트 전략** + **고정 손익절** 자동매매 시스템

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Private-red.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-success.svg)]()

---

## 빠른 시작

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

**처음 사용하시나요?** [SYSTEM_FLOW.md](SYSTEM_FLOW.md)를 먼저 읽어보세요!

---

## 핵심 개념 (30초 요약)

### 이 프로그램은 무엇을 하나요?

```
KOSPI + KOSDAQ 전체 종목 스크리닝 → 상위 10개 종목 선정 → 자동 매매
                                                      ↓
                           모든 종목 동일: 익절 16%, 손절 8% (워크포워드 검증)
```

### 언제 매매하나요?

| 시간 | 동작 |
|------|------|
| **08:20** | 종목 리스트 갱신 (KOSPI + KOSDAQ) + DB 백업 |
| **08:30** | 전일 데이터 수집 (일봉/재무) |
| **08:40** | 장전 시장 분석 (NXT + 미장 + NewsQuant → CRISIS/CAUTION/NORMAL) |
| **08:55** | 퀀트 스크리닝 (포트폴리오 생성) |
| **09:05** | 리밸런싱 (매도/매수/유지 자동 결정) |
| **09:06~15:20** | 장중 모니터링 (1분마다 익절/손절 체크) |
| **15:35** | 일일 매매 리포트 생성 |

### 어떻게 종목을 고르나요?

```
KOSPI + KOSDAQ 약 2,500개 종목
    ↓ 1차 필터 (시총 1000억+, 거래대금 10억+, 가격 범위 등)
    ↓ 약 400~600개 통과
    ↓ 4가지 퀀트 팩터 점수 계산
    ↓ 상위 10개 선정
```

4가지 퀀트 팩터:
- **Value (30%)**: PER, PBR, PSR — 저평가 종목 선호
- **Momentum (30%)**: 1M/3M/6M/12M 수익률 + RSI — 상승 추세 선호
- **Quality (20%)**: ROE, ROA, 부채비율 — 우량 종목 선호
- **Growth (20%)**: 매출/순이익 성장률 — 성장성 선호

### 언제 매도하나요?

모든 종목에 단일 익절/손절률 적용 (워크포워드 7구간x99조합 검증):

| 구분 | 비율 |
|------|------|
| **익절** | 16% |
| **손절** | 8% |

리밸런싱 매도 (09:05): 퀀트 점수 < 65점 → 긴급매도, 65~67점 & 순위 > 30위 → 조건부매도

**더 자세한 설명**: [SYSTEM_FLOW.md](SYSTEM_FLOW.md)

---

## 주요 특징

### 완전 자동화

- **종목 리스트 갱신**: 08:20 KOSPI + KOSDAQ 종목 자동 수집
- **데이터 수집**: 08:30 전일 일봉/재무 데이터 수집
- **스크리닝**: 08:55 퀀트 팩터 점수 계산 + 상위 10개 선정
- **리밸런싱**: 09:05 포트폴리오 재구성
- **장중 손익절**: 1분마다 조건 체크, 자동 매도
- **일일 리포트**: 15:35 매매 결과 정리

### 단일 고정 손익절

워크포워드 검증 결과, 단순 고정 TP/SL(16%/8%)이 동적 등급별 계산보다 우수합니다.
모든 종목에 동일한 익절/손절률을 적용합니다.

### 스마트 리밸런싱

```
어제 포트폴리오: 종목 A, B, C (10개)
오늘 스크리닝: 종목 A, B, D (10개)

자동 판단:
  A, B → 유지 (익절/손절률 갱신)
  C → 매도 (탈락)
  D → 매수 (신규)
```

3단계 매도 필터:
1. **긴급 매도**: 점수 < 65점 → 무조건 매도
2. **조건부 매도**: 점수 65~67점 & 순위 > 30위 → 매도
3. **안전 유지**: 점수 >= 75점 or 순위 <= 25위 → 유지

### 매수 안전장치

리밸런싱 매수 시 3중 검증:
1. **당일 손절 재매수 차단**: 같은 날 손절한 종목 재매수 금지
2. **가격 밴드 검증**: 전일 저가 -5% ~ 종가 +10% 범위 확인
3. **시장 대비 상대강도**: KOSPI 대비 -5%p 이상 약세 종목 제외

### 안정성 & 복원력

- **프로그램 재시작해도 OK**: DB에서 포지션 자동 복원 (익절/손절률 포함)
- **API Rate Limit 보호**: 전역 Rate Limiting (초당 16회)
- **서킷 브레이커**: 연속 10회 API 실패 시 60초 자동 중단
- **09:00-09:05 손절 중단**: 리밸런싱 직전 갭하락 손절 방지
- **PostgreSQL**: ThreadedConnectionPool 기반 안정적 DB 연결
- **Graceful Shutdown**: 미체결 주문 대기 후 종료

---

## 프로그램 동작 흐름

### 하루 일과 타임라인

```
08:20  종목 리스트 갱신 (KOSPI + KOSDAQ)
       └─ DB 백업 (7일 보관)

08:30  전일 데이터 수집
       ├─ 일봉 가격 데이터
       └─ 재무제표 데이터

08:40  장전 시장 분석 (pre_market_analyzer.py)
       ├─ KRX 예상체결지수 (KOSPI 등락률)
       ├─ 미장 데이터 (S&P500, VIX)
       ├─ NewsQuant 글로벌 뉴스 감성
       └─ 판정: NORMAL / CAUTION / CRISIS

08:55  퀀트 스크리닝
       ├─ 1차 필터 (시총/거래대금/가격)
       ├─ 4팩터 점수 계산
       └─ 상위 10개 선정 → 오늘 포트폴리오

09:00  장 시작
       └─ 09:00-09:05 손절 중단 모드 (익절만 허용)

09:05  리밸런싱 (핵심!)
       ├─ 어제 스크리닝 결과 조회
       ├─ 3단계 매도 필터 → 탈락 종목 시장가 매도
       ├─ 3중 안전 검증 → 신규 종목 시장가 매수
       └─ 유지 종목 → 익절/손절률 갱신

09:06  장중 모니터링 (15:20까지)
~      ├─ 1분마다: 익절/손절 체크
15:20  └─ 조건 만족 시 즉시 매도

15:35  일일 리포트 생성

15:40  퀀트 스크리닝 (내일용)
```

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

**자세한 설명**: [SYSTEM_FLOW.md](SYSTEM_FLOW.md)

---

## 매매 전략 상세

### 1. 종목 선정 (퀀트 스크리닝)

**언제**: 매일 08:55 (실행용) + 15:40 (내일용)

```
1. 종목 리스트 로드 (stock_list.json: KOSPI + KOSDAQ 약 2,500개)

2. 1차 필터링 (candidate_selector.py)
   - 시가총액 >= 1,000억원
   - 일평균 거래대금 >= 10억원
   - 주가 1,000 ~ 500,000원
   - 상장 250거래일 이상
   - 재무데이터 존재
   → 약 400~600개 통과

3. 4팩터 점수 계산 (quant_screening_service.py)
   - Value(30%): PER/PBR/PSR 점수
   - Momentum(30%): 1M/3M/6M/12M 수익률 + RSI(14)
   - Quality(20%): ROE/ROA/부채비율/유동비율/영업이익률
   - Growth(20%): 매출/순이익/EPS 성장률

4. 종합 점수 산출 + 상위 10개 선정

5. DB 저장 (quant_portfolio 테이블)
```

**코드**: `core/quant/quant_screening_service.py`

### 2. 매수 전략

**리밸런싱 매수 (09:05)**

```python
# 신규 편입 종목만 매수
if 종목 in 목표_포트폴리오 and 종목 not in 현재_보유:
    # 3중 안전 검증
    if 오늘_손절_종목: skip     # 1. 당일 손절 재매수 차단
    if 가격_밴드_이탈: skip     # 2. 급락/과열 차단
    if 시장대비_약세: skip      # 3. 상대강도 미달 차단

    매수_금액 = 총자금 / 10  # 동등 비중
    매수_수량 = 매수_금액 / 현재가

    # 단일 고정 익절/손절률 적용
    익절률 = 0.16  # 16%
    손절률 = 0.08  # 8%

    시장가_매수_주문()
```

**코드**: `core/helpers/rebalancing_executor.py`

### 3. 매도 전략

**리밸런싱 매도 (09:05)**

```python
for 보유종목 in 현재_포트폴리오:
    if 점수 < 65:                             # 긴급 매도
        시장가_전량_매도()
    elif 점수 < 67 and 순위 > 30:             # 조건부 매도
        시장가_전량_매도()
    elif 점수 >= 75 or 순위 <= 25:            # 안전 유지
        익절_손절률_갱신()
    elif 보유종목 not in 목표_포트폴리오:      # 탈락 매도
        시장가_전량_매도()
```

**익절/손절 매도 (장중 1분마다)**

```python
현재_수익률 = (현재가 - 매수가) / 매수가

if 현재_수익률 >= 목표_익절률:
    시장가_전량_매도()  # 익절

if 현재_수익률 <= -목표_손절률:
    시장가_전량_매도()  # 손절
```

**코드**: `core/trading_decision_engine.py`

---

## 데이터 관리

### 저장하는 데이터

| 데이터 | 저장 시각 | 테이블 | 용도 |
|--------|----------|--------|------|
| 일봉 가격 | 08:30 | `daily_prices` | 팩터 계산, 백테스팅 |
| 재무제표 | 08:30 | `financial_statements` | Value/Quality 점수 |
| 퀀트 점수 | 08:55 | `quant_portfolio`, `quant_factor_scores` | 리밸런싱 |
| 매매 기록 | 즉시 | `real_trading_records` / `virtual_trading_records` | 손익 관리, 포지션 복원 |

### 저장하지 않는 데이터

- **분봉 데이터**: 메모리에만 보관 (DB 저장 X)
- **현재가**: API로 실시간 조회 (DB 저장 X)

### 프로그램 재시작 시 포지션 복원

```
프로그램 시작
    ↓
DB에서 미체결 포지션 조회
    ↓
포지션 정보 메모리 복원
  - 수량, 매수가
  - 목표 익절률
  - 목표 손절률
    ↓
매도 모니터링 재개 (1분마다 체크)
```

아침에 설정한 동적 목표값이 DB에 저장되어 있어, 재시작 시에도 동일한 익절/손절률로 모니터링 재개.

---

## 설정 및 커스터마이징

### 포트폴리오 크기 변경

```python
# config/constants.py
PORTFOLIO_SIZE = 10  # 보유 종목 수
```

### 익절/손절률 변경

```python
# core/quant/target_profit_loss_calculator.py:78-79
# 단일 고정 익절/손절선 (워크포워드 검증)
return 0.16, 0.08  # 16% 익절, 8% 손절
```

### 리밸런싱 매도 기준 변경

```python
# core/quant/quant_rebalancing_service.py:46-50
self.hard_stop_score = 65.0  # 긴급 매도: 점수 < 65점
self.soft_stop_score = 67.0  # 조건부 매도: 점수 65~67점
self.soft_stop_rank = 30     # 조건부 매도 순위: > 30위
self.safe_score = 75.0       # 안전 유지: >= 75점
self.safe_rank = 25          # 안전 유지: <= 25위
```

### 가상매매 / 실제매매

```json
// config/trading_config.json
{
  "paper_trading": true,       // true=가상매매, false=실제매매
  "rebalancing_mode": true     // true=순수 리밸런싱 모드
}
```

---

## 종목 리스트 관리

### 자동 갱신

매일 08:20에 `scripts/update_stock_list.py`가 자동 실행되어 KOSPI + KOSDAQ 종목 리스트를 갱신합니다.

### 수동 갱신

```bash
# 미리보기 (파일 변경 없음)
python scripts/update_stock_list.py --dry-run

# 실제 갱신
python scripts/update_stock_list.py
```

### 필터링 대상

- 우선주 (코드 끝자리 5)
- 전환우선주
- ETF/ETN
- SPAC
- 리츠

---

## 주요 파일 구조

```
RoboTrader_quant/
├─ main.py                           # 메인 오케스트레이터 (1,152 lines)
│
├─ core/                             # 핵심 로직
│  ├─ trading_stock_manager.py       # 종목 상태 관리
│  ├─ trading_decision_engine.py     # 매매 판단 (익절/손절)
│  ├─ order_manager.py               # 주문 실행
│  ├─ fund_manager.py                # 자금 관리 (reserve/confirm/cancel)
│  ├─ candidate_selector.py          # 1차 필터링 (KOSPI + KOSDAQ)
│  ├─ quant/                         # 퀀트 전략
│  │  ├─ quant_screening_service.py  # 스크리닝
│  │  ├─ quant_rebalancing_service.py # 리밸런싱
│  │  └─ target_profit_loss_calculator.py  # 고정 익절/손절률 (16%/8%)
│  └─ helpers/                       # 헬퍼 모듈
│     ├─ rebalancing_executor.py     # 리밸런싱 실행 (3중 안전 검증)
│     ├─ screening_task_runner.py    # 스크리닝 태스크
│     └─ state_restoration_helper.py # 상태 복원
│
├─ api/                              # API 래퍼
│  ├─ kis_api_manager.py             # 통합 관리
│  ├─ kis_auth.py                    # 인증 + Rate Limit + 서킷 브레이커
│  ├─ kis_order_api.py               # 주문
│  └─ kis_financial_api.py           # 재무 데이터
│
├─ db/                               # 데이터베이스
│  ├─ database_manager.py            # DB 인터페이스 (PostgreSQL)
│  └─ quant_db_manager.py            # 퀀트 전용 DB
│
├─ config/                           # 설정
│  ├─ constants.py                   # 시스템 상수 (PORTFOLIO_SIZE=10 등)
│  ├─ market_hours.py                # 시장 시간
│  └─ app_config.json                # API 키 (직접 생성)
│
├─ utils/                            # 유틸리티
│  ├─ korean_time.py                 # 한국 시간
│  └─ korean_holidays.py             # 공휴일 캘린더
│
├─ scripts/                          # 스크립트
│  ├─ update_stock_list.py           # KOSPI+KOSDAQ 종목 리스트 갱신
│  ├─ daily_trading_summary.py       # 일일 리포트
│  └─ today_trading_status.py        # 매매 현황 조회
│
├─ backtest/                         # 백테스트
│  ├─ data_collector.py              # FDR+yfinance 데이터 수집
│  ├─ factor_calculator.py           # 4팩터 점수 계산
│  ├─ backtester.py                  # 백테스트 엔진
│  └─ models.py                      # 백테스트 설정
│
├─ stock_list.json                   # 종목 리스트 (KOSPI+KOSDAQ ~2,500개)
└─ config/db_config.py               # DB 설정 (PostgreSQL, port 5433)
```

---

## 자주 묻는 질문 (FAQ)

### Q1. 매수는 언제 하나요?
**A**: 리밸런싱 모드에서는 **오직 09:05에만** 매수합니다.

### Q2. 매도는 언제 하나요?
**A**:
- 리밸런싱 시 탈락 종목 (09:05)
- 익절가 도달 시 (장중 1분마다 체크)
- 손절가 도달 시 (장중 1분마다 체크)

### Q3. 종목은 어떻게 선정하나요?
**A**: 매일 08:55에 KOSPI+KOSDAQ 약 2,500개 종목에서 4가지 퀀트 팩터(Value/Momentum/Quality/Growth) 점수를 계산하여 상위 10개를 선정합니다.

### Q4. 프로그램을 재시작하면?
**A**: DB에서 자동으로 보유 종목과 익절/손절률을 복원하여 모니터링을 재개합니다.

### Q5. 가상매매와 실제매매 차이는?
**A**:
- 가상매매: DB에만 기록, 실제 주문 X
- 실제매매: 한국투자증권 API로 실제 주문

### Q6. 손익은 어떻게 확인하나요?
**A**:
```bash
python scripts/today_trading_status.py           # 오늘 매매 현황
python scripts/today_trading_status.py --date 2026-01-23  # 특정 날짜
python after_market_report.py                     # 일일 리포트
```

### Q7. 종목 리스트를 수동으로 갱신하려면?
**A**:
```bash
python scripts/update_stock_list.py --dry-run  # 미리보기
python scripts/update_stock_list.py            # 실제 갱신
```

---

## 문서 가이드

| 문서 | 대상 | 내용 |
|------|------|------|
| [SYSTEM_FLOW.md](SYSTEM_FLOW.md) | 처음 사용자 | 프로그램 동작 흐름 상세 |
| [CLAUDE.md](CLAUDE.md) | 개발자 | 아키텍처, 핵심 코드 위치 |
| [DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md) | 운영자 | 데이터 수집 안정성 |

### 유용한 스크립트

```bash
python after_market_report.py             # 일일 매매 리포트
python scripts/today_trading_status.py    # 매매 현황 조회
python scripts/update_stock_list.py       # 종목 리스트 갱신
python scripts/run_backtest.py all        # 5년 백테스트 실행
```

---

## 주의사항

### 투자 위험

- 이 소프트웨어는 **교육 및 연구 목적**입니다
- 실제 투자 시 **모든 손실은 사용자 책임**입니다
- 과거 성과는 미래 수익을 보장하지 않습니다
- 반드시 **충분한 테스트 후** 실제 운영하세요

### 안전 운영 가이드

1. **가상매매로 시작** (`paper_trading: true`로 최소 1개월 테스트)
2. **소액으로 시작** (실제 운영 시작 시 100만원부터)
3. **정기 모니터링** (매일 15:35 리포트 확인)
4. **백테스팅 필수** (`python scripts/run_backtest.py all`)

---

## 라이선스

이 프로젝트는 개인 투자 용도로 제작되었습니다.

---

**마지막 업데이트**: 2026-03-18
**문서 버전**: 4.0
