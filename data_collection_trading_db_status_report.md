# 데이터 수집 및 매매 판단, DB 저장 상태 종합 보고서

**최종 업데이트**: 2025-12-28 KST
**이전 확인**: 2025-12-27 01:30 KST

---

## 📊 종합 평가: ✅ 정상 작동 + 안정성 대폭 개선

모든 주요 기능이 정상적으로 작동하고 있으며, 데이터 수집 로직의 안정성과 성능이 크게 개선되었습니다.

### 🆕 2025-12-28 업데이트 내역

#### ✅ 장 마감 후 자동 리포트 생성
- **15:35 자동 실행**: 장 마감 후 일일 매매 리포트 자동 생성
- **주요 내용**:
  1. 오늘의 매매 내역 (매수/매도)
  2. 현재 보유 종목 및 평가손익
  3. 누적 수익률 (실현/미실현)
  4. 퀀트 포트폴리오 현황 (Top 10)
  5. 오늘의 데이터 수집 현황
- **코드 위치**:
  - `main.py:748-757` - 메인 루프 자동 실행
  - `scripts/daily_trading_summary.py` - 리포트 생성 로직
  - `after_market_report.py` - 수동 실행 스크립트
- **실행 흐름**:
  - 15:30 ML 데이터 수집
  - 15:35 **일일 매매 리포트 생성** (NEW!)
  - 15:40 퀀트 스크리닝

#### ✅ 데이터 수집 안정성 개선 (6가지)
1. **가격 데이터 검증 추가**
   - OHLC 관계 검증 (open ≤ high, low ≤ close)
   - 거래량 일관성 확인
   - 급격한 가격 변동 감지 (50% 이상)
   - 코드 위치: `core/ml_data_collector.py:256-297`

2. **API Rate Limiting 추가**
   - 0.2초 간격으로 API 호출 제한
   - API 차단(Ban) 방지
   - 코드 위치: `core/ml_data_collector.py:691-721`

3. **수익률 계산 최적화**
   - N+1 쿼리 문제 해결 (1000번 → 1번 쿼리)
   - 성능 약 100배 향상
   - 코드 위치: `core/ml_data_collector.py:205-276`

4. **재무데이터 원자성 보장**
   - INSERT + UPDATE 원자적 처리
   - 부분 저장 방지
   - 코드 위치: `core/ml_data_collector.py:485-778`

5. **에러 로깅 개선**
   - API 호출별 에러 로깅
   - 성공/실패 카운트 및 요약
   - 코드 위치: `core/ml_data_collector.py:383-409, 747-766`

6. **API 필드 검증 강화**
   - 필수 필드 누락 감지
   - API 스키마 변경 조기 감지
   - 코드 위치: `core/ml_data_collector.py:183-192, 482-718`

**상세 내용**: [DATA_COLLECTION_IMPROVEMENTS.md](DATA_COLLECTION_IMPROVEMENTS.md)

### 🆕 2025-12-27 업데이트 내역

#### ✅ 대차대조표 데이터 수집 추가
- **기능**: 보유 종목의 대차대조표 데이터 수집 및 저장
- **수집 완료**: 49개 보유 종목 (100% 성공)
- **저장 테이블**: `financial_statements` (기존 테이블에 컬럼 추가)
- **새 컬럼**: `total_assets`, `current_assets`, `current_liabilities`, `total_liabilities`, `total_equity`
- **코드 위치**:
  - API: `api/kis_financial_api.py` - `get_balance_sheet()`
  - 수집: `core/ml_data_collector.py` - `save_financial_data()`
  - 수집 스크립트: `collect_balance_sheet.py`
- **수정 사항**:
  - KIS API 필드명 오류 수정 (flow_aset → cras, fix_aset → fxas)
  - 상세 내용: `BALANCE_SHEET_FIX.md` 참조

