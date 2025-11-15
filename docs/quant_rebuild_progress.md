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

