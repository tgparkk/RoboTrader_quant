# 퀀트 전략 전환 진행 현황

## 1. 데이터 수집/지표 파이프라인
- `api/kis_financial_api.py`에 KIS 재무비율(`FHKST66430300`), 손익계산서(`FHKST66430200`) API 대응 함수를 구축했습니다.  
  - FinancialRatioEntry: `stac_yymm`, 매출/영업/순이익 증가율, ROE/EPS/SPS/BPS, 유보·부채 비율을 그대로 매핑.  
  - IncomeStatementEntry: 결산 월 기준 매출, 매출원가, 매출총이익, 감가상각, 판관비, 영업/경상/특별/당기순이익 등을 매핑.
- `tests/manual_ratio_test.py`, `tests/manual_income_statement_test.py` 등 수동 테스트 스크립트로 실제 응답을 확인할 수 있게 했습니다.

## 2. DB 스키마 및 저장 로직
- `db/database_manager.py`에 `financial_data`, `quant_factors`, `quant_portfolio` 테이블을 정의하고 upsert API를 추가했습니다.  
  - `get_quant_portfolio(calc_date)`로 오늘 날짜의 상위 포트폴리오를 조회할 수 있습니다.  
  - `save_quant_factors`, `save_quant_portfolio`는 기존 데이터를 날짜 기준으로 삭제 후 일괄 저장하도록 구성했습니다.

## 3. 스크리닝 서비스
- 새로운 `core/quant/quant_screening_service.py`를 만들었습니다.  
  - 전체 종목 리스트를 순회하며 재무비율·손익계산서·일봉 데이터를 수집하고 Value/Momentum/Quality/Growth 점수를 계산합니다.  
  - 점수/총점을 `quant_factors`, 상위 50개를 `quant_portfolio`에 저장합니다. (기본 Universe 최대 500개)

## 4. 장중 연동
- `CandidateSelector`는 DB를 참조해 `get_quant_candidates()`가 오늘 포트폴리오 상위 종목을 반환하도록 수정했습니다.  
  - DB 데이터가 없는 경우 기존 로직(일일 후보 선별)으로 자동 fallback합니다.
- `main.DayTradingBot`에 `QuantScreeningService`를 주입하고 `_system_monitoring_task`에서 15:40 이후 하루 한 번 스크리닝을 실행하도록 스케줄링했습니다.  
  - 결과는 텔레그램으로 통지되며 `_check_condition_search()`에서 즉시 활용됩니다.

## 5. 스코어링/정렬/저장 고도화 (7단계)
- 최종 점수 = Value(30%) + Momentum(30%) + Quality(20%) + Growth(20%) 적용  
- 동점 시 Momentum 우선 정렬 후 상위 50개 선정 저장

## 6. 스케줄러 안정화 (8단계)
- 일일 스크리닝 실행에 오류 재시도(기본 3회) 적용  
- 완료 시 상위 5개 종목 텔레그램 요약 알림

## 7. 리밸런싱 시스템 (9단계)
- `core/quant/quant_rebalancing_service.py` 추가  
  - 보유 vs 목표 비교로 매도/매수/유지 리스트 산출  
  - 동등 비중 매수, 일간/주간/월간 주기 지원  

## 8. 전략 통합 (10단계)
- `strategies/quant_strategy.py`: 상위 50 포함 시 BUY 신호  
- `strategies/combined_strategy.py`: quant 40%, pullback 20%, momentum 15%, breakout 10%, 기타 15%

## 9. 테스트 및 백테스트 (11단계)
- 단위 테스트 추가:  
  - `tests/test_quant_factors.py` (팩터/점수 검증)  
  - `tests/test_primary_filter.py` (1차 필터)  
  - `tests/test_rebalancing.py` (리밸런싱 계획/실행)  
- 백테스트 스크립트: `backtests/quant_monthly_backtest.py` (월간 리밸런싱)

