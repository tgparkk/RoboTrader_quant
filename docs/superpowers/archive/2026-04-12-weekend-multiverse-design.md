# 2026-04-12 주말 병렬 멀티버스 설계

## 배경

현행 전략은 4팩터 스크리닝 + 타이밍 점수 기반 스윙(1~3일 보유, TP12%/SL6%)으로 백테스트 샤프 12.12를 기록 중이나 다음 구조적 약점이 있다.

- 팩터 점수-수익 상관 r=0.04 (유의하지 않음)
- 하락장 구간 미검증 (2020/2022 베어마켓 데이터 제한)
- 주 수익원이 TP 도달에 집중, 손절 비용이 최대 지출
- score_momentum 단일 신호 외에 후속 필터·상관 낮은 수익원 부재

이를 해결하기 위해 5개 독립 스트림을 병렬 멀티버스로 검증한다. 모든 작업은 분석 스크립트 생성에 한정하며, 실전 운영 코드(`main.py`, `core/`)는 수정하지 않는다.

## 공통 프레임

### 원칙
- 각 스트림은 독립 git 워크트리 + 브랜치에서 작업
- 기존 `backtest/backtester.py` 및 `scripts/*_multiverse.py` 패턴 재사용
- 산출물은 `docs/superpowers/reports/<stream>-result.md`에 샤프·승률·MDD·거래수 수치 포함
- 각 스트림 완료 후 main 병합 여부는 사용자가 결정

### 산출물 규격
모든 리포트는 다음 항목을 포함한다:
- 베이스라인 대비 샤프·승률·MDD·총손익·거래수 차이
- 연도별 분할(2023/2024/2025/2026Q1) 검증
- 고정자본(5천만원, 복리 제거) 기준 총손익
- 과적합 판정 기준(거래수 50% 이상 감소 시 경고)

### 공통 베이스라인
- 백테스트 기간: 2023-01-01 ~ 2026-03-31
- TP/SL: 12%/6%, 포트폴리오 10종목
- 팩터 가중치: V25/M30/Q22.5/G22.5
- score_momentum >= 0.5 필터 포함

---

## 스트림 1: quant_flow_signal (수급·매크로 필터)

### 가설
외국인·기관 수급 부호와 SOX(필라델피아 반도체 지수) 1일 선행성이 한국 스윙 수익률에 양의 알파를 제공한다.

### 데이터
- **pykrx**: `get_market_trading_value_by_investor()` — 종목별/일자별 외국인·기관 순매수
- **yfinance**: `^SOX` 일별 종가

### 피처
- `foreign_buy_3d`: 3일 누적 외국인 순매수 / 평균 거래대금
- `inst_buy_3d`: 3일 누적 기관 순매수 / 평균 거래대금
- `foreign_inst_aligned`: 외국인·기관 동반 매수 플래그 (둘 다 > 0)
- `sox_prev_ret`: SOX 전일 수익률 (반도체 업종 가점)

### 멀티버스 축
- `foreign_buy_3d`: [없음, > 0, > 10억]
- `inst_buy_3d`: [없음, > 0, > 5억]
- `sox_prev_ret`: [없음, > 0, > 1%]
- 위 3축 완전 탐색 (3×3×3 = 27조합)

### 구현
- 신규 스크립트: `scripts/flow_signal_multiverse.py`
- `signal_filter_multiverse.py`의 `FilteredBacktester` 상속, 필터 함수 추가
- 데이터 수집기: `scripts/collect_investor_flow.py` (pykrx 일별 수집, PG 저장)

### 검증
- score_momentum 단독 필터 대비 승률·샤프 차이
- 거래수 50% 미만 감소 조합만 채택
- 연도별 일관성 3/4 이상 요구

### 출력
`docs/superpowers/reports/flow_signal-result.md`

---

## 스트림 2: quant_regime_filter (레짐 조건부 필터)

### 가설
KOSPI 일간 수익률 레짐(상승/보합/하락)에 따라 score_momentum·ret5d_min 최적 임계값이 다르다. 단일 임계값은 평균에 맞춘 타협이므로 레짐별 분리가 우수하다.

### 데이터
기존 `daily_prices` 테이블에서 KOSPI 지수 시계열 계산 (또는 FDR로 별도 수집)

### 피처
- `kospi_ret_1d`: KOSPI 전일 수익률
- `regime`: 3분위 (하위 33% = 하락, 중간 = 보합, 상위 33% = 상승)

### 멀티버스 축
- 레짐 3종 × score_momentum_min [0.0, 0.3, 0.5, 0.7, 1.0] × ret5d_min [-5, -3, -1, 0] = 60조합
- 레짐별 독립 최적값 vs 전체 단일 최적값 비교

### 구현
- 신규 스크립트: `scripts/regime_filter_multiverse.py`
- 백테스터에 레짐 판정 훅 추가 (매수 시점 전일 KOSPI 수익률로 분기)

### 검증
- 레짐별 샘플 수 균형 확인 (각 레짐 20% 이상)
- 레짐 판정의 look-ahead 없음 확인 (전일 수익률로만 판정)

### 출력
`docs/superpowers/reports/regime_filter-result.md`

---

## 스트림 3: quant_hedge_etf (하락장 헤지)

### 가설
CRISIS/CAUTION 레짐 진입 시 인버스 ETF로 포트폴리오 일부를 전환하면 MDD를 축소할 수 있다. `pre_market_analyzer`의 기존 레짐 판정을 재활용한다.

