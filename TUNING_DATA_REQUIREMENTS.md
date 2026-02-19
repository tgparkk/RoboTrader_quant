# 백테스팅 튜닝을 위한 데이터 수집 체크리스트

## 📊 수집 기간: 2025-12-16 ~ 현재 (목표: 2개월)

---

## ✅ 필수 데이터 (현재 수집 중)

### 1. 매수 시점 데이터 (BUY)
| 항목 | 필드명 | 수집 여부 | 용도 |
|------|--------|-----------|------|
| 종목코드 | stock_code | ✅ | 종목 식별 |
| 종목명 | stock_name | ✅ | 가독성 |
| 매수가 | price | ✅ | 손익 계산 |
| 매수 수량 | quantity | ✅ | 손익 계산 |
| 매수 시각 | timestamp | ✅ | 보유 기간 계산 |
| 목표 익절률 | target_profit_rate | ✅ | 목표율 최적화 |
| 손절률 | stop_loss_rate | ✅ | 손절률 최적화 |
| 전략명 | strategy | ✅ | 전략별 분석 |
| 매수 사유 | reason | ✅ | 패턴 분석 |

**수집 상태**: ✅ **완벽** (모든 필드 수집 중)

---

### 2. 매도 시점 데이터 (SELL)
| 항목 | 필드명 | 수집 여부 | 용도 |
|------|--------|-----------|------|
| 종목코드 | stock_code | ✅ | 종목 식별 |
| 매도가 | price | ✅ | 손익 계산 |
| 매도 수량 | quantity | ✅ | 손익 계산 |
| 매도 시각 | timestamp | ✅ | 보유 기간 계산 |
| 손익 금액 | profit_loss | ✅ | 수익성 분석 |
| 손익률 | profit_rate | ✅ | 승률 계산 |
| 매수 기록 ID | buy_record_id | ✅ | 매수-매도 연결 |
| 매도 사유 | reason | ✅ | 청산 패턴 분석 |

**수집 상태**: ✅ **완벽** (모든 필드 수집 중)

---

### 3. 퀀트 점수 데이터 (매수 시점)
| 항목 | 필드명 | 수집 여부 | 용도 |
|------|--------|-----------|------|
| Value 점수 | value_score | ✅ | 팩터별 성과 분석 |
| Quality 점수 | quality_score | ✅ | 팩터별 성과 분석 |
| Momentum 점수 | momentum_score | ✅ | 팩터별 성과 분석 |
| Growth 점수 | growth_score | ✅ | 팩터별 성과 분석 |
| 종합 점수 | total_score | ✅ | 점수 구간별 성과 |
| 포트폴리오 순위 | rank | ✅ | 순위별 성과 분석 |

**수집 상태**: ✅ **완벽** (quant_factors 테이블에 저장 중)

**연결 가능**: ✅ (매수 시점과 점수 데이터 JOIN 가능)

---

## 📈 현재 수집 현황

### 통계
- **총 매매 기록**: 72건 (Buy: 46, Sell: 26)
- **완결된 매매**: 20건 (승: 3, 패: 17)
- **보유 중**: 26건
- **데이터 품질**: ✅ 100% (필수 필드 누락 0%)

### 기간
- **시작**: 2025-12-16
- **최신**: 2026-01-05
- **경과**: 21일 (3주)
- **목표**: 60일 (2개월)
- **진행률**: 35%

---

## ⚠️ 추가 수집 권장 데이터

### 4. 시장 환경 데이터 (추가 필요)
| 항목 | 필드명 | 수집 여부 | 용도 |
|------|--------|-----------|------|
| KOSPI 지수 | market_index | ❌ | 시장 상황별 성과 |
| KOSPI 등락률 | market_return | ❌ | 시장 상승/하락장 분석 |
| 업종 | sector | ❌ | 섹터별 성과 분석 |
| 시가총액 | market_cap | ⚠️ | 대/중/소형주 분석 |
| 거래량 | volume | ⚠️ | 유동성 분석 |

**수집 상태**: ❌ **미수집** (하지만 daily_prices 테이블에서 추출 가능)

---

### 5. 기술적 지표 (선택 사항)
| 항목 | 수집 여부 | 용도 |
|------|-----------|------|
| RSI | ❌ | 과매수/과매도 분석 |
| 이동평균선 | ❌ | 추세 분석 |
| 볼린저밴드 | ❌ | 변동성 분석 |

**수집 상태**: ❌ **미수집** (당장 필요하지 않음)

---

