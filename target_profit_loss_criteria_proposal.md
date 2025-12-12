# 목표 익절/손절 조절 기준 제안

## 📊 현재 사용 가능한 데이터

매일 15:40 스크리닝에서 계산되는 데이터:
- `total_score`: 종합 점수 (0-100)
- `rank`: 순위 (1-50)
- `value_score`: Value 팩터 점수
- `momentum_score`: Momentum 팩터 점수
- `quality_score`: Quality 팩터 점수
- `growth_score`: Growth 팩터 점수

---

## 🎯 제안하는 기준 (우선순위 순)

### 1. **순위 기반 조절** (추천 ⭐⭐⭐)

**이유**: 순위는 종목의 상대적 우수성을 가장 잘 나타냄

**로직**:
```python
# 상위 10위: 높은 목표 수익률 (더 오래 보유)
# 중위 11-30위: 중간 목표 수익률
# 하위 31-50위: 낮은 목표 수익률 (빠른 익절)

if rank <= 10:
    target_profit = 0.20  # 20% (상위권 - 높은 기대)
    stop_loss = 0.08      # 8% (여유 있는 손절)
elif rank <= 30:
    target_profit = 0.15  # 15% (중위권 - 기본)
    stop_loss = 0.10      # 10% (기본 손절)
else:
    target_profit = 0.12  # 12% (하위권 - 빠른 익절)
    stop_loss = 0.10      # 10% (기본 손절)
```

**장점**:
- 구현 간단
- 직관적
- 상위 종목은 더 높은 수익 기대

**단점**:
- 순위만으로는 변동성 고려 부족

---

### 2. **점수 기반 조절** (추천 ⭐⭐⭐)

**이유**: 점수는 종목의 절대적 우수성을 나타냄

**로직**:
```python
# 점수 구간별 차등 적용
# 80점 이상: 최고 등급
# 70-80점: 상위 등급
# 60-70점: 중위 등급
# 60점 미만: 하위 등급

if total_score >= 80:
    target_profit = 0.22  # 22%
    stop_loss = 0.08      # 8%
elif total_score >= 70:
    target_profit = 0.18  # 18%
    stop_loss = 0.09      # 9%
elif total_score >= 60:
    target_profit = 0.15  # 15%
    stop_loss = 0.10      # 10%
else:
    target_profit = 0.12  # 12%
    stop_loss = 0.10      # 10%
```

**장점**:
- 절대적 기준으로 안정적
- 점수 변화에 따라 자동 조절

**단점**:
- 점수 분포에 따라 구간 조정 필요

---

### 3. **Momentum 팩터 기반 조절** (추천 ⭐⭐)

**이유**: Momentum이 높으면 상승 추세가 강함 → 더 높은 목표 수익률

**로직**:
```python
# Momentum 점수가 높으면 상승 추세 강함
# 높은 Momentum → 높은 목표 수익률

if momentum_score >= 80:
    target_profit = 0.20  # 20%
    stop_loss = 0.08      # 8%
elif momentum_score >= 60:
    target_profit = 0.15  # 15%
    stop_loss = 0.10      # 10%
else:
    target_profit = 0.12  # 12%
    stop_loss = 0.10      # 10%
```

**장점**:
- 추세 기반으로 합리적
- 단기 수익에 효과적

**단점**:
- Momentum만으로는 리스크 고려 부족

---

### 4. **복합 기준 (순위 + 점수)** (추천 ⭐⭐⭐⭐)

**이유**: 순위와 점수를 모두 고려하여 더 정확한 판단

**로직**:
```python
# 순위와 점수를 모두 고려
# 가중치: 순위 60%, 점수 40%

rank_weight = 0.6
score_weight = 0.4

# 순위 점수 (1위=100점, 50위=0점)
rank_score = (51 - rank) / 50 * 100

# 점수 정규화 (0-100)
normalized_score = total_score

# 종합 점수
composite_score = rank_score * rank_weight + normalized_score * score_weight

# 종합 점수 기반 목표 수익률
if composite_score >= 80:
    target_profit = 0.20
    stop_loss = 0.08
elif composite_score >= 60:
    target_profit = 0.15
    stop_loss = 0.10
else:
    target_profit = 0.12
    stop_loss = 0.10
```

**장점**:
- 가장 정확한 판단
- 상대적/절대적 기준 모두 고려

**단점**:
- 구현 복잡도 증가

---

### 5. **변동성 기반 조절** (추천 ⭐⭐)

**이유**: 변동성이 높으면 목표 수익률도 높게 설정