## 10. 실행 환경 및 운영 개선
- `run_robotrader.bat` 개선: UTF-8 모드, 로그 파일 자동 생성, 선택적 pip/requirements 설치, PID 경고  
- `config/trading_config.json`: `"paper_trading": true` (기본값)로 가상 매매 모드 지원  
  - 실제 매매 전환은 `"paper_trading": false`로 설정

## 11. ML 멀티팩터 시스템 구현 (2025-11-19)

### 11.1 데이터베이스 스키마 확장
- `db/database_manager.py`에 ML 멀티팩터 시스템용 테이블 추가:
  - **`daily_prices`**: 일별 가격 데이터 (ML용 확장 버전)
    - 기본 OHLCV 데이터 + 수익률(1일/5일/20일), 변동성(20일), 시가총액
  - **`financial_statements`**: 재무제표 데이터 (ML용 확장 버전)
    - Value 팩터용: PER, PBR, PCR, PSR, 배당수익률, 배당성장률, 배당여력, NAV 할인율, 청산마진, 이익안정성
    - Quality 팩터용: ROE, ROA, ROIC, 부채비율, 이자보상배수, 유동비율, 당좌비율, 영업마진, 순이익마진, FCF 수익률, OCF/순이익, CAPEX 비율, 현금비율
    - Growth 팩터용: 매출/이익/영업이익 성장률
  - **`daily_factor_scores`**: 일별 팩터 점수 (0-100 스케일)
    - Value, Momentum, Quality, Growth 점수 및 총점, 순위 정보
  - **`ml_features`**: ML 학습용 45개 상세 지표
    - Value 지표 10개, Momentum 지표 10개, Quality 지표 15개, Growth 지표 10개
    - 라벨: 5일/20일 목표 수익률
  - **`trading_history`**: 거래 이력 (ML용 확장 버전)
    - 진입/청산 점수, 보유일수, 수익률 등

### 11.2 ML 데이터 수집 모듈
- `core/ml_data_collector.py`: `MLDataCollector` 클래스 구현
  - `save_daily_price_data()`: 일별 가격 데이터 수집 및 저장
    - KIS API를 통해 최소 3년치 과거 데이터 수집
    - 수익률 및 변동성 자동 계산
  - `save_financial_data()`: 재무비율 및 손익계산서 데이터 수집 및 저장
    - 연간/분기 데이터 수집 및 업데이트

### 11.3 팩터 계산 모듈 (45개 지표)
- `core/factors/` 디렉토리에 4개 팩터 모듈 구현:
  - **`value_factor.py`**: Value 팩터 (10개 지표, 30% 가중치)
    - 밸류에이션 점수: PER, PBR, PCR, PSR
    - 배당 점수: 배당수익률, 배당성장률, 배당여력
    - 자산 가치 점수: NAV 할인율, 청산마진
    - 이익 안정성 점수
  - **`momentum_factor.py`**: Momentum 팩터 (10개 지표, 30% 가중치)
    - 가격 모멘텀: 1개월/3개월/6개월/12개월 수익률
    - 거래량 모멘텀: 1개월/3개월 거래량 추세
    - 상대 강도: 시장/섹터 대비 상대 수익률
    - 지속성: 상승일 비율, 52주 신고가 근접도
  - **`quality_factor.py`**: Quality 팩터 (15개 지표, 20% 가중치)
    - 수익성: ROE, ROA, ROIC, 영업마진, 순이익마진
    - 안정성: 부채비율, 이자보상배수, 유동비율, 당좌비율, 순부채비율
    - 현금흐름 품질: FCF 수익률, OCF/순이익, CAPEX 비율, 현금비율
    - 이익 품질 점수
  - **`growth_factor.py`**: Growth 팩터 (10개 지표, 20% 가중치)
    - 매출 성장: 1년/3년/5년 CAGR
    - 이익 성장: 1년/3년 CAGR, 영업이익 성장률
    - 성장 효율성: 이익 레버리지, 마진 개선도, ROE 개선도
    - 성장 지속성 점수