#### ✅ Quality Factor 계산 개선
- **기능**: ROA와 유동비율을 실제 재무데이터로 계산
- **개선 전**: 근사값 사용 (ROA = ROE * 0.6, 유동비율 = 100 - 부채비율)
- **개선 후**: 정확한 계산 (ROA = 순이익 / 총자산, 유동비율 = 유동자산 / 유동부채 * 100)
- **코드 위치**: `core/quant/quant_screening_service.py` - `_calc_quality_score()`
- **기대 효과**: Quality Score 정확도 향상, 재무 안정성 기반 종목 선별 개선

---

## 1️⃣ 데이터 수집 현황

### ✅ 후보 종목 선정
- **상태**: 정상 작동
- **선정 종목 수**: 3개
- **선정 시간**: 2025-12-17 15:33:35
- **선정된 종목**:
  1. 011780 (동화약품화학): 55.0점
  2. 006280 (녹십자): 55.0점
  3. 001060 (JW중외제약): 50.0점
- **저장 테이블**: `candidate_stocks`
- **코드 위치**: `core/candidate_selector.py`

### ✅ 일봉 데이터 수집 및 저장
- **상태**: 정상 작동
- **수집률**: 3/3개 종목 (100%)
- **데이터 건수**: 종목당 3건 (오늘 날짜 포함)
- **최신 데이터**: 2025-12-17 (오늘 날짜)
- **저장 테이블**: `daily_prices`
- **코드 위치**: 
  - 수집: `core/intraday_stock_manager.py` - `_collect_daily_data_only()`
  - 저장: `core/ml_data_collector.py` - `_save_daily_prices_to_db()`
- **저장 방식**: `INSERT OR REPLACE` (중복 방지)

### ⚠️ 분봉 데이터 수집
- **상태**: 장 마감 후 저장 예정
- **저장 위치**: `stock_prices` 테이블
- **오늘 날짜 파일**: 아직 생성되지 않음 (장 마감 후 저장 예정)
- **참고**: 분봉 데이터는 장 마감 후 자동으로 저장됨

---

## 2️⃣ 매매 판단 현황

### ✅ 리밸런싱 실행
- **상태**: 정상 작동
- **실행 시간**: 2025-12-17 09:05:16
- **매수 실행**: 2건
- **매도 실행**: 25건
- **코드 위치**: `main.py` - `_execute_rebalancing_async()`
- **리밸런싱 서비스**: `core/quant/quant_rebalancing_service.py`

### ✅ 매매 판단 로직
- **리밸런싱 모드**: 활성화
- **매수 판단**: 09:05 리밸런싱으로만 매수
- **매도 판단**: 장중 손절/익절 매도 판단 활성화
- **코드 위치**: `core/trading_decision_engine.py`

---

## 3️⃣ DB 저장 현황

### ✅ 가상 매매 기록 저장
- **상태**: 정상 저장
- **총 기록 수**: 27건
  - 매수: 2건 (총 2,683,500원)
  - 매도: 25건 (총 13,348,730원)
- **저장 테이블**: `virtual_trading_records`
- **코드 위치**: 
  - 매수 저장: `db/database_manager.py` - `save_virtual_buy()`
  - 매도 저장: `db/database_manager.py` - `save_virtual_sell()`
  - 호출 위치: `core/order_manager.py` - `place_buy_order()`, `place_sell_order()`
- **주요 매수 종목**:
  - 002380 (KCC): 3주 @418,500원
  - 012330 (현대모비스): 4주 @357,000원

### ✅ 퀀트 팩터 점수 저장
- **상태**: 정상 저장
- **저장 종목 수**: 357개 종목
- **저장 테이블**: `quant_factors`
- **코드 위치**: `core/ml_factor_calculator.py` - `save_factor_scores()`

