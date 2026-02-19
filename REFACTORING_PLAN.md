# RoboTrader 퀀트 시스템 리팩토링 계획서

## 개요

**목표**: 1000줄 초과 파일 5개를 모듈화하여 유지보수성 향상

**원칙**: 파일당 최대 1000줄 제한 (이상적으로는 300-500줄)

---

## 현황 분석

### 1000줄 초과 파일 (5개)

| 순위 | 파일 | 라인 수 | 초과량 | 우선순위 |
|------|------|---------|--------|----------|
| 1 | [main.py](#1-mainpy-1732-lines) | 1,732 | +732 | P1 (Critical) |
| 2 | [core/intraday_stock_manager.py](#2-coreintradaystockmanagerpy-1690-lines) | 1,690 | +690 | P1 (Critical) |
| 3 | [db/database_manager.py](#3-dbdatabasemanagerpy-1397-lines) | 1,397 | +397 | P1 (Critical) |
| 4 | [visualization/chart_renderer.py](#4-visualizationchartrendererpy-1067-lines) | 1,067 | +67 | P2 (High) |
| 5 | [core/trading_stock_manager.py](#5-coretradingstockmanagerpy-1052-lines) | 1,052 | +52 | P1 (Critical) |

**총계**: 6,938줄 → 약 4,500줄 (17개 모듈로 분산)

---

## 1. main.py (1,732 lines)

### 현재 구조

**주요 섹션**:
- 초기화 & 설정 (185 lines)
- 6개 비동기 태스크 (257 lines)
- 매매 판단 로직 (164 lines)
- 리밸런싱 시스템 (257 lines) - **최대 단일 메서드 198줄**
- 시스템 모니터링 (215 lines)
- 스크리닝 & 분석 (220 lines)
- 주문 & 포지션 관리 (214 lines)
- 상태 복원 & 유틸리티 (315 lines)

### 리팩토링 계획

#### Phase 1: Async Task 분리

**생성할 파일** (6개):

1. **`core/tasks/data_collection_task.py`** (40 lines)
   - 실시간 데이터 수집 wrapper

2. **`core/tasks/order_monitoring_task.py`** (40 lines)
   - 주문 모니터링 wrapper

3. **`core/tasks/telegram_task.py`** (50 lines)
   - 텔레그램 봇 통합

4. **`core/tasks/rebalancing_task.py`** (300 lines) ⭐ **최대**
   - `_rebalancing_task()` + `_execute_rebalancing_async()`
   - `_wait_for_sell_orders_completion()`
   - `_update_keep_list_profit_loss()`
   - `_send_rebalancing_result_notification()`

5. **`core/tasks/system_monitoring_task.py`** (150 lines)
   - API 리프레시 이벤트
   - 장 마감 후 이벤트 (15:30+)
   - 퀀트 스크리닝 이벤트 (15:40)
   - 상태 로깅

6. **`core/tasks/screening_task.py`** (220 lines)
   - `_run_quant_screening()`
   - `_run_ml_data_collection()`
   - `_run_ml_screening()`

#### Phase 2: Trading Decision 분리

7. **`core/trading/buy_decision_analyzer.py`** (100 lines)
   - `_analyze_buy_decision()` 캡슐화
   - 자금 체크 로직
   - 주문 실행 래퍼

8. **`core/trading/sell_decision_analyzer.py`** (50 lines)
   - `_analyze_sell_decision()` 캡슐화

#### Phase 3: State Management 분리

9. **`core/state/position_recovery.py`** (180 lines)
   - `_restore_todays_candidates()` 리팩토링
   - DB → 메모리 포지션 복원

10. **`core/state/emergency_recovery.py`** (130 lines)
    - `emergency_sync_positions()` 리팩토링
    - 계좌 잔고 동기화

#### Phase 4: Initialization 분리

11. **`core/bootstrap.py`** (120 lines)
    - `__init__()` 구현 이동
    - 서비스 인스턴스화 분리

#### Phase 5: Utilities 분리

12. **`utils/price_utils.py`** (20 lines)
    - `_round_to_tick()`
    - `_check_duplicate_process()`
    - `_load_config()`

### 목표 라인 수

- **main.py**: 1,732 → **400 lines** (-77% ✅)
- **신규 파일 12개**: 약 1,400 lines

### 기대 효과

- ✅ 각 모듈 50-300줄 (최적 유지보수성)
- ✅ 단일 책임 원칙 준수
- ✅ 독립적 테스트 가능
- ✅ 재사용 가능한 태스크 모듈
- ✅ 명확한 의존성 주입
- ✅ 인지 부하 감소

---

## 2. core/intraday_stock_manager.py (1,690 lines)

### 현재 구조

**주요 섹션**:
- 주식 분봉 데이터 모델 (18 lines)
- 초기화 & 설정 (41 lines)
- 종목 선정 & 데이터 수집 (162 lines)
- 과거 데이터 수집 (224 lines)
- Fallback 데이터 수집 (120 lines)
- 실시간 데이터 업데이트 (186 lines)
- 데이터 품질 검증 (83 lines)
- 종목 분석 & 조회 (207 lines)
- 배치 작업 (170 lines)

### 리팩토링 계획

**생성할 파일** (5개):

1. **`core/intraday_data_collection.py`** (400-450 lines)
   - `collect_full_trading_day_data()`
   - `_adjust_selection_time_on_failure()`
   - `_filter_today_data()`
   - `_validate_candle_continuity()`

2. **`core/intraday_data_fallback.py`** (180-220 lines)
   - `collect_minute_data_legacy()`
   - `_retry_with_adjusted_time()`
   - 중복 재시도 로직 통합

3. **`core/intraday_realtime_updater.py`** (350-400 lines)
   - `update_realtime_candles()` 오케스트레이터
   - `_get_latest_minute_bar()` 이동
   - `_validate_before_merge()` (1차 검증)
   - `_validate_after_merge()` (2차 검증)
   - `_validate_before_store()` (3차 검증)

4. **`core/intraday_data_quality.py`** (250-300 lines)
   - `validate_data_quantity()`
   - `validate_time_continuity()`
   - `validate_price_anomalies()`
   - `validate_data_freshness()`
   - `validate_date_consistency()`
   - `DataQualityReport` dataclass

5. **`core/intraday_batch_processor.py`** (200-250 lines)
   - `execute_batch_update()`
   - `_process_incomplete_stocks()`
   - `_execute_batch_with_rate_limiting()`
   - `_monitor_batch_quality()`

### 목표 라인 수

- **intraday_stock_manager.py**: 1,690 → **400-500 lines** (-76% ✅)
- **신규 파일 5개**: 약 1,600 lines

### 주요 개선

- ✅ 187줄 메서드 분리 (historical data collection)
- ✅ 3단계 검증 로직 명확한 분리
- ✅ 배치 처리 독립 모듈화
- ✅ 품질 검증 재사용 가능

---

## 3. db/database_manager.py (1,397 lines)

### 현재 구조

**주요 섹션**:
- 테이블 스키마 & 초기화 (247 lines) - **최대 단일 메서드**
- 후보 종목 작업 (63 lines)
- 가격 데이터 작업 (77 lines)
- 재무 데이터 작업 (74 lines)
- 퀀트 팩터 작업 (164 lines)
- 가상 거래 작업 (215 lines)
- 실제 거래 작업 (126 lines)
- 데이터 정리 & 분석 (44 lines)

### 리팩토링 계획

**생성할 파일** (4개):

1. **`db/database_schema.py`** (350-400 lines)
   - `create_candidate_stocks_table()`
   - `create_price_tables()`
   - `create_financial_tables()`
   - `create_trading_tables()`
   - `create_indices()`
   - 스키마 버전 관리
   - `TableSchema` enum

2. **`db/trading_records_repository.py`** (350-400 lines)
   - `save_virtual_buy()` / `save_virtual_sell()`
   - `save_real_buy()` / `save_real_sell()`
   - `get_virtual_open_positions()`
   - `get_virtual_trading_history()`
   - `get_virtual_trading_stats()`
   - 공통 `calculate_profit_metrics()` 유틸리티
   - `TradingRecordRepository` 클래스

3. **`db/quant_data_repository.py`** (200-250 lines)
   - `save_quant_factors()`
   - `save_quant_portfolio()`
   - `get_quant_factors()`
   - `get_quant_portfolio()`
   - `QuantDataRepository` 클래스

4. **`db/financial_data_repository.py`** (200-250 lines)
   - `upsert_financial_data()` 리팩토링
   - `get_financial_data()`
   - 데이터 변환 헬퍼
   - `FinancialDataRepository` 클래스

### 목표 라인 수

- **database_manager.py**: 1,397 → **300-400 lines** (-73% ✅)
- **신규 파일 4개**: 약 1,200 lines

### 주요 개선

- ✅ Repository 패턴 적용
- ✅ 247줄 스키마 메서드 분리
- ✅ 중복 손익 계산 로직 통합
- ✅ 도메인별 명확한 분리

---

## 4. visualization/chart_renderer.py (1,067 lines)

### 현재 구조

**주요 섹션**:
- 초기화 (12 lines)
- 전략 차트 생성 (75 lines)
- 기본 차트 생성 (37 lines)
- 캔들스틱 그리기 (65 lines)
- 인디케이터 그리기 (19 lines)
- 시그널 시각화 (212 lines) - **145줄 단일 메서드**
- 가격박스/볼린저 그리기 (152 lines)
- 거래량 차트 (26 lines)
- X축 레이블링 (263 lines) - **138줄 단일 메서드**
- 데이터 검증 (68 lines)

### 리팩토링 계획

**생성할 파일** (4개):

1. **`visualization/chart_data_processor.py`** (250-300 lines)
   - `_validate_and_clean_data()` 리팩토링
   - `_align_data_length()` 이동
   - 날짜/시간 형식 정규화
   - `ChartDataValidator` 클래스

2. **`visualization/chart_axis_manager.py`** (300-350 lines)
   - `calculate_1min_positions()`
   - `calculate_3min_positions()`
   - `calculate_5min_positions()`
   - `set_labels_for_1min()`
   - `set_labels_for_3min()`
   - `set_labels_for_5min()`
   - `set_basic_labels()`
   - `TimeAxisManager` 클래스

3. **`visualization/chart_signal_plotter.py`** (250-300 lines)
   - `_draw_buy_signals()`
   - `_draw_sell_signals()`
   - `_parse_trade_time()` 공통화 (DRY)
   - `_match_trade_to_candle()`
   - `_plot_buy_trades()`
   - `_plot_sell_trades()`
   - `SignalPlotter` 클래스

4. **`visualization/chart_indicator_renderer.py`** (200-250 lines)
   - `_draw_price_box()`
   - `_draw_bisector_line()`
   - `_draw_bollinger_bands()`
   - `_draw_multi_bollinger_bands()`
   - `IndicatorRenderer` 클래스

### 목표 라인 수

- **chart_renderer.py**: 1,067 → **200-250 lines** (-81% ✅)
- **신규 파일 4개**: 약 1,050 lines

### 주요 개선

- ✅ 145줄 시그널 메서드 분리
- ✅ 시간대별 X축 로직 통합
- ✅ DRY 원칙 적용 (시간 파싱)
- ✅ 모듈화된 렌더링

---

## 5. core/trading_stock_manager.py (1,052 lines)

### 현재 구조

**주요 섹션**:
- 초기화 & 의존성 (46 lines)
- 종목 선정 워크플로우 (79 lines)
- 매수 주문 실행 (80 lines)
- 매도 주문 실행 (92 lines)
- 모니터링 루프 (35 lines)
- 주문 완료 체크 (182 lines) - **96줄 + 69줄 메서드**
- 포지션 업데이트 (73 lines)
- 매도 판단 로직 (67 lines)
- 상태 관리 (88 lines)
- 포트폴리오 요약 (57 lines)

### 리팩토링 계획

**생성할 파일** (4개):

1. **`core/order_completion_handler.py`** (250-300 lines) ⭐ **최우선**
   - `process_buy_completion()` (통합)
   - `process_sell_completion()` (통합)
   - `update_virtual_position_info()` 공통 유틸리티
   - `OrderCompletionProcessor` 클래스
   - 중복 로직 제거 (96 + 69 + 135 lines)

2. **`core/position_monitor.py`** (200-250 lines)
   - `monitor_all_positions()` 단순화
   - `_check_order_completions()` 이동
   - `_update_position_prices()` 이동
   - `_check_positioned_stocks_for_sell()` 이동
   - `PositionMonitor` 클래스
   - 비동기 반복 로직

3. **`core/sell_decision_engine.py`** (150-200 lines)
   - `evaluate_all_positions()`
   - `_analyze_sell_for_stock()` 이동
   - `_execute_sell()` 이동
   - 손익 계산 헬퍼
   - `SellDecisionEngine` 클래스

4. **`core/state_logger.py`** (100-150 lines)
   - `_log_detailed_state_change()` 리팩토링
   - `_format_position_info()`
   - `_format_order_info()`
   - `_format_state_transition()`
   - `TradingStateLogger` 클래스

### 목표 라인 수

- **trading_stock_manager.py**: 1,052 → **400-500 lines** (-62% ✅)
- **신규 파일 4개**: 약 800 lines

### 주요 개선

- ✅ 중복 주문 완료 로직 통합 (300줄 → 250줄)
- ✅ 레이스 컨디션 이슈 제거
- ✅ 매도 로직 분리로 전략 교체 용이
- ✅ 로깅 테스트 가능

---

## 전체 요약

### Before & After

| 파일 | 현재 | 목표 | 감소율 | 신규 파일 수 |
|------|------|------|--------|-------------|
| main.py | 1,732 | 400 | -77% | 12 |
| intraday_stock_manager.py | 1,690 | 400-500 | -76% | 5 |
| database_manager.py | 1,397 | 300-400 | -73% | 4 |
| chart_renderer.py | 1,067 | 200-250 | -81% | 4 |
| trading_stock_manager.py | 1,052 | 400-500 | -62% | 4 |
| **총계** | **6,938** | **~1,900** | **-73%** | **29개** |

### 기대 효과

1. **유지보수성 향상**
   - 각 모듈 200-500줄 (이상적 크기)
   - 단일 책임 원칙 준수
   - 명확한 모듈 경계

2. **테스트 용이성**
   - 독립적 유닛 테스트 가능
   - 모의 객체(Mock) 주입 용이
   - 커버리지 향상

3. **코드 품질**
   - 중복 코드 제거 (DRY 원칙)
   - 명확한 의존성 관리
   - 재사용 가능한 컴포넌트

4. **개발 생산성**
   - 빠른 코드 탐색
   - 안전한 리팩토링
   - 병렬 개발 가능

### 구현 우선순위

#### Phase 1 (즉시 시작, 2주)
1. main.py → 6개 task 모듈 분리
2. database_manager.py → schema + repository 분리
3. trading_stock_manager.py → order completion handler 분리

#### Phase 2 (2주 차, 1.5주)
4. intraday_stock_manager.py → data quality + collection 분리
5. chart_renderer.py → axis manager + signal plotter 분리

#### Phase 3 (3.5주 차, 1.5주)
6. 나머지 모듈 분리
7. 유닛 테스트 작성
8. 통합 테스트 검증

#### Phase 4 (5주 차, 1주)
9. 문서화 업데이트
10. 성능 테스트
11. 배포

**총 예상 시간**: 4-6주

---

## 의존성 그래프 (리팩토링 후)

```
main.py (DayTradingBot - 오케스트레이터)
│
├── core/tasks/
│   ├── data_collection_task.py
│   ├── order_monitoring_task.py
│   ├── telegram_task.py
│   ├── rebalancing_task.py
│   ├── system_monitoring_task.py
│   └── screening_task.py
│
├── core/state/
│   ├── position_recovery.py
│   └── emergency_recovery.py
│
├── core/trading/
│   ├── buy_decision_analyzer.py
│   ├── sell_decision_analyzer.py
│   └── sell_decision_engine.py
│
├── core/
│   ├── intraday_data_collection.py
│   ├── intraday_data_fallback.py
│   ├── intraday_realtime_updater.py
│   ├── intraday_data_quality.py
│   ├── intraday_batch_processor.py
│   ├── order_completion_handler.py
│   ├── position_monitor.py
│   └── state_logger.py
│
├── db/
│   ├── database_schema.py
│   ├── trading_records_repository.py
│   ├── quant_data_repository.py
│   └── financial_data_repository.py
│
├── visualization/
│   ├── chart_data_processor.py
│   ├── chart_axis_manager.py
│   ├── chart_signal_plotter.py
│   └── chart_indicator_renderer.py
│
├── core/bootstrap.py
└── utils/price_utils.py
```

---

## 위험 관리

### 리팩토링 리스크

| 리스크 | 확률 | 영향 | 완화 전략 |
|--------|------|------|----------|
| 기존 기능 손상 | 중간 | 높음 | 단계별 테스트 + 회귀 테스트 |
| 성능 저하 | 낮음 | 중간 | 프로파일링 + 벤치마크 |
| 의존성 순환 | 중간 | 높음 | 명확한 계층 구조 설계 |
| 일정 지연 | 높음 | 중간 | 단계별 목표 + 점진적 배포 |

### 안전 장치

1. **브랜치 전략**: 각 Phase마다 별도 브랜치
2. **테스트**: Phase 완료 시 통합 테스트 필수
3. **롤백 계획**: 각 Phase는 독립적으로 롤백 가능
4. **코드 리뷰**: 주요 리팩토링은 리뷰 필수

---

## 체크리스트

### Phase 1 시작 전
- [ ] 현재 코드베이스 백업
- [ ] 리팩토링 브랜치 생성
- [ ] 기존 테스트 실행 확인
- [ ] 벤치마크 기준선 측정

### Phase 완료 기준
- [ ] 목표 라인 수 달성
- [ ] 모든 유닛 테스트 통과
- [ ] 통합 테스트 통과
- [ ] 성능 저하 없음 (±5% 이내)
- [ ] 코드 리뷰 승인
- [ ] 문서화 업데이트

### 전체 완료 기준
- [ ] 모든 1000줄 초과 파일 해결
- [ ] 전체 테스트 커버리지 70% 이상
- [ ] CI/CD 파이프라인 통과
- [ ] 프로덕션 배포 성공
- [ ] 모니터링 정상

---

## 참고 문서

- [CLAUDE.md](CLAUDE.md) - 시스템 아키텍처
- [DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md) - 데이터 수집 개선
- [README.md](README.md) - 프로그램 흐름

---

**마지막 업데이트**: 2025-12-28
**작성자**: Claude Sonnet 4.5
**상태**: 분석 완료, 구현 대기 중
