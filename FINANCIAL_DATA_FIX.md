# 재무 데이터 저장 오류 수정

## 문제 상황
- `financial_statements` 테이블에 2,296건 존재
- **모든 재무지표(PER, PBR, ROE 등)가 NULL**

## 원인 분석

### 1. API 구조 불일치
`FinancialRatioEntry` (kis_financial_api.py)에는 다음 필드만 존재:
- ✓ ROE (roe_value)
- ✓ EPS, BPS, SPS  
- ✓ 부채비율 (liability_ratio)
- ✗ **PER, PBR, PSR 없음**

### 2. 잘못된 파싱 로직
기존 코드 (ml_data_collector.py:391-393):
```python
per = ratio.raw.get('per') if ratio.raw else None
pbr = ratio.raw.get('pbr') if ratio.raw else None
```
→ ratio.raw에도 해당 필드 없음

## 해결 방법

### 1. 다양한 필드명 시도
```python
if ratio.raw and isinstance(ratio.raw, dict):
    per = ratio.raw.get('per') or ratio.raw.get('PER') or ratio.raw.get('stock_per')
    pbr = ratio.raw.get('pbr') or ratio.raw.get('PBR') or ratio.raw.get('stock_pbr')
```

### 2. PER/PBR 자체 계산 추가
```python
# PER = 주가 / EPS
if not per and ratio.eps and ratio.eps > 0:
    market_info = get_stock_market_cap(stock_code)
    if market_info:
        current_price = float(market_info['current_price'])
        per = current_price / ratio.eps

# PBR = 주가 / BPS  
if not pbr and ratio.bps and ratio.bps > 0:
    market_info = get_stock_market_cap(stock_code)
    if market_info:
        current_price = float(market_info['current_price'])
        pbr = current_price / ratio.bps
```

### 3. 저장 가능한 데이터 우선 저장
- ROE: ✓ FinancialRatioEntry.roe_value에서 가져옴
- 부채비율: ✓ FinancialRatioEntry.liability_ratio에서 가져옴
- EPS, BPS: ✓ 있음 (DB에는 저장 안 하지만 PER/PBR 계산에 사용)
- PER, PBR: 계산하여 저장 시도

## 수정 사항

### 파일: core/ml_data_collector.py

**변경 전 (390-416줄):**
- ratio.raw에서 직접 추출 시도
- 실패 시 None 저장

**변경 후:**
1. raw 데이터에서 다양한 필드명으로 시도
2. 없으면 EPS/BPS와 현재가로 계산
3. 저장 가능한 데이터 우선 저장
4. 상세 로깅 추가

## 기대 효과

### 즉시 개선
- ✓ ROE, 부채비율 정상 저장 (기존 API 필드 활용)
- ✓ 오류 없이 저장 완료

### 추가 개선 (PER/PBR 계산 시)
- ✓ 현재가 기준 PER/PBR 계산
- ✓ 퀀트 팩터의 Value Score 계산 가능
- ✓ 리밸런싱 품질 향상

## 재수집 필요

### 방법 1: 자동 재수집 (추천)
```bash
# 다음 장 종료 후 자동 수집됨
# 보유 종목 + 포트폴리오 30개만 재수집
```

### 방법 2: 수동 재수집
```python
from core.ml_data_collector import MLDataCollector

collector = MLDataCollector()

# 보유 + 포트폴리오 종목 재수집
stock_codes = ["005930", "000660", ...]  # 대상 종목
for code in stock_codes:
    collector.save_financial_data(code)
```

## 검증 방법

### 재수집 후 확인
```sql
SELECT 
    stock_code,
    report_date,
    per, pbr, roe, debt_ratio
FROM financial_statements  
WHERE report_date >= '2024-01-01'
ORDER BY report_date DESC
LIMIT 10;
```

### 기대 결과
- ROE, debt_ratio: 값 있음 (필수)
- PER, PBR: 값 있음 (계산 성공 시) 또는 NULL (계산 실패 시)
- 모두 NULL이 아니어야 함

## 추가 개선 사항 (향후)

1. **PER/PBR API 찾기**
   - KIS API에서 PER/PBR을 직접 제공하는 API 확인
   - 있다면 계산 대신 API 사용

2. **과거 데이터 보정**
   - 과거 분기 데이터는 현재가로 계산 불가
   - 당시 주가 데이터가 있다면 재계산 가능

3. **배당수익률 추가**
   - dividend_yield 필드 활용 검토

---

수정일: 2025-12-25
수정자: Claude Code
