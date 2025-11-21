# 월요일 테스트 체크리스트

## 수정된 기능 확인 사항

### 1. 후보 종목 데이터베이스 저장 확인
- **확인 시점**: 15:30 이후 (ML 데이터 수집 후)
- **확인 방법**: 
  ```bash
  python check_db_today.py
  ```
- **예상 결과**: 오늘 날짜의 후보 종목이 `candidate_stocks` 테이블에 저장되어 있어야 함

### 2. ML 데이터 수집 확인
- **확인 시점**: 15:30 이후
- **확인 방법**: 로그 파일 확인
  - `logs/robotrader_quant_YYYYMMDD_HHMMSS.log` 파일에서 다음 메시지 확인:
    - "✅ 후보 종목 X개 데이터베이스 저장 완료"
    - "✅ ML 데이터 수집 완료: 가격 X/Y개, 재무 X/Y개"
- **예상 결과**: 
  - 가격 데이터 수집 성공 (이전 오류 해결됨)
  - 재무 데이터 수집 성공

### 3. 장 마감 후 데이터 저장 확인
- **확인 시점**: 15:30 이후
- **확인 방법**: 
  ```bash
  python check_today_data_collection.py
  ```
- **예상 결과**: 
  - 분봉 데이터: 후보 종목 수만큼 수집됨
  - 일봉 데이터: 후보 종목 수만큼 수집됨

### 4. 데이터 수집 상태 종합 확인
- **확인 시점**: 장 마감 후 (15:30 이후)
- **확인 방법**: 
  ```bash
  python data_collection_summary.py --days 1
  ```
- **예상 결과**: 
  - 오늘 날짜의 모든 후보 종목 데이터가 수집됨
  - 분봉: 100% 수집
  - 일봉: 100% 수집

## 로그에서 확인할 메시지

### 정상 동작 시 예상 로그:
```
2025-11-24 15:30:XX | __main__ | INFO | 📊 15:30 ML 데이터 수집 시작
2025-11-24 15:30:XX | core.candidate_selector | INFO | 🔍 일일 매수 후보 종목 선정 시작
2025-11-24 15:33:XX | core.candidate_selector | INFO | ✅ 최종 선정된 후보 종목: X개
2025-11-24 15:33:XX | __main__ | INFO | ✅ 후보 종목 X개 데이터베이스 저장 완료
2025-11-24 15:33:XX | __main__ | INFO | ✅ ML 데이터 수집 완료: 가격 X/Y개, 재무 X/Y개
2025-11-24 15:30:XX | core.post_market_data_saver | INFO | 🏁 장 마감 후 데이터 저장 시작
2025-11-24 15:30:XX | core.post_market_data_saver | INFO | ✅ 분봉 데이터 캐시 저장 완료: X/Y개 종목 성공
2025-11-24 15:30:XX | core.post_market_data_saver | INFO | ✅ 일봉 데이터 저장 완료: X/Y개 종목 성공
```

### 오류 발생 시 확인할 메시지:
- `❌ 후보 종목 DB 저장 오류` - 저장 로직 문제
- `❌ [종목코드] 일별 가격 데이터 수집 오류` - API 호출 문제
- `⚠️ 저장할 종목이 없습니다` - 후보 종목이 선정되지 않음

## 문제 발생 시 대응 방법

### 1. 후보 종목이 저장되지 않는 경우
- 로그에서 `save_candidate_stocks` 호출 여부 확인
- `main.py`의 `_run_ml_data_collection` 함수 확인

### 2. ML 데이터 수집 오류 발생 시
- `core/ml_data_collector.py`의 `save_daily_price_data` 함수 확인
- API 파라미터가 올바른지 확인 (`itm_no`, `adj_prc` 등)

### 3. 장 마감 후 데이터 저장 실패 시
- `core/post_market_data_saver.py` 확인
- `intraday_manager`에 종목이 있는지 확인

## 빠른 확인 스크립트

월요일 장 마감 후 다음 명령어로 한 번에 확인:
```bash
# 1. 오늘 후보 종목 확인
python check_db_today.py

# 2. 오늘 데이터 수집 상태 확인
python check_today_data_collection.py

# 3. 최근 며칠간 요약 확인
python data_collection_summary.py --days 3
```

