# RoboTrader 퀀트 자동매매 시스템

> 한국투자증권 API 기반 **V100 단일 팩터 퀀트 전략** + **고정 손익절** 자동매매 시스템

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Private-red.svg)]()
[![Status](https://img.shields.io/badge/Status-Active%20(Live%20Trading)-success.svg)]()

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

# 3. 종목 리스트 부트스트랩 (최초 1회)
python scripts/update_stock_list.py

# 4. 실행
python main.py
```

처음 사용하시나요? [SYSTEM_FLOW.md](SYSTEM_FLOW.md) → [CLAUDE.md](CLAUDE.md) 순으로 읽어보세요.

---

## 핵심 개념 (30초 요약)

### 무엇을 하나요?

```
KOSPI + KOSDAQ 약 2,500종목 → V100 점수 95점 이상 통과 → 6게이트 차단 통과 → 상위 10종목 매수
                                                                     ↓
                                       모든 종목 동일: 익절 12%, 손절 6%
```

### 언제 매매하나요?

| 시간 | 동작 |
|------|------|
| **08:30** | 전일 일봉 + 재무 데이터 수집 |
| **08:40** | 장전 시장 분석 (KRX 예상 + 미장 + NewsQuant → CRISIS/CAUTION/NORMAL) |
| **09:00** | 장 시작 — 즉시 TP/SL 작동 |
| **09:05** | 리밸런싱 (매도/매수/유지 자동 결정) — 1회 |
| **09:00 ~ 15:20** | 장중 모니터링 (3초마다 익절/손절 체크) |
| **15:35** | 일봉 수집 → 퀀트 스크리닝 → 일일 리포트 (순차 실행) |

### V100 단일 팩터 (2026-04-14 전환)

**Value 단일 팩터**로 종목 선정 (멀티버스 검증 결과 V/M/Q/G 4팩터 가중평균보다 우월):

```
total_score = value_score = PER(30%) + PBR(35%) + PSR(35%)
buy_min_score = 95.0 (V100 점수 95점 이상만 매수 후보)
```

이전 4팩터 시대(V/M/Q/G)는 deprecated. Momentum/Quality/Growth는 점수 코드에 남아있지만 ranking 미사용.

### 매수 6단계 게이트 (모두 통과해야 매수)

| 순서 | 게이트 | 임계값 | 차단 사유 |
|------|--------|--------|-----------|
| 1 | `buy_min_score` | ≥ 95 | V100 점수 미달 |
| 2 | `BUY_RET5D_MIN` | ≥ -3% | 직전 5거래일 급락 차단 |
| 3 | `BUY_RET5D_MAX` | ≤ +17% | 5일 단기 모멘텀 천장 (2026-05-06) |
| 4 | `BUY_RET20D_MAX` | ≤ +30% | 20일 누적 모멘텀 천장 (2026-05-07) |
| 5 | `BUY_MOMENTUM_SCORE_MIN` | ≥ 30 | momentum_score 합성 점수 하한 (2026-05-07) |
| 6 | 가격 검증 / 자금 예약 | — | 시장 대비 상대강도 + 자금 race condition 방지 |

### 매도

모든 종목 동일 익절/손절 (백테스트 실행순서 수정 후 재검증, 2026-03-26):

| 구분 | 비율 |
|------|------|
| **익절** | 12% |
| **손절** | 6% |

리밸런싱 매도 (09:05): 점수 < 65 → 긴급매도, 65~67 & 순위 > 30 → 조건부매도, ≥ 75 또는 순위 ≤ 25 → 안전 유지.

장중 매도 (3초마다): 익절/손절선 도달 시 즉시 시장가 매도.

---

## 백테스트 성과 (2023-2026, 슬리피지 0.25% 실측 적용)

| 구성 | sharpe | return (3.3년) | MDD | 거래수 |
|------|--------|----------------|-----|--------|
| baseline (V100 + RET5D 게이트만) | +1.85 | +164.3% | 15.1% | 192 |
| **+ M=30 + R=30 게이트 (현행)** | **+2.48** | **+236.7%** | ~17% | 173 |

연도별 sharpe (현행 운영 세팅):
- 2023: 0.00 (데이터 부족 가능성)
- 2024: +0.63
- 2025: +3.83 (백테스트 +71%)
- 2026 Q1+: +8.54 (March 매크로 사고에도 양수)

⚠️ 알파 감소 추세 — 메모리 기록상 2023 샤프 30+ → 2026 +8 수준. 분기별 재검증 필요.

---

## 안전 메커니즘

상세는 [docs/safety_mechanisms.md](docs/safety_mechanisms.md) 참조.

1. **09:00 즉시 TP/SL 작동** — 장 시작과 동시에 익절/손절 체크
2. **당일 손절 종목 재매수 차단** — DB 조회로 같은 날 재매수 금지
3. **매수 6단계 게이트** — 점수/모멘텀/가격/자금 다층 차단
4. **Thread-Safe 매수** — Lock 기반 중복 매수 방지
5. **중복 매도 차단** — UNIQUE 인덱스 + IntegrityError 처리
6. **전역 API Rate Limiting** — 60ms 간격, 서킷 브레이커 (연속 10회 실패 시 60초 차단)
7. **Memory Management** — 분봉 데이터는 메모리에만 (DB 미저장), 당일 데이터만 유지
8. **리밸런싱 매도 쿨다운** — 매도 후 3일간 재매수 차단 (요요 방지)
9. **상태 복원** — 프로그램 재시작 시 DB에서 미체결 포지션 복원 (수량/매수가/TP/SL 포함)
10. **CRISIS 레짐 전량 매도** — KOSPI ≤ -3%, S&P ≤ -5%, VIX ≥ 40 시 보유 전량 시가 매도

---

## 데이터 관리

| 데이터 | 저장 시각 | 위치 | 비고 |
|--------|----------|------|------|
| 일봉 | 08:30 + 15:35 | `daily_prices` (PG) | 2단계 수집 |
| 재무 | 08:30 | `financial_data`, `quant_*` (PG) | yfinance |
| 퀀트 점수 | 15:35 | `quant_factors`, `quant_portfolio` (PG) | 다음 날 09:05 리밸런싱용 |
| 매매 기록 | 즉시 | `real_trading_records` / `virtual_trading_records` (PG) | 손익·복원 |
| 분봉 | — | 메모리만 | DB 미저장 |
| 현재가 | — | API 실시간 | DB 미저장 |

DB: PostgreSQL `robotrader_quant`, port 5433. 백테스트 DB: `robotrader_backtest`.

---

## 설정 및 커스터마이징

### 가상매매 ↔ 실제매매

```json
// config/trading_config.json
{
  "paper_trading": false,      // false=실전, true=가상
  "rebalancing_mode": true     // true=09:05 리밸런싱 모드
}
```

현재 운영: **실전매매 (paper_trading=false, 2026-02-12 전환)**

### 매수 게이트 (config/constants.py)

```python
PORTFOLIO_SIZE = 10
buy_min_score = 95.0                # V100 점수 컷
BUY_RET5D_MIN = -3.0                # -3% 이하 급락 차단
BUY_RET5D_MAX = 17.0                # +17% 초과 모멘텀 천장 차단
BUY_RET20D_MAX = 30.0               # +30% 초과 20일 누적 차단
BUY_MOMENTUM_SCORE_MIN = 30.0       # momentum_score 하한
BUY_BLACKLIST = set()               # 한시 차단 종목 (현재 비어있음)
```

### TP/SL 변경

`core/quant/target_profit_loss_calculator.py`:

```python
target_profit_rate = 0.12  # 12%
stop_loss_rate = 0.06      # 6%
```

### 리밸런싱 매도 기준

`core/quant/quant_rebalancing_service.py`:

```python
self.hard_stop_score = 65.0   # 긴급 매도
self.soft_stop_score = 67.0   # 조건부 매도
self.soft_stop_rank = 30      # 조건부 순위
self.safe_score = 75.0        # 안전 유지
self.safe_rank = 25           # 안전 순위
self.buy_min_score = 95.0     # 매수 최소 점수 (V100)
```

---

## 종목 리스트 관리

`stock_list.json`은 매일 변경되는 자동 갱신 데이터라 git에서 추적하지 않습니다(.gitignore).
신규 클론 직후엔 한 번 부트스트랩:

```bash
python scripts/update_stock_list.py
```

자동 갱신: 매일 08:20에 `scripts/update_stock_list.py`가 자동 실행되어 KOSPI + KOSDAQ 종목 리스트를 갱신합니다.

필터링 대상: 우선주(코드 끝자리 5), 전환우선주, ETF/ETN, SPAC, 리츠.

---

## 주요 파일 구조

```
RoboTrader_quant/
├─ main.py                              # 메인 오케스트레이터
│
├─ core/
│  ├─ trading_stock_manager.py          # 종목 상태 관리 (3초 간격 모니터링)
│  ├─ trading_decision_engine.py        # 매매 판단 (TP/SL)
│  ├─ order_manager.py                  # 주문 실행 + 체결 콜백
│  ├─ fund_manager.py                   # 자금 reserve/confirm/cancel 패턴
│  ├─ pre_market_analyzer.py            # 08:40 장전 레짐 분석
│  ├─ candidate_selector.py             # 1차 필터링
│  ├─ quant/
│  │  ├─ quant_screening_service.py     # V100 스크리닝 (15:35)
│  │  ├─ quant_rebalancing_service.py   # 09:05 리밸런싱 + 6단계 매수 게이트
│  │  └─ target_profit_loss_calculator.py  # 고정 TP/SL 12%/6%
│  └─ helpers/
│     ├─ rebalancing_executor.py        # 리밸런싱 실행 (가격 검증 + 자금 예약)
│     ├─ screening_task_runner.py       # 15:35 스크리닝 태스크
│     └─ state_restoration_helper.py    # 시작 시 포지션 복원
│
├─ api/
│  ├─ kis_api_manager.py                # 통합 관리
│  ├─ kis_auth.py                       # 인증 + Rate Limit + 서킷 브레이커
│  ├─ kis_order_api.py                  # 주문
│  └─ kis_financial_api.py              # 재무
│
├─ db/
│  ├─ database_manager.py               # PG 인터페이스 (ThreadedConnectionPool)
│  └─ quant_db_manager.py               # 퀀트 전용
│
├─ config/
│  ├─ constants.py                      # 시스템 상수 (PORTFOLIO_SIZE, BUY_* 게이트)
│  ├─ db_config.py                      # PG 설정 (port 5433)
│  └─ app_config.json                   # API 키 (직접 생성)
│
├─ backtest/
│  ├─ data_collector.py                 # FDR + yfinance
│  ├─ factor_calculator.py              # V100 점수 계산
│  ├─ backtester.py                     # 백테스트 엔진
│  └─ models.py                         # BacktestParams (게이트 파라미터)
│
├─ scripts/
│  ├─ update_stock_list.py              # KOSPI+KOSDAQ 갱신 (08:20 자동 + 수동)
│  ├─ today_trading_status.py           # 오늘 매매 현황
│  ├─ daily_trading_summary.py          # 일일 리포트
│  ├─ tp_sl_multiverse*.py              # TP/SL 멀티버스
│  ├─ buy_ret*_multiverse.py            # 게이트 멀티버스
│  ├─ v100_momentum_combo_*.py          # 4축 결합 멀티버스 + 분석기
│  └─ regen_factors_with_delay.py       # 백테스트 DB 팩터 재생성
│
├─ stock_list.json                      # 종목 리스트 (자동 갱신, gitignore)
├─ CLAUDE.md                            # 시스템 아키텍처 (개발자용)
├─ SYSTEM_FLOW.md                       # 동작 흐름 상세 (사용자용)
└─ README.md                            # 이 문서
```

---

## 자주 묻는 질문 (FAQ)

### Q1. 매수는 언제 하나요?
**A**: 09:05 리밸런싱 시 1회만. 6단계 게이트 통과한 V100 점수 95+ 종목 중 신규 편입 대상.

### Q2. 매도는 언제 하나요?
- 09:05 리밸런싱: 점수 < 65 또는 탈락 종목
- 장중 (3초마다): 익절(+12%) 또는 손절(-6%) 도달 시 즉시
- 09:00부터 TP/SL 즉시 작동 (09:05 리밸런싱과 독립)

### Q3. 종목은 어떻게 선정하나요?
**A**: 매일 15:35에 KOSPI+KOSDAQ 약 2,500개 종목에서 V100 점수(Value 단일)를 계산하여 95점 이상 종목 중 상위 10개를 다음 날 매수 후보로 선정.

### Q4. 프로그램을 재시작하면?
**A**: DB에서 자동으로 보유 종목과 익절/손절률(12%/6%)을 복원하여 모니터링을 재개합니다.

### Q5. 가상매매와 실제매매 차이는?
- 가상매매: DB(`virtual_trading_records`)에만 기록, 실제 주문 X
- 실제매매: KIS API로 실제 주문, `real_trading_records` 기록

### Q6. 손익은 어떻게 확인하나요?
```bash
python scripts/today_trading_status.py                    # 오늘
python scripts/today_trading_status.py --date 2026-05-07  # 특정 날짜
python after_market_report.py                              # 일일 리포트
```

### Q7. 백테스트는 어떻게 하나요?
```bash
# TP/SL 멀티버스 (전체 기간)
python scripts/tp_sl_multiverse_2024_2025.py

# 매수 게이트 멀티버스
python scripts/buy_ret20d_max_multiverse.py
python scripts/v100_momentum_combo_multiverse.py

# 백테스트 DB 팩터 재생성 (운영 코드 변경 후)
python scripts/regen_factors_with_delay.py --start 2023-01-01 --end 2026-05-06
```

---

## 문서 가이드

| 문서 | 대상 | 내용 |
|------|------|------|
| [README.md](README.md) (이 문서) | 모두 | 개요·빠른 시작·FAQ |
| [CLAUDE.md](CLAUDE.md) | 개발자 | 아키텍처·코드 위치·현재 설정값 |
| [SYSTEM_FLOW.md](SYSTEM_FLOW.md) | 사용자 | 동작 흐름 상세 |
| [docs/safety_mechanisms.md](docs/safety_mechanisms.md) | 운영자 | 안전 메커니즘 |
| [docs/portfolio_snapshot_guide.md](docs/portfolio_snapshot_guide.md) | 운영자 | 포트폴리오 스냅샷 |
| [docs/multiverse_guide.md](docs/multiverse_guide.md) | 분석자 | 멀티버스 분석 가이드 |
| [docs/multiverse_parameters.md](docs/multiverse_parameters.md) | 분석자 | 멀티버스 파라미터 사전 |
| [docs/slippage_calibration_20260413.md](docs/slippage_calibration_20260413.md) | 분석자 | 슬리피지 0.25% 실측 |
| [docs/archive/](docs/archive/) | 참고 | 폐기된 문서·changelog |

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
4. **백테스트 정합성 점검** — 운영 코드와 백테스트 DB의 점수 체계 일치 여부 확인 (2026-05-07 점수 컬럼 의미 불일치 버그 발견·수정 사례 참고)

---

## 라이선스

이 프로젝트는 개인 투자 용도로 제작되었습니다.

---

**마지막 업데이트**: 2026-05-07
**문서 버전**: 5.0 (V100 + 6단계 매수 게이트 시대)