### 데이터
- **FDR**: 252670 (KODEX 200선물인버스2X) 일별 OHLCV
- 기존 CRISIS/CAUTION 판정 로직 (`core/pre_market_analyzer.py`)

### 피처
- 레짐 진입일, 청산 조건 (NORMAL 복귀 or N일 경과)
- 인버스 비중 (5~30%)

### 멀티버스 축
- 인버스 비중: [5%, 10%, 15%, 20%, 30%]
- 청산 조건: [NORMAL 복귀, 3일 경과, 5일 경과, TP5%/SL3%]
- 적용 레짐: [CRISIS만, CRISIS+CAUTION]
- 총 5×4×2 = 40조합

### 구현
- 신규 스크립트: `scripts/hedge_etf_multiverse.py`
- `backtest/backtester.py` 서브클래스로 레짐일 인버스 매수 훅 추가
- FDR 데이터 수집: `scripts/fetch_inverse_etf.py`

### 검증
- 2020-03 코로나 구간, 2022 하락장 구간 집중 검증
- MDD 감소폭, 샤프 변화, 전체 수익률 손실 측정
- 인버스 ETF 상장일 이전 기간은 제외

### 출력
`docs/superpowers/reports/hedge_etf-result.md`

---

## 스트림 4: quant_pead (실적 드리프트)

### 가설
한국시장 PEAD(Post-Earnings Announcement Drift)는 개인 비중이 높아 미국보다 강하다(다수 논문). `dart_events` 3,543건을 활용하여 어닝 서프라이즈 드리프트를 별도 수익원으로 투입한다.

### 데이터
- `robotrader_backtest.dart_events`: 3,543건 (스키마 사전 조사 필요)
- 과거 실적 컨센서스가 없으면 간이 SUE 계산: `(actual_EPS - prior_4Q_avg_EPS) / stddev(prior_4Q_EPS)`

### 피처
- `SUE`: 간이 Standardized Unexpected Earnings
- `announce_date`: 발표일
- `drift_start`: 발표 +1 거래일
- `drift_end`: 발표 +20 거래일

### 멀티버스 축
- SUE 분위: [상위 5%, 상위 10%, 하위 5%, 하위 10%]
- 보유일: [+5, +10, +20, +40]
- 슬롯 수: [2, 3, 5] (별도 포트폴리오)
- 총 4×4×3 = 48조합

### 구현
- 신규 스크립트: `scripts/pead_backtest.py`
- 기존 팩터 전략과 독립 포트폴리오로 병렬 시뮬레이션
- 결합 시뮬레이션: 메인 포트폴리오에서 N슬롯 할당 시 전체 샤프

### 검증
- dart_events 스키마 확인 후 SUE 계산 가능 여부 판정 (불가 시 단순 이벤트 드리프트로 축소)
- 연도별 일관성, 생존자 편향 경고

### 출력
`docs/superpowers/reports/pead-result.md`

---

## 스트림 5: quant_intraday_vwap (분봉 필터)

### 가설
전일 분봉에서 계산한 VWAP 이격·종가 강도, 당일 09:00~09:05 갭·방향이 매수 후보 필터로 유효하다.

### 데이터
- `robotrader.minute_candles`: 2025-02-24 ~ 2026-04-10, 1,100종목, 374만 건
- 기존 거래 1,471건 (베이스라인 백테스트 출력)
- 주의: 하루 30~40 종목만 저장 → 전체 유니버스 백테스트 불가, 기존 거래 회고 한정

### 피처 A (전일 분봉)
- `vwap_gap`: (전일 종가 / 전일 VWAP - 1) × 100
- `closing_30min_ret`: 전일 14:30~15:30 수익률
- `intraday_vol_ratio`: 전일 오전 변동성 / 오후 변동성

### 피처 B (당일 개장)
- `open_gap`: (당일 시가 / 전일 종가 - 1) × 100
- `first_5min_ret`: 09:00~09:05 수익률
- `first_5min_vol_ratio`: 09:00~09:05 거래량 / 전일 평균 5분 거래량

### 멀티버스
- 우선 `blind_pattern_discovery.py` 확장: 피처 6개 추가 → 승/패 Cohen's d 탐색
- Top 신호에 대해 임계값 컷 멀티버스 (각 피처 [분위 20%, 40%, 60%, 80%])

### 구현
- 신규 스크립트: `scripts/intraday_feature_discovery.py`
- 분봉 DB 어댑터: 기존 1,471 거래 각각에 대해 매수 당일·전일 분봉 로드
- 피처 생성 후 `blind_pattern_discovery.py` 방식으로 통계 검정

### 리스크
- 하루 30~40종목 제약 → 통계 검정력 제한
- 결과가 유의해도 전체 유니버스 적용 시 편향 가능성
- 부족 시 "분봉 수집 확대 후 재분석" 권고로 종료

### 출력
`docs/superpowers/reports/intraday_vwap-result.md`

---

## 실행 순서

1. 본 스펙 문서 커밋
2. `superpowers:writing-plans` 스킬 진입 → 5개 스트림 각각 플랜 작성
3. 5개 워크트리 생성: `D:/GIT/RoboTrader_quant_<stream>`, 브랜치 `stream/<name>`
4. 각 워크트리에 병렬 에이전트 투입
5. 결과 수집 후 통합 보고 + main 병합 여부 결정

## 종료 조건

- 5개 스트림 각자 리포트 생성 완료
- 통합 표: 스트림별 베이스라인 대비 샤프·MDD·승률 개선폭
- 실전 투입 후보 우선순위 제시
