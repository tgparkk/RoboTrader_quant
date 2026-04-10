# RoboTrader 퀀트 시스템 아키텍처

## 시스템 개요

한국투자증권 API를 사용한 자동매매 시스템으로, 2단계 스코어링(퀀트 필터 + 타이밍 순위) 기반 종목 선정과 점수 기반 리밸런싱을 수행합니다.
**현재 실전매매 운영 중** (2026-02-12~, `paper_trading=false`)

## 핵심 동작 흐름

### 1. 아침 09:05 리밸런싱 (1회 실행)

**위치**: `core/quant/target_profit_loss_calculator.py`

모든 종목에 단일 익절/손절률을 적용합니다 (백테스트 실행순서 수정 후 재검증):

```python
target_profit_rate = 0.12  # 12%
stop_loss_rate = 0.06      # 6%
```

**저장 위치**: `real_trading_records` (실전) / `virtual_trading_records` (가상) 테이블

### 1-1. 장전 시장 분석 (08:40 실행)

**위치**: `core/pre_market_analyzer.py`

3개 데이터 소스로 시장 레짐을 판단합니다:
- **KRX 예상체결지수**: KOSPI 등락률 예상
- **미장 데이터**: S&P500, VIX (yfinance)
- **NewsQuant**: 글로벌 뉴스 감성 (`GET /api/market/global-sentiment?hours=24`)

| 레짐 | KOSPI 조건 | S&P500 | VIX | 뉴스 | 액션 |
|------|-----------|--------|-----|------|------|
| **CRISIS** | ≤ -3.0% | ≤ -5% | ≥ 40 | down+strong+신뢰≥60% | 전량 매도 + 매수 중단 |
| **CAUTION** | ≤ -1.5% | ≤ -3% | ≥ 30 | down+신뢰≥40% | 매수 5종목 제한 |
| **NORMAL** | 그 외 | — | — | — | 정상 운영 |

폴백: NewsQuant 연결 실패 시 NXT+미장만으로 판단

### 2. 장중 모니터링 (3초마다 주기적 체크)

**위치**: `core/trading_stock_manager.py` → `core/trading_decision_engine.py`

`TradingStockManager`가 3초 간격으로 보유 종목을 순회하며 `TradingDecisionEngine`의 손익절 조건을 체크합니다:
- 익절: `profit_rate >= target_profit_rate` → 매도
- 손절: `profit_rate <= -stop_loss_rate` → 매도
- 09:00부터 손절/익절 모두 즉시 허용 (09:05 리밸런싱과 독립 동작)

### 3. 프로그램 재시작 시 복원 (장중)

**위치**: `main.py`

DB에서 미체결 포지션을 로드하여 메모리에 복원합니다:
- 실전: `get_real_open_positions()` / 가상: `get_virtual_open_positions()`
- 복원 항목: 수량, 매수가, 목표 익절률, 손절률, 상태

## 2단계 스코어링 시스템

### Stage 1: 퀀트 팩터 필터 (종목 선별)
- `total_score = Value(25%) + Momentum(30%) + Quality(22.5%) + Growth(22.5%)`
- 65점 이상인 종목만 매수 후보로 통과
- 매도 임계값(hard_stop=65, soft_stop=67, safe_score=75)에도 사용
- **점수 모멘텀 필터**: `BUY_SCORE_MOMENTUM_MIN = 0.5` (전일 대비 +0.5점 이상만 매수, 2026-04-04 적용)

### Stage 2: 타이밍 점수 (매수 순위 결정)
- `timing_score = MA60거리(40%) + 20일수익률(30%) + 변동성(20%) + MA20거리(10%)`
  - MA60 거리: 60일선 거리 기준 스코어 (거리 ≤ -10% 일 때 100점, 20% 초과 시 10점)
  - 20일 수익률: `clamp(60 - ret_20d × 2.0, 0, 100)` (최근 수익률이 낮을수록 가점)
  - 변동성: `clamp(100 - vol × 1.25, 0, 100)` (저변동성이 높은 점수)
  - MA20 거리: `clamp(60 - ma20_dist × 3.0, 0, 100)` (20일선 근처에 가점)
