# 전작(RoboTrader) 흔적 제거 계획

## ✅ 1단계: 코드에서 사용하지 않는 변수 제거 (완료)

**파일**: `core/trading_decision_engine.py`

제거한 변수들:
```python
self.daily_pattern_filter = None      # 전작의 일봉 패턴 필터
self.use_daily_filter = False
self.simple_pattern_filter = None     # 전작의 단순 패턴 필터  
self.use_simple_filter = False
self.use_ml_filter = False            # 전작의 ML 필터
self.use_hardcoded_ml = False
self.ml_settings = None
self.ml_predictor = None
self.hardcoded_ml_predictor = None
self.pattern_logger = None            # 전작의 패턴 로거
```

---

## 🔍 2단계: 사용하지 않는 Indicator 파일 확인

### 현재 사용 중인 파일 (유지 필요):
1. ✅ `pullback_candle_pattern.py` - trading_decision_engine에서 사용
2. ✅ `price_box.py` - visualization, intraday_stock_manager에서 사용
3. ✅ `bisector_line.py` - visualization, pullback 모듈에서 사용
4. ✅ `bollinger_bands.py` - visualization에서 사용
5. ✅ `multi_bollinger_bands.py` - visualization에서 사용
6. ✅ `pullback/` 폴더 전체 - pullback_candle_pattern에서 사용
7. ✅ `pattern_combination_filter.py` - pullback_candle_pattern에서 사용
8. ✅ `filter_stats.py` - pullback_candle_pattern에서 사용
9. ✅ `time_weighted_filter.py` - pullback_candle_pattern에서 사용
10. ✅ `pullback_utils.py` - pullback_candle_pattern에서 사용

### 사용하지 않는 파일 (제거 가능):
1. ❌ `close_position_filter.py` - 코드에서 import 없음
2. ❌ `consolidation_breakout.py` - 코드에서 import 없음
3. ❌ `volume_bollinger_bands.py` - 코드에서 import 없음
4. ❌ `simple_pattern_filter.py` - 코드에서 import 없음
5. ❌ `pullback_pattern_validator.py` - 코드에서 import 없음

---

## 📁 3단계: 오래된 분석 결과 파일 제거

### 즉시 제거 가능:
1. ❌ `comprehensive_analysis_results/` (2025-09-19) - 3개월 이상
2. ❌ `consecutive_analysis_results/` (2025-09-19) - 3개월 이상
3. ❌ `charts/` 폴더의 2025-08-03 이전 파일들 - 4개월 이상

### 중복 파일:
4. ❌ `월요일_테스트_체크리스트.md` (루트) - docs/에 동일 파일 있음

### 테스트 파일 (확인 필요):
5. ⚠️ `test_market_hours.py` (루트)
6. ⚠️ `test_virtual_trading_db.py` (루트)
7. ⚠️ `test_daily_chart_data.pkl`

### JSON 분석 파일 (확인 필요):
8. ⚠️ `comprehensive_pattern_analysis.json` (137 bytes)
9. ⚠️ `win_loss_pattern_analysis.json` (1,685 bytes)
10. ⚠️ `enhanced_analysis_with_auto_collection.json` (46,883 bytes)
11. ⚠️ `signal_replay_comparison.json` (268,935 bytes)

---

## 🎯 제거 우선순위

### High (즉시 제거):
1. 코드에서 사용하지 않는 indicator 파일 5개
2. 오래된 분석 결과 폴더 2개
3. 오래된 차트 파일들
4. 중복 문서 파일

### Medium (확인 후 제거):
1. 루트의 테스트 파일들
2. 큰 JSON 분석 파일들

### Low (보류):
1. patches/ 폴더 (일회성 패치)
2. fix_commit_msg.ps1 (일회성 스크립트)

---

## 📊 예상 효과

- 코드 간소화: 불필요한 변수 10개 제거
- 파일 정리: 약 15~20개 파일 제거
- 디스크 공간: 약 10MB 절약
- 유지보수성: 전작 의존성 제거로 코드 명확성 향상

