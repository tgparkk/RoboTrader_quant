# 포트폴리오 스냅샷 기능 가이드

## 📸 개요

장중 정기적으로 현재가를 조회하여 보유 종목의 평가손익을 DB에 저장하고, 언제든지 조회할 수 있는 기능입니다.

---

## 🎯 주요 기능

### 1. 자동 스냅샷 저장
- **실행 주기**: 30분마다 (장중에만)
- **저장 시각**: 09:00, 09:30, 10:00, 10:30, 11:00, 11:30, 13:00, 13:30, 14:00, 14:30, 15:00, 15:30
- **저장 내용**: 보유 종목별 현재가, 평가손익, 수익률

### 2. 언제든지 조회 가능
- 최근 스냅샷 즉시 확인
- 과거 특정 시각의 스냅샷 조회
- 시간대별 수익률 추이 분석

---

## 📊 DB 스키마

### `portfolio_snapshots` 테이블

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | INTEGER | Primary Key |
| snapshot_time | DATETIME | 스냅샷 시각 |
| stock_code | VARCHAR(10) | 종목코드 |
| stock_name | VARCHAR(100) | 종목명 |
| quantity | INTEGER | 보유 수량 |
| buy_price | REAL | 평균 매수가 |
| current_price | REAL | 현재가 |
| buy_value | REAL | 매수금액 |
| current_value | REAL | 평가금액 |
| unrealized_pl | REAL | 평가손익 (원) |
| unrealized_pl_rate | REAL | 수익률 (소수) |
| target_profit_rate | REAL | 목표 익절률 |
| stop_loss_rate | REAL | 손절률 |
| created_at | DATETIME | 생성 시각 |

**인덱스:**
- `idx_snapshot_time`: snapshot_time
- `idx_snapshot_stock`: (stock_code, snapshot_time)

---

## 💻 사용 방법

### 1. 수동으로 스냅샷 저장

```bash
python scripts/save_portfolio_snapshot.py
```

**출력 예시:**
```
📸 포트폴리오 스냅샷 저장 시작: 2025-12-30 10:30:00
📊 보유 종목 43개 현재가 조회 시작
✅ 스냅샷 저장 완료: 43개 성공, 0개 실패
💰 총 평가: 28,150,320원 (매수: 27,290,590원)
📊 평가손익: +859,730원 (+3.15%)
```

### 2. 최근 스냅샷 조회

```bash
python scripts/view_portfolio_snapshot.py
```

**출력 예시:**
```
================================================================================
📸 포트폴리오 스냅샷
================================================================================
스냅샷 시각: 2025-12-30 10:30:00
조회 시각: 2025-12-30 16:45:23
================================================================================

📦 보유 종목 (43개)
--------------------------------------------------------------------------------
종목코드    종목명                  수량     매수가        현재가        매수금액        평가금액        평가손익        수익률
--------------------------------------------------------------------------------
005380     현대차                     4    290,500      298,000     1,162,000     1,192,000      🟢+30,000      +2.6%
029460     케이씨                    55     25,500       26,300     1,402,500     1,446,500      🟢+44,000      +3.1%
...
--------------------------------------------------------------------------------
합계                                                              27,290,590    28,150,320      🟢+859,730      +3.2%

📊 수익 종목: 28개 | 손실 종목: 13개 | 보합: 2개
```

### 3. 특정 시각의 스냅샷 조회

```bash
python scripts/view_portfolio_snapshot.py "2025-12-30 09:30:00"
```

---

## 🔧 자동 실행 (main.py 통합)

프로그램 실행 중 자동으로 30분마다 스냅샷이 저장됩니다.

**main.py 로직:**
```python
# 30분마다 포트폴리오 스냅샷 저장 (장중에만)
if (current_time - last_portfolio_snapshot).total_seconds() >= 30 * 60:
    if is_market_open():
        logger.info(f"📸 포트폴리오 스냅샷 저장 ({current_time.strftime('%H:%M:%S')})")
        from scripts.save_portfolio_snapshot import save_portfolio_snapshot
        await asyncio.to_thread(save_portfolio_snapshot)
    last_portfolio_snapshot = current_time
```

---

## 📈 API 호출 최적화