- 60일선 근처의 저변동성 종목에 높은 점수 (평균회귀 기반)
- 전일 종가 기준으로 계산 (look-ahead bias 없음)

### 최종 매수 순위
- `hybrid_score = total_score × 50% + timing_score × 50%`
- 포트폴리오 상위 10종목은 hybrid_score 순으로 선정

## 데이터 저장 전략

- **일봉 데이터**: DB에 저장 (`daily_prices` 테이블)
- **분봉 데이터**: 메모리에만 보관 (DB 저장 안 함)
- **현재가**: API로 실시간 조회 (DB 저장 안 함)
- **DB**: PostgreSQL (`robotrader_quant`, port 5433)

## 주요 컴포넌트

### 핵심 파일
- `main.py`: 메인 오케스트레이터
- `core/trading_decision_engine.py`: 매매 판단 엔진
- `core/quant/target_profit_loss_calculator.py`: 익절/손절률 계산기
- `core/quant/quant_rebalancing_service.py`: 리밸런싱 서비스
- `core/pre_market_analyzer.py`: 장전 시장 분석 (CRISIS/CAUTION/NORMAL)
- `core/trading_stock_manager.py`: 종목 상태 관리
- `db/database_manager.py`: DB 인터페이스 (PostgreSQL)
- `config/constants.py`: 시스템 상수 정의
- `api/kis_auth.py`: KIS API 인증 + 전역 Rate Limiting

### 상태 전이
```
SELECTED → BUY_PENDING → POSITIONED → SELL_CANDIDATE → SELL_PENDING → COMPLETED
                                                                    → FAILED
```

### 데이터베이스 테이블
- `real_trading_records` / `virtual_trading_records`: 매매 기록
- `daily_prices`: 일봉 가격 데이터
- `quant_portfolio`: 퀀트 포트폴리오 구성 기록
- `quant_factor_scores`: 팩터 점수 기록

## 현재 설정값

### 포트폴리오 (config/constants.py)

```python
PORTFOLIO_SIZE = 10                    # 퀀트 포트폴리오 종목 수
QUANT_CANDIDATE_LIMIT = 50             # 장중 퀀트 후보 종목 최대 수
REBALANCING_ORDER_INTERVAL = 0.1       # 리밸런싱 주문 간 대기 시간 (초)
SELL_ORDER_WAIT_TIMEOUT = 300          # 매도 주문 체결 대기 시간 (초, 5분)
ORDER_CHECK_INTERVAL = 5               # 주문 체결 확인 주기 (초)
REBALANCING_SELL_COOLDOWN_DAYS = 3     # 리밸런싱 매도 후 재매수 차단 일수 (요요 방지)

# 매수 필터
BUY_RET5D_MIN = -3.0                   # 직전 5거래일 수익률 필터 (-3% 이하 급락 종목 매수 차단)
BUY_SCORE_MOMENTUM_MIN = 0.5           # 점수 모멘텀 필터 (전일 대비 +0.5점 이상만 매수, 2026-04-04 적용)

# Smart Hard Cap: 포트폴리오 평균 점수에 따라 보유 상한 동적 조절
SMART_HARD_CAP_TIERS = [
    (75.0, 5),  # 평균 >= 75점 → target + 5 = 15
    (72.0, 3),  # 평균 >= 72점 → target + 3 = 13
    (0.0,  2),  # 그 외        → target + 2 = 12
]
```

### 리밸런싱 기준 (quant_rebalancing_service.py)

```python
hard_stop_score = 65.0   # 1단계 긴급 매도: 점수 < 65점 (즉시 매도)
soft_stop_score = 67.0   # 2단계 조건부 매도: 65점 ≤ 점수 < 67점 AND 순위 > 30위
soft_stop_rank = 30      # 조건부 매도 순위 기준 (> 30위일 때만 적용)
safe_score = 75.0        # 3단계 안전 점수: >= 75점은 순위 무관 유지
safe_rank = 25           # 안전 순위: <= 25위면 점수 낮아도 유지
buy_min_score = 65.0     # 매수 최소 점수 (= hard_stop_score, "팔 종목을 사지 않는다")
```

