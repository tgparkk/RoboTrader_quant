# 대차대조표 데이터 수집 오류 수정

## 문제 발견

2025-12-27 대차대조표 데이터를 처음 수집했을 때, 다음 필드들이 NULL로 저장되는 문제가 발견되었습니다:
- `current_assets` (유동자산)
- `non_current_assets` (비유동자산)

**영향**: 유동비율(Current Ratio) 계산 불가 → Quality Factor 점수 계산 오류

## 근본 원인

KIS API 응답 필드명이 예상과 다름:

### 잘못된 매핑 (이전):
```python
current_assets=to_float(data.get("flow_aset"))        # ❌ 잘못된 필드명
non_current_assets=to_float(data.get("fix_aset"))     # ❌ 잘못된 필드명
```

### 실제 API 응답 구조:
```json
{
  "stac_yymm": "202509",
  "cras": "1655.00",           // ✅ 유동자산 (current assets)
  "fxas": "10610.00",          // ✅ 비유동자산 (fixed assets)
  "total_aset": "12265.00",    // ✅ 총자산
  "flow_lblt": "2669.00",      // ✅ 유동부채 (current liabilities)
  "fix_lblt": "1754.00",       // ✅ 비유동부채 (fixed liabilities)
  "total_lblt": "4424.00",     // ✅ 총부채
  "cpfn": "137",               // ✅ 자본금 (capital stock)
  "prfi_surp": "99.99",        // ✅ 이익잉여금 (profit surplus)
  "total_cptl": "7841.00"      // ✅ 총자본
}
```

## 해결 방법

### 1. API 응답 구조 분석

디버그 스크립트 작성 (`debug_balance_sheet_api.py`):
```python
balance = balance_sheets[0]
print(json.dumps(balance.raw, indent=2, ensure_ascii=False))
```

실행 결과로 정확한 필드명 확인:
- `cras` → 유동자산
- `fxas` → 비유동자산
- `cpfn` → 자본금
- `prfi_surp` → 이익잉여금

### 2. 필드 매핑 수정

파일: `api/kis_financial_api.py` (line 267-280)

```python
return BalanceSheetEntry(
    statement_ym=str(data.get("stac_yymm", "")).strip(),
    total_assets=to_float(data.get("total_aset")),
    current_assets=to_float(data.get("cras")),              # 수정: flow_aset → cras
    non_current_assets=to_float(data.get("fxas")),          # 수정: fix_aset → fxas
    total_liabilities=to_float(data.get("total_lblt")),
    current_liabilities=to_float(data.get("flow_lblt")),
    non_current_liabilities=to_float(data.get("fix_lblt")),
    total_equity=to_float(data.get("total_cptl")),
    capital_stock=to_float(data.get("cpfn")),               # 수정: cptl_stck → cpfn
    retained_earnings=to_float(data.get("prfi_surp")),      # 수정: retained_earnings → prfi_surp
    created_at=now_kst(),
    raw=data
)
```

### 3. 데이터 재수집

```bash
python collect_balance_sheet.py
```

결과:
- 49개 보유 종목
- 49개 성공 (100%)
- 0개 실패

## 검증 결과

### 수정 전 (2025-12-27 01:00 - 첫 수집):
```sql
SELECT stock_code, current_assets, current_liabilities
FROM financial_statements
WHERE stock_code = '000050'
ORDER BY report_date DESC LIMIT 1;

-- 결과: current_assets = NULL (❌)
```

### 수정 후 (2025-12-27 01:26 - 재수집):
```sql
SELECT stock_code, report_date, current_assets, current_liabilities,
       ROUND((current_assets * 100.0 / current_liabilities), 1) as current_ratio
FROM financial_statements
WHERE stock_code = '000050'
ORDER BY report_date DESC LIMIT 1;

-- 결과:
-- stock_code | report_date | current_assets | current_liabilities | current_ratio
-- 000050     | 2025-09-01  | 1655.0         | 2669.0              | 62.0
```

### 유동비율 계산 성공 사례:

