# 불필요한 파일 목록

## 📋 검토 일자: 2025-12-11

---

## 🗑️ 제거 권장 파일

### 1. 중복 문서 파일
- ✅ `월요일_테스트_체크리스트.md` (루트)
  - `docs/monday_test_checklist.md`와 중복
  - 루트의 파일 제거 권장

### 2. 테스트 파일 (루트에 있는 것들)
- ✅ `test_market_hours.py` (루트)
  - tests 폴더에 있지 않고 루트에 있음
  - 사용 여부 확인 필요
  
- ✅ `test_virtual_trading_db.py` (루트)
  - tests 폴더에 있지 않고 루트에 있음
  - 사용 여부 확인 필요

- ✅ `test_daily_chart_data.pkl`
  - 테스트용 데이터 파일
  - 코드에서 import되지 않음
  - 제거 권장

### 3. 오래된 분석 결과 파일들

#### 3.1 분석 결과 이미지 (2025년 9월)
- ✅ `comprehensive_analysis_results/comprehensive_features_20250919_210435.png`
- ✅ `comprehensive_analysis_results/trading_rules_20250919_210435.py`
- ✅ `consecutive_analysis_results/consecutive_analysis_20250919_220028.png`
  - 3개월 이상 된 분석 결과
  - 제거 권장

#### 3.2 오래된 차트 파일 (2025년 8월)
- ✅ `charts/1min_103840_20250803_final.png`
- ✅ `charts/1min_bollinger_bands_103840_20250803_213921.png`
- ✅ `charts/1min_price_box_103840_20250803_213920.png`
- ✅ `charts/3min_103840_20250803_final.png`
- ✅ `charts/3min_bollinger_bands_103840_20250803_213923.png`
- ✅ `charts/3min_price_box_103840_20250803_213922.png`
- ✅ `charts/accurate_1min_103840_20250801.png`
- ✅ `charts/accurate_3min_103840_20250801.png`
- ✅ `charts/real_1min_103840_20250801.png`
- ✅ `charts/real_3min_103840_20250801.png`
  - 4개월 이상 된 차트 파일
  - 제거 권장

### 4. JSON 분석 결과 파일 (사용 여부 확인 필요)

#### 4.1 사용 중인 파일
- ⚠️ `daily_pattern_analysis.json`
  - `trade_analysis/daily_pattern_filter.py`에서 사용 중
  - 유지 필요

#### 4.2 사용 여부 불명확한 파일
- ⚠️ `comprehensive_pattern_analysis.json` (137 bytes)
  - 매우 작은 파일, 내용 확인 필요
  
- ⚠️ `win_loss_pattern_analysis.json` (1,685 bytes)
  - 사용 여부 확인 필요
  
- ⚠️ `enhanced_analysis_with_auto_collection.json` (46,883 bytes)
  - 사용 여부 확인 필요
  
- ⚠️ `signal_replay_comparison.json` (268,935 bytes)
  - 큰 파일, 사용 여부 확인 필요

#### 4.3 유지 필요 파일
- ✅ `stock_list.json` (93,903 bytes)
  - 종목 리스트로 사용 가능성 높음
  - 유지 권장

- ✅ `token_info.json`
  - API 토큰 정보
  - .gitignore에 포함되어 있음
  - 유지 필요

### 5. 기타 파일

#### 5.1 패치 파일
- ⚠️ `patches/fix_realtime_data_filtering.py`
  - 일회성 패치 파일인지 확인 필요
  - 적용 완료되었다면 제거 가능

#### 5.2 스크립트 파일
- ⚠️ `fix_commit_msg.ps1`
  - 일회성 스크립트인지 확인 필요

---

## 📊 제거 권장 파일 요약

### 즉시 제거 가능
1. `월요일_테스트_체크리스트.md` (중복)
2. `test_daily_chart_data.pkl` (미사용)
3. `comprehensive_analysis_results/` 폴더 전체 (3개월 이상)
4. `consecutive_analysis_results/` 폴더 전체 (3개월 이상)
5. `charts/` 폴더의 모든 파일 (4개월 이상)

### 확인 후 제거
1. `test_market_hours.py` (루트)
2. `test_virtual_trading_db.py` (루트)
3. `comprehensive_pattern_analysis.json`
4. `win_loss_pattern_analysis.json`
5. `enhanced_analysis_with_auto_collection.json`
6. `signal_replay_comparison.json`
7. `patches/fix_realtime_data_filtering.py`
8. `fix_commit_msg.ps1`

---

## 💾 예상 절약 공간

- 차트 파일: 약 10개 × 평균 500KB = 약 5MB
- 분석 결과 이미지: 약 3개 × 평균 1MB = 약 3MB
- JSON 파일 (확인 후): 약 300KB
- **총 예상 절약: 약 8-10MB**

