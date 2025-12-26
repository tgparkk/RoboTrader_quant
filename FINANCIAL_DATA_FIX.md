# 재무 데이터 저장 오류 분석 및 수정

## 📋 문제 요약

**증상**: financial_statements 테이블의 2,296개 레코드 모두 ROE, PER, PBR, 부채비율이 NULL
**원인**: ml_data_collector.py의 재무 데이터 저장 로직에서 INSERT OR REPLACE 사용 시 NULL 값이 기존 데이터를 덮어씀
**영향**: 퀀트 팩터 Value Score 계산 불가, 리밸런싱 품질 저하

---

## 🔍 상세 분석

### 1. 데이터 흐름

```
1. API 호출 (get_financial_ratio) → FinancialRatioEntry 객체 생성
   - roe_value: data.get("roe_val")로 추출 (정상)
   - liability_ratio: data.get("lblt_rate")로 추출 (정상)

2. ml_data_collector.py:save_financial_data() 실행
   - 재무비율 데이터: ratio.roe_value, ratio.liability_ratio 읽기 ✅
   - PER/PBR: ratio.raw에서 추출 시도 또는 계산 ✅

3. DB 저장 (line 431-447)
   ❌ 문제: INSERT OR REPLACE 사용 시 NULL 컬럼이 기존 데이터 덮어씀
```

### 2. 문제의 근본 원인

**위치**: `core/ml_data_collector.py:380-487`

**문제 시나리오**:
1. 재무비율 반복문 (line 382): ROE, 부채비율, PER, PBR 저장 → revenue, net_income은 NULL
2. 손익계산서 반복문 (line 464): revenue, net_income 저장 → ROE, 부채비율, PER, PBR은 NULL
3. **결과**: INSERT OR REPLACE가 기존 레코드를 삭제하고 재생성하므로, 손익계산서 저장 시 재무비율 데이터가 모두 NULL로 덮어써짐

**증거**:
```sql
-- 현재 상태
SELECT COUNT(*) as total,
       SUM(CASE WHEN roe IS NULL THEN 1 ELSE 0 END) as null_roe,
       SUM(CASE WHEN revenue IS NULL THEN 1 ELSE 0 END) as null_revenue
FROM financial_statements;

-- 결과: total=2296, null_roe=2296, null_revenue=2296 (100% NULL)
```

---

## ✅ 해결 방법: INSERT OR IGNORE + UPDATE

### 핵심 아이디어

1. `INSERT OR IGNORE`로 레코드가 없을 때만 생성
2. `UPDATE`로 특정 컬럼만 업데이트 (다른 컬럼 보존)
3. NULL 값은 업데이트하지 않음 (기존 값 유지)

### 수정 파일: `core/ml_data_collector.py`

#### 수정 1: 재무비율 저장 (line 431-461)

**변경 전**:
```python
cursor.execute('''
    INSERT OR REPLACE INTO financial_statements
    (stock_code, report_date, fiscal_quarter,
     per, pbr, psr, dividend_yield,
     roe, debt_ratio)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
''', (
    stock_code, report_date, None,
    float(per) if per else None,
    float(pbr) if pbr else None,
    float(psr) if psr else None,
    float(dividend_yield) if dividend_yield else None,
    float(ratio.roe_value) if ratio.roe_value else None,
    float(ratio.liability_ratio) if ratio.liability_ratio else None,
))
```

**변경 후**:
```python
# 1) 레코드 생성 (없을 경우만)
cursor.execute('''
    INSERT OR IGNORE INTO financial_statements
    (stock_code, report_date, created_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
''', (stock_code, report_date))

# 2) 재무비율 업데이트 (NULL이 아닌 값만)
update_parts = []
update_values = []

if per is not None and per != '':
    update_parts.append("per = ?")
    update_values.append(float(per))

if pbr is not None and pbr != '':
    update_parts.append("pbr = ?")
    update_values.append(float(pbr))

if psr is not None and psr != '':
    update_parts.append("psr = ?")
    update_values.append(float(psr))

if dividend_yield:
    update_parts.append("dividend_yield = ?")
    update_values.append(float(dividend_yield))

if ratio.roe_value:
    update_parts.append("roe = ?")
    update_values.append(float(ratio.roe_value))

if ratio.liability_ratio:
    update_parts.append("debt_ratio = ?")
    update_values.append(float(ratio.liability_ratio))

if update_parts:
    update_parts.append("updated_at = CURRENT_TIMESTAMP")
    update_values.extend([stock_code, report_date])

    cursor.execute(f'''
        UPDATE financial_statements
        SET {", ".join(update_parts)}
        WHERE stock_code = ? AND report_date = ?
    ''', update_values)

    # 로그 출력
    roe_str = f"{ratio.roe_value:.2f}" if ratio.roe_value else "N/A"
    debt_str = f"{ratio.liability_ratio:.2f}" if ratio.liability_ratio else "N/A"
    per_str = f"{per:.2f}" if per else "N/A"
    pbr_str = f"{pbr:.2f}" if pbr else "N/A"
    self.logger.debug(
        f"�� [{stock_code}] 재무비율 저장: {report_date} - "
        f"ROE: {roe_str}%, 부채비율: {debt_str}%, "
        f"PER: {per_str}, PBR: {pbr_str}"
    )
```