### Rate Limit 관리
- 보유 종목당 0.2초 간격으로 API 호출
- 43개 종목 기준: 약 8.6초 소요
- 하루 총 API 호출: 43종목 × 13회 = 559회
- KIS API 제한(일 20,000회) 대비: 약 2.8% 사용

### 장중에만 실행
- `is_market_open()` 체크로 장 마감 후 호출 방지
- 불필요한 API 호출 최소화

---

## 🎯 활용 예시

### 1. 실시간 수익률 모니터링
```bash
# 10분마다 최신 스냅샷 확인
while true; do
    python scripts/view_portfolio_snapshot.py
    sleep 600
done
```

### 2. 일중 수익률 추이 분석
```sql
SELECT
    snapshot_time,
    SUM(current_value) as total_value,
    SUM(unrealized_pl) as total_pl,
    AVG(unrealized_pl_rate) * 100 as avg_pl_rate
FROM portfolio_snapshots
WHERE DATE(snapshot_time) = '2025-12-30'
GROUP BY snapshot_time
ORDER BY snapshot_time;
```

### 3. 종목별 수익률 히스토리
```sql
SELECT
    snapshot_time,
    stock_name,
    current_price,
    unrealized_pl_rate * 100 as pl_rate
FROM portfolio_snapshots
WHERE stock_code = '005380'
  AND DATE(snapshot_time) = '2025-12-30'
ORDER BY snapshot_time;
```

---

## ⚙️ 설정 변경

### 스냅샷 주기 변경

**main.py 551번 라인:**
```python
# 30분 → 10분으로 변경
if (current_time - last_portfolio_snapshot).total_seconds() >= 10 * 60:  # 10분
```

### 저장 종목 필터링

**save_portfolio_snapshot.py에 조건 추가:**
```python
# 예: 평가손익 ±5% 이상인 종목만 저장
if abs(unrealized_pl_rate) >= 0.05:
    snapshot_data.append(...)
```

---

## 🚨 주의사항

1. **API Rate Limit**
   - 주기를 너무 짧게 설정하면 API 제한 초과 가능
   - 권장: 10분 이상

2. **DB 용량**
   - 43개 종목 × 13회/일 × 250거래일 = 약 139,750 레코드/년
   - 디스크 사용량: 약 50MB/년

3. **장 마감 시간**
   - 15:30 이후는 스냅샷 저장 안 됨
   - 15:35 일일 리포트에서 종가 기준 평가손익 확인

---

## 📝 FAQ

### Q1. 스냅샷이 저장되지 않아요
```bash
# 로그 확인
grep "포트폴리오 스냅샷" logs/*.log

# 수동 실행으로 오류 확인
python scripts/save_portfolio_snapshot.py
```

### Q2. 특정 종목의 현재가가 0원으로 표시됩니다
- API 조회 실패 가능성
- 해당 종목은 스냅샷에 포함되지 않음
- 로그에서 "현재가 조회 실패" 확인

### Q3. 과거 스냅샷을 삭제하고 싶어요
```sql
-- 30일 이전 데이터 삭제
DELETE FROM portfolio_snapshots
WHERE snapshot_time < datetime('now', '-30 days');
```

---

## 🔗 관련 파일

- `scripts/save_portfolio_snapshot.py`: 스냅샷 저장
- `scripts/view_portfolio_snapshot.py`: 스냅샷 조회
- `main.py` (line 551-559): 자동 저장 로직
- `data/robotrader.db`: SQLite 데이터베이스

---

## 📊 통계 쿼리 예시

### 오늘 최대 수익률
```sql
SELECT
    snapshot_time,
    SUM(unrealized_pl) as total_pl,
    SUM(unrealized_pl_rate * buy_value) / SUM(buy_value) * 100 as weighted_pl_rate
FROM portfolio_snapshots
WHERE DATE(snapshot_time) = DATE('now')
GROUP BY snapshot_time
ORDER BY total_pl DESC
LIMIT 1;
```

### 종목별 평균 수익률 (오늘)
```sql
SELECT
    stock_name,
    AVG(unrealized_pl_rate) * 100 as avg_pl_rate,
    MIN(unrealized_pl_rate) * 100 as min_pl_rate,
    MAX(unrealized_pl_rate) * 100 as max_pl_rate
FROM portfolio_snapshots
WHERE DATE(snapshot_time) = DATE('now')
GROUP BY stock_code, stock_name
ORDER BY avg_pl_rate DESC;
```