### ✅ 퀀트 포트폴리오 저장
- **상태**: 정상 저장
- **저장 종목 수**: 30개 종목
- **저장 테이블**: `quant_portfolio`
- **코드 위치**: `core/ml_portfolio_builder.py`
- **상위 5개 종목**:
  1. 402340 (SK바이오팜): 75.2점
  2. 161390 (한국타이어앤테크놀로지): 73.9점
  3. 000050 (경방): 72.5점
  4. 009970 (한화솔루션): 72.3점
  5. 019180 (티에이치엔): 72.0점

---

## 4️⃣ 코드 검증 결과

### ✅ 데이터 수집 코드
1. **일봉 데이터 수집**
   - `IntradayStockManager._collect_daily_data_only()`: 일봉 데이터 수집
   - `IntradayStockManager._save_daily_to_db()`: DB 저장 호출
   - `MLDataCollector._save_daily_prices_to_db()`: 실제 DB 저장 로직
   - **검증**: ✅ 정상 작동, 오류 처리 및 로깅 포함

2. **후보 종목 선정**
   - `CandidateSelector`: 후보 종목 선정 및 `candidate_stocks` 테이블 저장
   - **검증**: ✅ 정상 작동

### ✅ 매매 판단 코드
1. **리밸런싱 실행**
   - `main.py._execute_rebalancing_async()`: 리밸런싱 실행
   - `OrderManager.place_buy_order()`: 매수 주문 실행
   - **검증**: ✅ 정상 작동, 가상 매매 기록 저장 포함

2. **매매 판단 엔진**
   - `TradingDecisionEngine`: 매수/매도 판단 로직
   - **검증**: ✅ 정상 작동

### ✅ DB 저장 코드
1. **가상 매매 기록 저장**
   - `DatabaseManager.save_virtual_buy()`: 가상 매수 기록 저장
   - `DatabaseManager.save_virtual_sell()`: 가상 매도 기록 저장
   - **검증**: ✅ 정상 작동, 손익 계산 포함

2. **일봉 데이터 저장**
   - `MLDataCollector._save_daily_prices_to_db()`: 일봉 데이터 저장
   - **검증**: ✅ 정상 작동, `INSERT OR REPLACE` 사용으로 중복 방지

---

## 5️⃣ 발견된 문제점 및 개선 사항

### ⚠️ 분봉 데이터
- **상태**: 장 마감 후 저장 예정 (정상)
- **설명**: 분봉 데이터는 장 마감 후 자동으로 저장되므로 현재 상태는 정상입니다.

### ✅ 모든 기능 정상 작동
- 데이터 수집: ✅ 정상
- 매매 판단: ✅ 정상
- DB 저장: ✅ 정상

---

## 6️⃣ 결론

### 전체 평가: ✅ 정상 작동

**작동한 기능:**
- ✅ 후보 종목 선정 (3개)
- ✅ 일봉 데이터 수집 및 저장 (3/3개, 100%)
- ✅ 가상 매매 기록 저장 (27건: 매수 2건, 매도 25건)
- ✅ 퀀트 팩터 점수 계산 및 저장 (357개 종목)
- ✅ 퀀트 포트폴리오 구성 및 저장 (30개 종목)
- ✅ 리밸런싱 실행 (매수 2건, 매도 25건)

**의도된 동작:**
- ⚠️ 분봉 데이터는 장 마감 후 저장 (정상)

### 권장 사항
1. ✅ 현재 상태로 정상 작동 중
2. ✅ 모든 데이터 수집 및 저장 기능이 정상적으로 작동
3. ✅ 가상 매매 기록이 정상적으로 저장되고 있음
4. ✅ 매매 판단 로직이 정상적으로 작동

---

## 📝 참고사항

- **데이터베이스**: `data/robotrader.db`
- **확인 스크립트**: `check_db_status.py` (새로 생성)
- **로그 파일**: `logs/trading_YYYYMMDD.log`
- **분봉 캐시**: `cache/minute_data/`
- **일봉 캐시**: `cache/daily/`

---

**보고서 생성 시간**: 2025-12-17 22:34 KST  
**분석 기준**: 데이터베이스 기록 및 코드 검증
