### 11.4 ML 팩터 계산기
- `core/ml_factor_calculator.py`: `MLFactorCalculator` 클래스 구현
  - `calculate_total_score()`: 4개 팩터 점수를 가중 평균하여 총점 계산 (0-100 스케일)
  - `save_factor_scores()`: 일별 팩터 점수 및 순위를 `daily_factor_scores` 테이블에 저장
  - `save_ml_features()`: 45개 상세 지표를 `ml_features` 테이블에 저장
    - 각 팩터 모듈에서 계산된 지표 수집
    - 재무 데이터 및 가격 데이터 통합
    - 목표 수익률(5일/20일) 계산 및 저장

### 11.5 ML 포트폴리오 빌더
- `core/ml_portfolio_builder.py`: `MLPortfolioBuilder` 클래스 구현
  - `build_portfolio()`: 총점 기준 상위 N개 종목 선정 및 가중치 할당
    - 기본 상위 10개 종목 선정
    - 동등 가중 또는 점수 기반 가중치 할당

### 11.6 ML 스크리닝 서비스
- `core/ml_screening_service.py`: `MLScreeningService` 클래스 구현
  - 일일 자동 스크리닝 워크플로우 관리
  - 데이터 수집 → 팩터 계산 → 포트폴리오 구성 → DB 저장

### 11.7 통합 데이터 로더
- `utils/unified_data_loader.py`: `UnifiedDataLoader` 클래스 구현
  - DB 우선, 파일 캐시 폴백 지원
  - 일봉/분봉 데이터 통합 로드 인터페이스
  - 기존 파일 기반 캐시 시스템과의 호환성 유지

### 11.8 개발 환경 개선
- 커밋 메시지 가이드라인 추가:
  - `docs/COMMIT_GUIDELINES.md`: 커밋 메시지 작성 가이드
  - `.gitconfig_commit_template`: 커밋 메시지 템플릿
  - `.gitattributes`: 파일 인코딩 설정
  - Git 설정: UTF-8 인코딩, 커밋 템플릿 적용
  - 한글 인코딩 문제 방지를 위해 영어 커밋 메시지 사용 권장

### 11.9 구현 상태
- ✅ 데이터베이스 스키마 설계 및 구현
- ✅ ML 데이터 수집 모듈 구현
- ✅ 4개 팩터 계산 모듈 구현 (45개 지표)
- ✅ ML 팩터 계산기 및 피처 저장 구현
- ✅ ML 포트폴리오 빌더 구현
- ✅ ML 스크리닝 서비스 구현
- ✅ 통합 데이터 로더 구현
- ⚠️ KOSPI/섹터 데이터 수집 (상대 강도 계산용) - TODO
- ⚠️ 초기 데이터 수집 스크립트 (3년치 과거 데이터) - TODO
- ⚠️ 백테스트 시스템 통합 - TODO
- ⚠️ main.py 통합 - TODO

## 다음 단계
1. **팩터 계산 정밀화**  
   - Value/Momentum/Quality/Growth 점수식을 사용자 정의 기준(문서 3~6단계)에 맞게 세분화  
   - Growth 팩터: 손익 API 응답을 바탕으로 연간/분기 성장률 계산
2. **시장 필터/리스크 조건**  
   - 최소 시총, 거래대금, 주가 범위, 관리종목 제외 등 1차 필터를 실제 수집 데이터 기반으로 구현
3. **15:40 스케줄러 안정화**  
   - 실행 시간/예외 처리 개선, 텔레그램에 상위 종목 리스트와 변동 정보를 함께 발송
4. **백테스트/리밸런싱**  
   - `quant_portfolio` 데이터를 이용해 포트폴리오 비교→ 매수·매도 로직을 자동화  
   - 주간/월간 리밸런싱 옵션과 텔레그램 알림 흐름 구현