## 🎯 튜닝 가능한 항목

현재 수집 중인 데이터로 튜닝 가능한 항목들:

### 1. 손익절 비율 최적화 ⭐⭐⭐
```sql
-- 목표율별 성과 분석
SELECT
  target_profit_rate,
  stop_loss_rate,
  COUNT(*) as trades,
  AVG(profit_rate) as avg_return,
  SUM(CASE WHEN profit_rate > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM virtual_trading_records b
JOIN virtual_trading_records s ON s.buy_record_id = b.id
WHERE b.action = 'BUY' AND s.action = 'SELL'
GROUP BY target_profit_rate, stop_loss_rate;
```

### 2. 점수 구간별 목표율 차등화 ⭐⭐⭐
```sql
-- 점수 구간별 승률
SELECT
  CASE
    WHEN f.total_score >= 70 THEN 'S (70+)'
    WHEN f.total_score >= 60 THEN 'A (60-70)'
    WHEN f.total_score >= 50 THEN 'B (50-60)'
    ELSE 'C (<50)'
  END as grade,
  COUNT(*) as trades,
  AVG(s.profit_rate) as avg_return,
  SUM(CASE WHEN s.profit_rate > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM virtual_trading_records b
JOIN virtual_trading_records s ON s.buy_record_id = b.id
JOIN quant_factors f ON b.stock_code = f.stock_code
  AND DATE(b.timestamp) = f.calc_date
WHERE b.action = 'BUY' AND s.action = 'SELL'
GROUP BY grade;
```

### 3. 보유 기간 최적화 ⭐⭐
```sql
-- 보유 기간별 수익률
SELECT
  CAST(JULIANDAY(s.timestamp) - JULIANDAY(b.timestamp) AS INTEGER) as hold_days,
  COUNT(*) as trades,
  AVG(s.profit_rate) as avg_return,
  SUM(CASE WHEN s.profit_rate > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM virtual_trading_records b
JOIN virtual_trading_records s ON s.buy_record_id = b.id
WHERE b.action = 'BUY' AND s.action = 'SELL'
GROUP BY hold_days
HAVING COUNT(*) >= 2;
```

### 4. 팩터별 성과 분석 ⭐⭐
```sql
-- Value vs Momentum vs Quality vs Growth
SELECT
  CASE
    WHEN f.value_score = (SELECT MAX(x) FROM (SELECT value_score as x, quality_score, momentum_score, growth_score FROM quant_factors WHERE stock_code = f.stock_code AND calc_date = f.calc_date)) THEN 'Value'
    WHEN f.quality_score = (SELECT MAX(x) FROM (SELECT value_score, quality_score as x, momentum_score, growth_score FROM quant_factors WHERE stock_code = f.stock_code AND calc_date = f.calc_date)) THEN 'Quality'
    WHEN f.momentum_score = (SELECT MAX(x) FROM (SELECT value_score, quality_score, momentum_score as x, growth_score FROM quant_factors WHERE stock_code = f.stock_code AND calc_date = f.calc_date)) THEN 'Momentum'
    ELSE 'Growth'
  END as dominant_factor,
  COUNT(*) as trades,
  AVG(s.profit_rate) as avg_return,
  SUM(CASE WHEN s.profit_rate > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM virtual_trading_records b
JOIN virtual_trading_records s ON s.buy_record_id = b.id
JOIN quant_factors f ON b.stock_code = f.stock_code
  AND DATE(b.timestamp) = f.calc_date
WHERE b.action = 'BUY' AND s.action = 'SELL'
GROUP BY dominant_factor;
```

### 5. 청산 사유별 분석 ⭐⭐⭐
```sql
-- 익절/손절/리밸런싱별 성과
SELECT
  CASE
    WHEN reason LIKE '%Target%' OR reason LIKE '%익절%' THEN 'Target Profit'
    WHEN reason LIKE '%Stop%' OR reason LIKE '%손절%' THEN 'Stop Loss'
    ELSE 'Rebalancing'
  END as exit_type,
  COUNT(*) as trades,
  AVG(profit_rate) as avg_return,
  SUM(CASE WHEN profit_rate > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM virtual_trading_records
WHERE action = 'SELL' AND is_test = 1
GROUP BY exit_type;
```

---

## 📊 수집 목표

### 최소 목표 (튜닝 가능)
- ✅ **50건의 완결된 매매** (현재 20건, 60% 남음)
- ⏳ 다양한 점수 구간 (S/A/B 등급)
- ⏳ 다양한 청산 사유 (익절/손절/리밸런싱)