**리밸런싱 매도 3단계 로직**:
1. **Hard Stop**: `score < 65` → 즉시 매도
2. **Soft Stop**: `65 ≤ score < 67 AND rank > 30` → 조건부 매도
3. **Portfolio Rebalancing**: 목표 포트폴리오 제외 종목 중 `score >= 75 OR rank ≤ 25`가 아니면 매도

## 안전 메커니즘

다음 안전장치가 구현되어 있습니다. 상세 내용은 [docs/safety_mechanisms.md](docs/safety_mechanisms.md) 참조.

1. **09:00 즉시 손절 허용** — 장 시작과 동시에 TP/SL 모두 작동
2. **당일 손절 종목 재매수 차단** — DB 조회로 같은 날 재매수 금지
3. **2단계 매수 가격 검증** — 급락(-5%)/과열(+10%) 필터 + 시장 대비 상대강도
4. **Thread-Safe 매수** — Lock 기반 중복 매수 방지
5. **중복 매도 차단** — UNIQUE 인덱스 + IntegrityError 처리
6. **전역 API Rate Limiting** — 60ms 간격, 서킷 브레이커 (연속 10회 실패 시 60초 차단)
7. **Memory Management** — 당일 데이터만 유지
8. **리밸런싱 매도 쿨다운** — 매도 후 3일간 재매수 차단 (요요 방지)

## 자동 스케줄

### 장 시작 전
- 08:30 → 전일 일봉 + 재무데이터 수집
- 08:40 → 장전 시장 분석 (CRISIS/CAUTION/NORMAL 판정)

### 장 마감 후 (15:35 순차 실행)
- 15:35 → 전체 종목 당일 일봉 수집 → 퀀트 스크리닝 → 일일 매매 리포트 (순차)
  - 1단계: 전체 2,484종목 당일 종가 포함 일봉 수집 (재무 제외)
  - 2단계: 퀀트 스크리닝 + 타이밍 점수 계산 (hybrid_score로 내일용 포트폴리오 생성)
  - 3단계: 일일 매매 리포트 생성 (`scripts/daily_trading_summary.py`)

수동 실행: `python after_market_report.py`

## 매매 현황 조회

```bash
python scripts/today_trading_status.py              # 오늘
python scripts/today_trading_status.py --date 2026-01-23  # 특정 날짜
```

**손익 계산 원칙**: `buy_record_id`로 해당 포지션의 정확한 매수가 참조. 전체 평균 매수가 사용 금지.

## 실행 방법

```bash
python main.py
```

## 팩터 점수 실측 분포 (2026-04-10 분석)

### 점수 분포 (20260225 기준, n=1,129종목)

| 팩터 | avg | std | min | p50 | max | 변별력 | 비고 |
|------|-----|-----|-----|-----|-----|--------|------|
| Value | 54.3 | 29.7 | 0.0 | 61.0 | 99.9 | 좋음 | 8.8%가 0점 (데이터 누락) |
| Momentum | 73.8 | 17.1 | 11.7 | 77.2 | 97.0 | 보통 | 상방 편향 (bull 시장 의존) |
| Quality | 27.7 | 14.9 | 0.0 | 26.2 | 68.9 | 나쁨 | **상한 ~69점** (ROE/ROA 스케일링 문제) |
| Growth | 57.0 | 21.3 | 0.0 | 61.3 | 100.0 | 보통 | ~~50점 고착~~ 수정 완료 (47a6961) |
| **total_score** | 53.6 | 10.5 | 22.1 | 55.1 | 81.1 | — | hard_stop=65 정상 작동 |

### 실효 가중치 왜곡 (설계 vs 실제 분산 기여)

```
Value:    설계 30% → 실제 52.9% (지배적 — std가 가장 큼)
Momentum: 설계 30% → 실제 20.8%
Quality:  설계 20% → 실제 13.3% (상한 제약으로 변별력 부족)
Growth:   설계 20% → 실제  5.9% (범위 압축)
```

### Growth 버그 수정 (2026-04-10, 커밋 bb43e12 + 47a6961)

**수정 내용:**
- 음수 성장률 클리핑(`> 0 else 0`) 제거 → 역성장 기업 변별 가능 (-30% → 35점, 기존 50점)
- 가짜 근사값 제거: `3Y매출 = 1Y×0.8`, `EPS = 매출×0.7` → 독립 데이터만 사용
- Growth = 1Y매출성장(55%) + 1Y순이익성장(45%)

