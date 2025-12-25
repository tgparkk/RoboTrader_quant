# 데이터 저장 문제 진단 보고서
날짜: 2025-12-25

## 발견된 심각한 문제

### ❌ 재무 데이터 수집 오류 (긴급)

**문제 상황:**
- `financial_statements` 테이블에 2,296건의 레코드가 있으나
- **모든 재무지표가 NULL로 저장됨**
- PER, PBR, ROE, 부채비율 등 모든 값이 None

**샘플 데이터 (2025-09-01):**
```
stock_code  report_date   per   pbr   roe   debt_ratio
000050      2025-09-01   None  None  None  None
000120      2025-09-01   None  None  None  None
```

**영향:**
- 퀀트 팩터 중 Value Score 계산 불가능
- 팩터 점수의 정확도 저하
- 리밸런싱 품질 저하

**원인 분석:**
파일: core/ml_data_collector.py:390-416

```python
# 문제 코드
per = ratio.raw.get('per') if ratio.raw else None
pbr = ratio.raw.get('pbr') if ratio.raw else None
```

원인:
1. ratio.raw 객체 구조가 예상과 다름
2. API 응답 필드명이 변경되었을 가능성
3. 데이터 타입 불일치

---

## 발견된 경미한 문제

### ⚠️ 일봉 데이터 저장 종목 수 변동

**현상:**
- 12월 초: 106개 종목
- 12월 24일: 52개 종목 (50% 감소)

**원인:**
- 의도된 동작: 보유 종목 + 포트폴리오 30개만 저장
- 매도로 보유 종목 감소 → 저장 대상 자동 감소

**평가:** 정상 동작 (문제 없음)

---

## 정상 동작 확인

### ✓ 손익률 계산 수정 완료
- profit_rate 저장 형식 통일 (소수 형태)
- 향후 매도부터 정확하게 저장됨

### ✓ 퀀트 팩터 계산
- 353개 종목, 매일 정상 계산
- 포트폴리오 30개 정상 선정

### ✓ 일봉 데이터 저장
- INSERT OR REPLACE로 중복 방지
- 보유 + 포트폴리오 종목만 저장 (설계 의도)

---

## 권장 조치사항

### 우선순위 1: 재무 데이터 파싱 수정 ⚡
1. **API 응답 구조 확인**
   - get_financial_ratio() 실제 응답 로깅
   - ratio.raw 객체 내부 구조 확인
   - API 문서와 실제 응답 비교

2. **필드 매핑 수정**
   ```python
   # 수정 예시
   # 기존
   per = ratio.raw.get('per') if ratio.raw else None
   
   # 수정안 (실제 필드명 확인 후)
   per = getattr(ratio, 'per', None)
   # 또는
   per = ratio.raw['actual_field_name'] if ratio.raw else None
   ```

3. **재수집 및 검증**
   - 샘플 종목 5개로 테스트
   - 저장 결과 DB에서 확인
   - 전체 종목 재수집

### 우선순위 2: 일봉 저장 전략 검토
**현재 전략:** 보유 + 포트폴리오만 저장
**평가:** 유지 권장 (문제 없음)

**대안 고려 (선택사항):**
- 퀀트 후보 50개 추가 저장?
- 팩터 계산 대상 전체 저장? (부하 증가)

### 우선순위 3: 데이터 품질 모니터링
```python
# 일일 체크 스크립트
python check_data_storage.py
```

**모니터링 항목:**
- 재무지표 NULL 비율
- 일봉 저장 종목 수
- 팩터 점수 계산 완료 여부

---

## 테스트 방법

### 재무 데이터 파싱 테스트
```python
from api.kis_financial_api import get_financial_ratio

# 샘플 종목으로 테스트
stock_code = "005930"  # 삼성전자
ratios = get_financial_ratio(stock_code, div_cls="0")

if ratios:
    for ratio in ratios[:1]:  # 첫 번째 데이터만
        print(f"ratio object: {ratio}")
        print(f"ratio.raw: {ratio.raw}")
        print(f"ratio attributes: {dir(ratio)}")
        # 실제 필드명 확인
```

---

## 생성 정보
- 생성일: 2025-12-25
- 스크립트: check_data_storage.py
- 데이터베이스: data/robotrader.db