**로직**:
```python
# 최근 20일 변동성 계산
volatility = calculate_volatility(stock_code, days=20)

# 변동성 구간별 조절
if volatility >= 0.03:  # 3% 이상 (고변동성)
    target_profit = 0.20
    stop_loss = 0.12     # 손절도 넓게
elif volatility >= 0.02:  # 2-3% (중변동성)
    target_profit = 0.15
    stop_loss = 0.10
else:  # 2% 미만 (저변동성)
    target_profit = 0.12
    stop_loss = 0.08
```

**장점**:
- 리스크 기반 조절
- 변동성에 맞는 목표 설정

**단점**:
- 변동성 계산 필요
- 추가 데이터 수집 필요

---

## 💡 최종 추천안: **복합 기준 (순위 + 점수 + Momentum)**

### 이유
1. **순위**: 상대적 우수성 반영
2. **점수**: 절대적 우수성 반영
3. **Momentum**: 추세 강도 반영

### 구현 예시

```python
def calculate_target_profit_loss(rank: int, total_score: float, 
                                 momentum_score: float) -> Tuple[float, float]:
    """
    종목별 목표 익절/손절률 계산
    
    Args:
        rank: 순위 (1-50)
        total_score: 종합 점수 (0-100)
        momentum_score: Momentum 팩터 점수 (0-100)
    
    Returns:
        (target_profit_rate, stop_loss_rate)
    """
    # 1. 순위 점수 (1위=100점, 50위=0점)
    rank_score = (51 - rank) / 50 * 100
    
    # 2. 점수 정규화
    score_normalized = total_score
    
    # 3. Momentum 점수 정규화
    momentum_normalized = momentum_score
    
    # 4. 가중 평균
    # 순위 40%, 점수 30%, Momentum 30%
    composite_score = (
        rank_score * 0.40 +
        score_normalized * 0.30 +
        momentum_normalized * 0.30
    )
    
    # 5. 구간별 목표 수익률/손절률
    if composite_score >= 80:
        return 0.20, 0.08  # 상위권: 20% 익절, 8% 손절
    elif composite_score >= 65:
        return 0.17, 0.09  # 중상위: 17% 익절, 9% 손절
    elif composite_score >= 50:
        return 0.15, 0.10  # 중위권: 15% 익절, 10% 손절
    elif composite_score >= 35:
        return 0.13, 0.10  # 중하위: 13% 익절, 10% 손절
    else:
        return 0.12, 0.10  # 하위권: 12% 익절, 10% 손절
```

---

## 📋 적용 범위

### 기본값 (trading_config.json)
- 기본 익절: 15%
- 기본 손절: 10%

### 조절 범위
- **익절**: 12% ~ 22%
- **손절**: 8% ~ 12%

### 적용 시점
- **리밸런싱 매수 시점**: 종목별 목표 익절/손절률 계산 및 설정
- **매일 갱신**: 15:40 스크리닝 후 새로운 점수로 재계산

---

## 🔄 구현 위치

1. **리밸런싱 서비스** (`core/quant/quant_rebalancing_service.py`)
   - `calculate_rebalancing_plan()`에서 목표 익절/손절률 계산
   - `buy_list`에 `target_profit_rate`, `stop_loss_rate` 추가

2. **매수 실행** (`main.py`의 `_execute_rebalancing_async()`)
   - 매수 후 `TradingStock` 객체에 `target_profit_rate` 설정

3. **매도 판단** (`core/trading_decision_engine.py`)
   - `_check_profit_target()`: 종목별 `target_profit_rate` 사용
   - `_check_stop_loss_conditions()`: 종목별 `stop_loss_rate` 사용 (추가 필요)

---

## ⚙️ 설정 가능한 파라미터

`config/trading_config.json`에 추가:

```json
{
  "risk_management": {
    "target_profit_adjustment": {
      "enabled": true,
      "method": "composite",  // "rank", "score", "momentum", "composite"
      "weights": {
        "rank": 0.40,
        "score": 0.30,
        "momentum": 0.30
      },
      "ranges": {
        "high": {"profit": 0.20, "loss": 0.08},
        "medium_high": {"profit": 0.17, "loss": 0.09},
        "medium": {"profit": 0.15, "loss": 0.10},
        "medium_low": {"profit": 0.13, "loss": 0.10},
        "low": {"profit": 0.12, "loss": 0.10}
      }
    }
  }
}
```

---

## 📊 예상 효과

1. **상위 종목**: 더 높은 목표 수익률 → 더 큰 수익 기회
2. **하위 종목**: 낮은 목표 수익률 → 빠른 익절로 리스크 감소
3. **전체 포트폴리오**: 종목별 차등 적용으로 수익률 향상 기대

---

## 🎯 최종 추천

**복합 기준 (순위 + 점수 + Momentum)** 사용을 추천합니다.

이유:
- ✅ 가장 정확한 판단
- ✅ 퀀트 투자 관점에서 합리적
- ✅ 매일 갱신되는 데이터 활용
- ✅ 구현 복잡도는 적절한 수준