| 종목코드 | 기준일 | 유동자산 | 유동부채 | 유동비율 | 등급 |
|---------|--------|---------|---------|---------|------|
| 281820  | 2025-09-01 | 4,486 | 567 | 791.2% | S등급 |
| 035510  | 2025-09-01 | 1,941 | 836 | 232.2% | A등급 |
| 012330  | 2025-09-01 | 302,171 | 137,290 | 220.1% | A등급 |
| 006650  | 2025-09-01 | 8,159 | 4,481 | 182.1% | A등급 |
| 105840  | 2025-09-01 | 1,266 | 268 | 472.4% | S등급 |
| 234080  | 2025-09-01 | 997 | 825 | 120.8% | B등급 |
| 072710  | 2025-09-01 | 4,390 | 4,284 | 102.5% | B등급 |
| 002380  | 2025-09-01 | 40,189 | 40,852 | 98.4% | C등급 |
| 000050  | 2025-09-01 | 1,655 | 2,669 | 62.0% | D등급 |

**유동비율 기준**:
- S등급 (400% 이상): 매우 우수한 유동성
- A등급 (200-400%): 우수한 유동성
- B등급 (100-200%): 양호한 유동성
- C등급 (80-100%): 보통
- D등급 (80% 미만): 주의 필요

## 기대 효과

### 1. Quality Factor 정확도 향상

**수정 전** (유동비율 근사값 사용):
```python
current_ratio = 100 - debt_ratio  # ❌ 부정확한 근사값
```

**수정 후** (실제 유동비율 계산):
```python
current_ratio = (current_assets / current_liabilities) * 100  # ✅ 정확한 계산
```

### 2. 리밸런싱 품질 개선

- 정확한 유동비율로 Quality Score 계산
- 재무 안정성이 높은 종목 선별 가능
- 유동성 위험이 큰 종목 조기 감지

### 3. ROA 계산 정확도 향상

**수정 전** (근사값):
```python
roa = roe * 0.6  # ❌ 부정확한 근사값
```

**수정 후** (실제 계산):
```python
roa = (net_income / total_assets) * 100  # ✅ 정확한 계산
```

## 참고 사항

### KIS API 대차대조표 필드명 정리

| 한글명 | 영문명 | API 필드명 | 비고 |
|-------|--------|-----------|------|
| 결산년월 | Statement Year-Month | `stac_yymm` | YYYYMM 형식 |
| 유동자산 | Current Assets | `cras` | NOT flow_aset |
| 비유동자산 | Fixed Assets | `fxas` | NOT fix_aset |
| 자산총계 | Total Assets | `total_aset` | ✅ |
| 유동부채 | Current Liabilities | `flow_lblt` | ✅ |
| 비유동부채 | Fixed Liabilities | `fix_lblt` | ✅ |
| 부채총계 | Total Liabilities | `total_lblt` | ✅ |
| 자본금 | Capital Stock | `cpfn` | NOT cptl_stck |
| 이익잉여금 | Profit Surplus | `prfi_surp` | NOT retained_earnings |
| 자본총계 | Total Equity | `total_cptl` | ✅ |

### 향후 주의사항

1. **새로운 재무 API 추가 시**: 반드시 디버그 스크립트로 실제 응답 구조 확인
2. **필드명 가정 금지**: KIS API 문서와 실제 응답이 다를 수 있음
3. **데이터 검증 필수**: 수집 후 반드시 NULL 값 체크

## 관련 파일

- `api/kis_financial_api.py`: 필드 매핑 수정
- `collect_balance_sheet.py`: 재수집 스크립트
- `debug_balance_sheet_api.py`: API 응답 분석 스크립트
- `core/quant/quant_screening_service.py`: Quality Factor 계산 로직

## 수정 일시

- 문제 발견: 2025-12-27 01:00 (첫 수집)
- 원인 분석: 2025-12-27 01:25 (디버그 스크립트 실행)
- 수정 완료: 2025-12-27 01:26 (필드 매핑 수정)
- 재수집 완료: 2025-12-27 01:26 (49개 종목 100% 성공)