**백테스트 검증 (현행 가중치 V30/M30/Q20/G20):**
- 수정 전: 샤프 10.27, MDD 16.0%, 승률 50.3%
- 수정 후: 샤프 10.26, MDD 16.0%, 승률 50.4% (변화 없음)

### Quality 상한 문제 (미수정, 현행 유지)

```python
roe_score = clamp(roe, 0, 100)  # ROE 15% → 15점 (100점 만점에서)
roa_score = clamp(roa, 0, 100)  # ROA 8% → 8점
```

ROE×5 스케일링, 백분위 변환 모두 시도했으나 **전체 성과 악화**로 철회. 현재 Quality의 낮은 변별력은 시스템이 이미 최적화된 상태이므로, 변경 시 임계값(65/67/75) 재보정 등 연쇄 조정이 필요함.

### 팩터 가중치 멀티버스 결과 (2026-04-10, Growth 수정 후)

**현행 V30/M30/Q20/G20: 40위/721 (상위 5.5%), 샤프 10.26**

| 순위 | Value | Mom | Qual | Grow | 샤프 | MDD | 승률 |
|------|-------|-----|------|------|------|-----|------|
| 1 | 35% | 25% | 12% | 28% | 12.25 | 28.9% | 47.5% |
| 3 | 25% | 30% | 22% | 22% | 11.65 | 18.9% | 50.9% |
| 4 | 30% | 20% | 20% | 30% | 11.62 | 17.6% | 49.2% |
| **40** | **30%** | **30%** | **20%** | **20%** | **10.26** | **16.0%** | **50.4%** |

**Top 10/20 평균 가중치 (세밀 721개 조합):**

```
          Top 10     Top 20     현행     방향
Value:    29.8%      30.8%      30%     = (유지)
Momentum: 30.2%      29.1%      30%     = (유지)
Quality:  14.0%      14.4%      20%     ↓ (줄이면 개선)
Growth:   26.0%      25.8%      20%     ↑ (올리면 개선)
```

**가중치 변경 적용 (2026-04-10)**: V30/M30/Q20/G20 → V25/M30/Q22.5/G22.5
멀티버스 3위/721 (샤프 12.12, MDD 18.9%, 승률 50.9%, PF 1.82), 4개 연도 중 3개에서 우위

## 핵심 원칙

1. **09:05 리밸런싱**: 점수 기반 매도/매수 결정 → DB 저장
2. **장중 3초마다**: 현재가 API 조회 → 목표가 도달 체크 → 매도 실행
3. **재시작 시**: DB에서 전체 포지션 정보 복원 → 모니터링 재개

## 코드 검토 시 주의사항

### 검증 체크리스트
코드에서 문제를 발견했다고 판단하기 전 반드시 확인:

- [ ] 함수 시작부터 끝까지 읽었는가?
- [ ] Lock이나 동기화 메커니즘을 확인했는가?
- [ ] 호출하는 함수의 구현을 확인했는가?
- [ ] 전역 공통 모듈(auth, utils)을 확인했는가?
- [ ] SQL 쿼리의 실제 의미를 파악했는가?
- [ ] 설계 의도를 고려했는가?

### 흔한 오판 사례

1. **코드 조각만 보고 판단** — Lock 밖에 있는 것처럼 보이지만 함수 전체를 읽으면 Lock 안에 있음
2. **중복 방어를 버그로 오해** — 방어적 프로그래밍 (defensive programming)
3. **전역 인프라 간과** — `kis_auth.py`에 전역 Rate Limiting이 모든 API에 적용됨
4. **부분 로직만 보고 판단** — 함수 끝에 당일 필터링 로직 있음

---

## 참고 문서

- [docs/safety_mechanisms.md](docs/safety_mechanisms.md) — 안전 메커니즘 상세
- [docs/PORTFOLIO_SNAPSHOT_GUIDE.md](docs/PORTFOLIO_SNAPSHOT_GUIDE.md) — 포트폴리오 스냅샷 가이드
- [docs/archive/changelog_2025-12_2026-02.md](docs/archive/changelog_2025-12_2026-02.md) — 변경 이력
