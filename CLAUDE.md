# RoboTrader 퀀트 시스템 아키텍처

## 시스템 개요

한국투자증권 API를 사용한 자동매매 시스템으로, 퀀트 팩터 기반 종목 선정과 점수 기반 리밸런싱을 수행합니다.
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
- 09:00-09:05: 손절 중단, 익절만 허용 (리밸런싱 대기)

### 3. 프로그램 재시작 시 복원 (장중)

**위치**: `main.py`

DB에서 미체결 포지션을 로드하여 메모리에 복원합니다:
- 실전: `get_real_open_positions()` / 가상: `get_virtual_open_positions()`
- 복원 항목: 수량, 매수가, 목표 익절률, 손절률, 상태

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

# Smart Hard Cap: 포트폴리오 평균 점수에 따라 보유 상한 동적 조절
SMART_HARD_CAP_TIERS = [
    (75.0, 5),  # 평균 >= 75점 → target + 5 = 15
    (72.0, 3),  # 평균 >= 72점 → target + 3 = 13
    (0.0,  2),  # 그 외        → target + 2 = 12
]
```

### 리밸런싱 기준 (quant_rebalancing_service.py)

```python
hard_stop_score = 65.0   # 긴급 매도: 점수 < 65점
soft_stop_score = 67.0   # 조건부 매도: 점수 65~67점
soft_stop_rank = 30      # 조건부 매도 순위: > 30위
safe_score = 75.0        # 안전 점수: >= 75점 유지
safe_rank = 25           # 안전 순위: <= 25위 유지
buy_min_score = 65.0     # 매수 최소 점수 (= hard_stop_score)
```

## 안전 메커니즘

다음 안전장치가 구현되어 있습니다. 상세 내용은 [docs/safety_mechanisms.md](docs/safety_mechanisms.md) 참조.

1. **09:00-09:05 손절 중단** — 리밸런싱 전 갭하락 손절 방지
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
- 08:55 → 퀀트 스크리닝 (오늘용 포트폴리오 생성)

### 장 마감 후
- 15:35 → 일일 매매 리포트 생성 (`scripts/daily_trading_summary.py`)

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