### 권장 목표 (신뢰도 향상)
- ⏳ **100건의 완결된 매매**
- ⏳ 상승장/하락장/횡보장 모두 경험
- ⏳ 각 목표율별 최소 10건 이상

---

## 🔧 데이터 품질 점검 쿼리

### 1. 필수 필드 누락 확인
```sql
SELECT
  'BUY' as action,
  COUNT(*) as total,
  SUM(CASE WHEN target_profit_rate IS NULL THEN 1 ELSE 0 END) as missing_target,
  SUM(CASE WHEN stop_loss_rate IS NULL THEN 1 ELSE 0 END) as missing_stop
FROM virtual_trading_records
WHERE action = 'BUY' AND is_test = 1
UNION ALL
SELECT
  'SELL' as action,
  COUNT(*) as total,
  SUM(CASE WHEN profit_rate IS NULL THEN 1 ELSE 0 END) as missing_profit_rate,
  SUM(CASE WHEN reason IS NULL THEN 1 ELSE 0 END) as missing_reason
FROM virtual_trading_records
WHERE action = 'SELL' AND is_test = 1;
```

### 2. 매수-매도 연결 검증
```sql
-- 고아 매도 기록 (매수 기록 없음)
SELECT COUNT(*) as orphan_sells
FROM virtual_trading_records s
WHERE s.action = 'SELL'
  AND s.is_test = 1
  AND s.buy_record_id NOT IN (
    SELECT id FROM virtual_trading_records WHERE action = 'BUY'
  );
```

### 3. 퀀트 점수 연결 가능 여부
```sql
-- 매수 시점에 점수 데이터가 있는지
SELECT
  COUNT(*) as total_buys,
  SUM(CASE WHEN f.stock_code IS NOT NULL THEN 1 ELSE 0 END) as has_score
FROM virtual_trading_records b
LEFT JOIN quant_factors f
  ON b.stock_code = f.stock_code
  AND f.calc_date <= DATE(b.timestamp)
WHERE b.action = 'BUY' AND b.is_test = 1;
```

---

## 📅 향후 수집 일정

| 주차 | 날짜 | 예상 완결 매매 | 누적 총계 | 비고 |
|------|------|----------------|-----------|------|
| 3주차 (현재) | 2026-01-05 | 20건 | 20건 | ✅ 현재 위치 |
| 4주차 | 2026-01-12 | +7건 | 27건 | |
| 5주차 | 2026-01-19 | +7건 | 34건 | |
| 6주차 | 2026-01-26 | +7건 | 41건 | |
| 7주차 | 2026-02-02 | +7건 | 48건 | |
| 8주차 | 2026-02-09 | +7건 | 55건 | 최소 목표 달성 |
| 9주차 | 2026-02-16 | +7건 | 62건 | 2개월 완료 |

**주간 평균 완결 매매**: 약 7건 (현재 3주에 20건 = 주당 6.7건)

---

## ✅ 결론: 데이터 수집 상태

### 🟢 잘 수집 중인 항목
1. ✅ 매수/매도 가격, 수량, 시각
2. ✅ 손익 금액, 손익률
3. ✅ 목표 익절률, 손절률
4. ✅ 청산 사유 (익절/손절/리밸런싱)
5. ✅ 퀀트 점수 (4개 팩터 + 종합)
6. ✅ 매수-매도 연결 (buy_record_id)

### 🟡 개선 가능 항목
1. ⚠️ 시장 환경 데이터 (KOSPI 등) - daily_prices에서 추출 가능
2. ⚠️ 섹터 정보 - KIS API로 수집 가능

### 🔴 불필요한 항목
1. ❌ 기술적 지표 - 퀀트 전략이므로 불필요
2. ❌ 뉴스/공시 - 당장 활용 어려움

---

## 🎯 다음 행동

1. **계속 수집** (현재 시스템 유지)
   - 손익절 로직 수정 완료 ✅
   - 자동 매매 기록 ✅
   - 목표: 50-60건 완결 매매

2. **중간 분석** (4주차, 약 30건 모일 때)
   - 손익절 비율 효과 1차 분석
   - 필요시 임시 조정

3. **최종 튜닝** (8-9주차, 50-60건 모일 때)
   - 위 SQL 쿼리로 상세 분석
   - 최적 손익절 비율 결정
   - 점수별 차등 목표율 조정
   - 팩터 가중치 재조정 고려

**현재 데이터 수집 상태: ✅ 매우 양호!**