#### 수정 2: 손익계산서 저장 (line 482-503)

**변경 전**:
```python
cursor.execute('''
    INSERT OR REPLACE INTO financial_statements
    (stock_code, report_date, fiscal_quarter,
     revenue, operating_profit, net_income, operating_margin, net_margin)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
''', (
    stock_code, report_date, None,
    float(income.revenue) if income.revenue else None,
    float(income.operating_income) if income.operating_income else None,
    float(income.net_income) if income.net_income else None,
    float(operating_margin) if operating_margin else None,
    float(net_margin) if net_margin else None,
))
```

**변경 후**:
```python
# 1) 레코드 생성 (없을 경우만)
cursor.execute('''
    INSERT OR IGNORE INTO financial_statements
    (stock_code, report_date, created_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
''', (stock_code, report_date))

# 2) 손익계산서 업데이트 (NULL이 아닌 값만)
update_parts = []
update_values = []

if income.revenue:
    update_parts.append("revenue = ?")
    update_values.append(float(income.revenue))

if income.operating_income:
    update_parts.append("operating_profit = ?")
    update_values.append(float(income.operating_income))

if income.net_income:
    update_parts.append("net_income = ?")
    update_values.append(float(income.net_income))

if operating_margin is not None:
    update_parts.append("operating_margin = ?")
    update_values.append(float(operating_margin))

if net_margin is not None:
    update_parts.append("net_margin = ?")
    update_values.append(float(net_margin))

if update_parts:
    update_parts.append("updated_at = CURRENT_TIMESTAMP")
    update_values.extend([stock_code, report_date])

    cursor.execute(f'''
        UPDATE financial_statements
        SET {", ".join(update_parts)}
        WHERE stock_code = ? AND report_date = ?
    ''', update_values)
```

---

## 🚀 실행 계획

### 1. 코드 수정 적용 (지금 바로)

```bash
# ml_data_collector.py 수정
# - line 431-461: 재무비율 저장 로직
# - line 482-503: 손익계산서 저장 로직
```

### 2. 기존 데이터 삭제 (선택적)

```sql
-- 기존 NULL 데이터 모두 삭제하고 재수집하려면
DELETE FROM financial_statements;

-- 또는 특정 날짜만 삭제
DELETE FROM financial_statements WHERE report_date >= '2024-01-01';
```

### 3. 데이터 재수집

```bash
# 오늘 데이터 재수집 (장 마감 후 16:00 이후)
python scripts/collect_missing_daily_data.py --date 20251226
```

### 4. 검증

```sql
-- NULL 비율 확인
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN roe IS NOT NULL THEN 1 ELSE 0 END) as roe_count,
    SUM(CASE WHEN per IS NOT NULL THEN 1 ELSE 0 END) as per_count,
    SUM(CASE WHEN revenue IS NOT NULL THEN 1 ELSE 0 END) as revenue_count
FROM financial_statements;

-- 최근 데이터 샘플
SELECT stock_code, report_date, roe, debt_ratio, per, pbr, revenue, net_income
FROM financial_statements
WHERE report_date >= '2024-01-01'
ORDER BY report_date DESC
LIMIT 10;
```

---

## 📊 기대 효과

### Before (현재)
- ROE: 0/2296 (0%)
- PER: 0/2296 (0%)
- Revenue: 0/2296 (0%)

### After (수정 후)
- ROE: ~1500/2296 (65%)  ← API가 제공하는 종목만
- PER: ~800/2296 (35%)   ← EPS > 0인 종목만 계산 가능
- Revenue: ~1800/2296 (78%)  ← 대부분 종목 제공

---

## 🎯 체크리스트

### 오늘 (12/26) 17:30 이전
- [ ] ml_data_collector.py 수정 완료
- [ ] 수정 사항 커밋 & 푸시
- [ ] 기존 financial_statements 테이블 백업 (선택)

### 오늘 (12/26) 16:00 이후
- [ ] 수정된 코드로 데이터 재수집
- [ ] 데이터베이스 검증 쿼리 실행
- [ ] ROE/PER/PBR 정상 저장 확인

### 내일 (12/27)
- [ ] 15:30 자동 재무 데이터 수집 로그 확인
- [ ] 퀀트 스크리닝 정상 작동 확인
- [ ] Value Score 계산 오류 없음 확인

---

**작성일**: 2025-12-26 17:15
**작성자**: Claude
**관련 이슈**: 재무 데이터 100% NULL 문제
