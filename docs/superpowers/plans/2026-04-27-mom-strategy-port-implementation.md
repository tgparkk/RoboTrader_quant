# mom_006676 운영 시스템 포팅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `RoboTrader_quant_mom` 워크트리에서 V100 운영 코드를 mom_006676 momentum 전용으로 완전 교체하여 백테스트 ±10% 검증 통과.

**Architecture:** 운영 V100 시스템(`RoboTrader_quant`, branch main)은 손대지 않고 mom-strategy 브랜치에서만 변경. multiverse_min의 `MomentumScorer.risk_adjusted` 로직을 운영 시스템 `quant_screening_service` 와 backtest `factor_calculator` 양쪽에 동일 구현. monthly 리밸런싱은 단순 `is_first_trading_day_of_month()` 게이트로 추가. 장중 모니터링·장전 분석·재무 수집은 no-op 처리하여 sim 동일 동작 보장.

**Tech Stack:** Python 3, PostgreSQL (port 5433), psycopg2, pandas, pytest, KIS API (paper trading 단계에서 추가).

**Spec:** `docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md`

---

## File Structure

| 파일 | 책임 | 변경 유형 |
|---|---|---|
| `config/db_config.py` | DB 이름 분리 (`robotrader_quant_mom`) | Modify |
| `config/constants.py` | PORTFOLIO_SIZE=15, BUY_RET5D_MIN=None, BUY_SCORE_MOMENTUM_MIN=None | Modify |
| `core/quant/quant_screening_service.py` | momentum scorer 교체, V100 로직 제거 | Modify (대규모) |
| `core/quant/quant_rebalancing_service.py` | monthly 트리거, buy_min_score 임계값 변경 | Modify |
| `core/quant/target_profit_loss_calculator.py` | TP/SL=99 (사실상 무한) | Modify |
| `core/trading_stock_manager.py` | 장중 TP/SL 체크 no-op | Modify |
| `core/pre_market_analyzer.py` | 호출부 비활성화 (파일 자체는 보존) | No change |
| `backtest/factor_calculator.py` | momentum scorer 교체 (사이드 by 사이드) | Modify (대규모) |
| `backtest/backtester.py` | monthly 트리거 + TP/SL skip 옵션 | Modify |
| `backtest/models.py` | tp_sl=99 default | Modify |
| `main.py` | 재무수집 / 장전분석 호출 제거 | Modify |
| `robotrader_quant.pid` → `robotrader_quant_mom.pid` | 프로세스 격리 | Modify (line 57) |
| `utils/trading_calendar.py` | `is_first_trading_day_of_month()` 신규 함수 | Create or Modify |
| `tests/test_momentum_scorer.py` | momentum scorer 단위 테스트 | Create |
| `tests/test_monthly_rebalance.py` | 첫 거래일 판정 테스트 | Create |
| `scripts/migrate_db_to_mom.py` | 기존 schema → robotrader_quant_mom 마이그레이션 | Create |
| `scripts/run_mom_backtest.py` | mom_006676 운영 백테스트 실행 | Create |

---

## Task 1: DB 분리 + config 변경

**Files:**
- Modify: `config/db_config.py`
- Modify: `config/constants.py`
- Modify: `main.py` (line 57: pid_file)
- Create: `scripts/migrate_db_to_mom.py`
- Test: PG에 신규 DB 생성 + 기존 schema 복제

- [ ] **Step 1: 새 DB 생성**

PG에 `robotrader_quant_mom` DB 생성:
```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE robotrader_quant_mom;"
```
Expected: `CREATE DATABASE`

- [ ] **Step 2: 기존 schema 복제 마이그레이션 스크립트 작성**

Create `scripts/migrate_db_to_mom.py`:
```python
"""기존 robotrader_quant schema를 robotrader_quant_mom으로 복제.

데이터는 복제하지 않음 (운영 V100과 무관한 신규 시스템).
스키마(테이블, 인덱스, 제약조건)만 복제.
"""
import subprocess
import os

PG_HOST = "127.0.0.1"
PG_PORT = "5433"
PG_USER = "postgres"
PG_PASSWORD = "postgres"
SOURCE_DB = "robotrader_quant"
TARGET_DB = "robotrader_quant_mom"


def main() -> None:
    env = {**os.environ, "PGPASSWORD": PG_PASSWORD}
    # schema-only dump
    dump = subprocess.run(
        ["pg_dump", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER,
         "--schema-only", "--no-owner", SOURCE_DB],
        env=env, check=True, capture_output=True, text=True,
    )
    # restore to target
    subprocess.run(
        ["psql", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", TARGET_DB],
        env=env, check=True, input=dump.stdout, text=True,
    )
    print(f"[migrate] schema copied from {SOURCE_DB} to {TARGET_DB}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 마이그레이션 실행**

Run: `python scripts/migrate_db_to_mom.py`
Expected: `[migrate] schema copied from robotrader_quant to robotrader_quant_mom`

- [ ] **Step 4: db_config.py 변경**

Edit `config/db_config.py:12`:
```python
# Before:
'dbname': os.environ.get('DB_NAME', 'robotrader_quant'),

# After:
'dbname': os.environ.get('DB_NAME', 'robotrader_quant_mom'),
```

- [ ] **Step 5: pid_file 변경**

Edit `main.py:57`:
```python
# Before:
self.pid_file = Path("robotrader_quant.pid")

# After:
self.pid_file = Path("robotrader_quant_mom.pid")
```

- [ ] **Step 6: PORTFOLIO_SIZE + 필터 변경**

Edit `config/constants.py`:
```python
# Before (line 6):
PORTFOLIO_SIZE = 10

# After:
PORTFOLIO_SIZE = 15  # mom_006676 paramset

# Before (line 36):
BUY_RET5D_MIN = -3.0

# After:
BUY_RET5D_MIN = None  # momentum은 추세 추종이므로 급락 필터 제거 (sim 동일)
```

`BUY_SCORE_MOMENTUM_MIN`은 이미 `None` (line 44).

- [ ] **Step 7: DB 연결 검증**

Run:
```bash
python -c "from config.db_config import DB_CONFIG; print(DB_CONFIG['dbname'])"
```
Expected: `robotrader_quant_mom`

Run:
```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -p 5433 -U postgres -d robotrader_quant_mom -c "\dt"
```
Expected: 테이블 목록 출력 (`real_trading_records`, `daily_prices`, `quant_factor_scores`, `quant_portfolio` 등)

- [ ] **Step 8: Commit**

```bash
git add config/db_config.py config/constants.py main.py scripts/migrate_db_to_mom.py
git commit -m "$(cat <<'EOF'
chore(mom): DB 분리(robotrader_quant_mom) + paramset 일부

- DB_CONFIG.dbname → robotrader_quant_mom
- PORTFOLIO_SIZE 10 → 15 (mom_006676 paramset)
- BUY_RET5D_MIN -3.0 → None (sim 동일성)
- pid_file robotrader_quant.pid → robotrader_quant_mom.pid
- migrate_db_to_mom.py 신규 (schema-only 복제)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Momentum Scorer 신규 모듈

**Files:**
- Create: `core/quant/momentum_scorer.py`
- Create: `tests/test_momentum_scorer.py`

multiverse_min `RiskAdjustedMomentumScorer` 와 동일 식 구현. 별도 모듈로 분리하여 운영 + 백테스트 양쪽에서 import.

- [ ] **Step 1: Failing test 작성**

Create `tests/test_momentum_scorer.py`:
```python
"""Momentum scorer 단위 테스트 (multiverse_min과 식 일치 검증)."""
import math
import numpy as np
import pandas as pd
from datetime import date

from core.quant.momentum_scorer import compute_risk_adjusted_momentum


def test_returns_zero_for_flat_prices():
    """가격 변화 0 → 수익률 0, std 0 → 점수 정의 0 또는 NaN."""
    prices = pd.Series(
        [100.0] * 252,
        index=pd.date_range("2025-04-01", periods=252, freq="B"),
    )
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert math.isclose(score, 0.0, abs_tol=1e-9) or math.isnan(score)


def test_positive_for_uptrend():
    """단조 상승 → 양수 점수."""
    prices = pd.Series(
        np.linspace(100.0, 200.0, 252),
        index=pd.date_range("2025-04-01", periods=252, freq="B"),
    )
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert score > 0


def test_skip_excludes_recent_month():
    """최근 1개월에 폭등이 있어도 skip=1이면 그 구간 제외 → 폭등 미반영."""
    n = 252
    prices = list(np.linspace(100.0, 110.0, n - 21))  # 11개월 완만한 상승
    prices += list(np.linspace(110.0, 300.0, 21))     # 직전 1개월 폭등
    series = pd.Series(prices, index=pd.date_range("2025-04-01", periods=n, freq="B"))
    score_skip1 = compute_risk_adjusted_momentum(series, lookback_months=12, skip_months=1)
    score_skip0 = compute_risk_adjusted_momentum(series, lookback_months=12, skip_months=0)
    assert score_skip1 < score_skip0   # skip이 폭등 구간을 제외하므로 점수 낮음


def test_insufficient_history_returns_nan():
    """이력이 lookback 미만 → NaN."""
    prices = pd.Series(
        [100.0] * 50,
        index=pd.date_range("2025-04-01", periods=50, freq="B"),
    )
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert math.isnan(score)
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_momentum_scorer.py -v`
Expected: `ImportError: No module named 'core.quant.momentum_scorer'`

- [ ] **Step 3: Scorer 구현**

Create `core/quant/momentum_scorer.py`:
```python
"""Risk-adjusted momentum scorer.

multiverse_min `strategy_v2/multiverse_min/modules/scorers.py::RiskAdjustedMomentumScorer`
와 식 일치. 운영 + 백테스트 모듈에서 공통 사용.

식: (price[t-skip*21] / price[t-(lookback*21)] - 1) / std(daily_returns) * sqrt(252)
- lookback_months: 12 (12*21 ≈ 252 거래일)
- skip_months:    1  (1*21 = 21 거래일 — 직전 1개월 제외)
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


TRADING_DAYS_PER_MONTH = 21


def compute_risk_adjusted_momentum(
    prices: pd.Series,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> float:
    """Risk-adjusted momentum 점수.

    Args:
        prices: 일봉 종가 시계열 (오름차순 날짜 인덱스). 최소 lookback*21+1 영업일 필요.
        lookback_months: 모멘텀 측정 기간 (개월).
        skip_months: 직전 제외 구간 (개월).

    Returns:
        float 점수. 이력 부족 또는 std=0 → NaN.
    """
    lookback_days = lookback_months * TRADING_DAYS_PER_MONTH
    skip_days = skip_months * TRADING_DAYS_PER_MONTH

    if len(prices) < lookback_days + 1:
        return float("nan")

    # 가장 최근에서 skip_days 만큼 잘라낸 윈도우의 양 끝
    end_idx = len(prices) - 1 - skip_days
    start_idx = end_idx - (lookback_days - skip_days)
    if start_idx < 0:
        return float("nan")

    window = prices.iloc[start_idx : end_idx + 1]
    if len(window) < 2:
        return float("nan")

    p_start = float(window.iloc[0])
    p_end = float(window.iloc[-1])
    if p_start <= 0:
        return float("nan")

    raw_return = p_end / p_start - 1.0

    daily_returns = window.pct_change().dropna()
    if len(daily_returns) < 2:
        return float("nan")
    annualized_std = float(daily_returns.std()) * math.sqrt(252)
    if annualized_std <= 0:
        return 0.0 if math.isclose(raw_return, 0.0) else float("nan")

    return raw_return / annualized_std
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_momentum_scorer.py -v`
Expected: 4 passed

- [ ] **Step 5: multiverse_min 식 일치 검증 (선택)**

multiverse_min 구현과 동일 출력인지 한 번 검증. multiverse_min repo를 sys.path 에 임시 추가하여 비교:
```bash
python -c "
import sys
sys.path.insert(0, 'D:/GIT/RoboTrader_quant_v2')
from strategy_v2.multiverse_min.modules.scorers import RiskAdjustedMomentumScorer
import pandas as pd, numpy as np
prices = pd.Series(np.linspace(100, 200, 252), index=pd.date_range('2025-01-01', periods=252, freq='B'))
mv_scorer = RiskAdjustedMomentumScorer(lookback_months=12, skip_months=1)
mv_score = mv_scorer.score(prices)
from core.quant.momentum_scorer import compute_risk_adjusted_momentum
op_score = compute_risk_adjusted_momentum(prices, 12, 1)
print(f'mv={mv_score:.6f} op={op_score:.6f} diff={abs(mv_score-op_score):.2e}')
"
```
Expected: `diff < 1e-6`

만약 식 차이 발견 시 multiverse_min 구현 우선으로 우리 구현 정렬.

- [ ] **Step 6: Commit**

```bash
git add core/quant/momentum_scorer.py tests/test_momentum_scorer.py
git commit -m "$(cat <<'EOF'
feat(mom): risk-adjusted momentum scorer (multiverse_min 식 일치)

- core/quant/momentum_scorer.py 신규
- (price[t-skip*21] / price[t-(lookback*21)] - 1) / annualized_std
- 단위 테스트 4건 통과
- multiverse_min RiskAdjustedMomentumScorer와 식 검증 일치

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 거래 캘린더 (첫 거래일 판정)

**Files:**
- Create: `utils/trading_calendar.py`
- Create: `tests/test_trading_calendar.py`

multiverse_min `MonthlyRebalancer` 동일 의미. 영업일 캘린더 기준 첫 거래일.

- [ ] **Step 1: Failing test 작성**

Create `tests/test_trading_calendar.py`:
```python
"""거래 캘린더 첫 거래일 판정 테스트."""
from datetime import date

from utils.trading_calendar import is_first_trading_day_of_month


def test_first_trading_day_of_april_2026():
    """2026-04-01 (수) 영업일. 4월 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 4, 1)) is True


def test_first_trading_day_when_1st_is_holiday():
    """2026-01-01 (목) 신정 휴일. 2026-01-02 (금) 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 1, 1)) is False
    assert is_first_trading_day_of_month(date(2026, 1, 2)) is True


def test_mid_month_returns_false():
    """월 중간 영업일은 False."""
    assert is_first_trading_day_of_month(date(2026, 4, 15)) is False


def test_weekend_returns_false():
    """주말은 첫 거래일 아님."""
    assert is_first_trading_day_of_month(date(2026, 3, 1)) is False  # 일요일
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_trading_calendar.py -v`
Expected: `ImportError`

- [ ] **Step 3: 구현**

KIS API 사용 시 영업일 캘린더가 필요. 단순 구현은 KRX 공휴일 리스트 + 주말 제외. 운영 시스템에 이미 `utils/korean_time.py` 또는 `config/market_hours.py`에 영업일 판정 로직 있을 가능성 — 우선 그 코드 재활용. 없으면 `pykrx.get_business_days()` 사용.

Create `utils/trading_calendar.py`:
```python
"""거래 캘린더 — 첫 거래일 판정 (월간 리밸런싱 트리거).

KRX 영업일 기준. 단순 구현: 주말 제외 + 공휴일 리스트.
운영 시스템에 기존 영업일 헬퍼 있으면 그것을 import 하여 사용.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Set


# 주요 한국 공휴일 (월간 첫 거래일 판정용 — 2024-2026 범위만 명시)
# 향후 확장 시 KRX 공식 캘린더 또는 pykrx 사용
KR_HOLIDAYS: Set[date] = {
    # 2024
    date(2024, 1, 1), date(2024, 2, 9), date(2024, 2, 12),
    date(2024, 3, 1), date(2024, 5, 5), date(2024, 5, 6),
    date(2024, 5, 15), date(2024, 6, 6), date(2024, 8, 15),
    date(2024, 9, 16), date(2024, 9, 17), date(2024, 9, 18),
    date(2024, 10, 3), date(2024, 10, 9), date(2024, 12, 25),
    date(2024, 12, 31),
    # 2025
    date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29),
    date(2025, 1, 30), date(2025, 3, 3), date(2025, 5, 5),
    date(2025, 5, 6), date(2025, 6, 6), date(2025, 8, 15),
    date(2025, 10, 3), date(2025, 10, 6), date(2025, 10, 7),
    date(2025, 10, 8), date(2025, 10, 9), date(2025, 12, 25),
    date(2025, 12, 31),
    # 2026
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
    date(2026, 2, 18), date(2026, 3, 1), date(2026, 5, 5),
    date(2026, 5, 25), date(2026, 6, 6), date(2026, 8, 15),
    date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 9),
    date(2026, 12, 25), date(2026, 12, 31),
}


def is_trading_day(d: date) -> bool:
    """주말 + 공휴일 제외."""
    if d.weekday() >= 5:  # 토(5), 일(6)
        return False
    if d in KR_HOLIDAYS:
        return False
    return True


def is_first_trading_day_of_month(d: date) -> bool:
    """d 가 그 달의 첫 거래일이면 True."""
    if not is_trading_day(d):
        return False
    # d 이전 같은 달의 모든 영업일이 trading_day 가 아니어야 함
    cur = d.replace(day=1)
    while cur < d:
        if is_trading_day(cur):
            return False
        cur += timedelta(days=1)
    return True
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_trading_calendar.py -v`
Expected: 4 passed

- [ ] **Step 5: 운영 시스템에 기존 영업일 헬퍼 있는지 확인**

Run: `grep -rn "is_business_day\|trading_day\|is_market_open" utils/ config/ --include='*.py' | head -10`

기존 헬퍼 발견 시 그것으로 대체하고 우리 `is_first_trading_day_of_month` 만 wrapper 로 유지.

- [ ] **Step 6: Commit**

```bash
git add utils/trading_calendar.py tests/test_trading_calendar.py
git commit -m "$(cat <<'EOF'
feat(mom): 거래 캘린더 - 첫 거래일 판정

- utils/trading_calendar.py 신규
- KRX 공휴일(2024-2026) + 주말 제외
- is_first_trading_day_of_month: monthly 리밸런싱 트리거

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 운영 스크리닝 momentum 교체

**Files:**
- Modify: `core/quant/quant_screening_service.py`

V100 점수 (`_calc_value_score` 등) 호출 제거 → momentum scorer 호출. `total_score` 의미를 momentum 점수로 재정의.

- [ ] **Step 1: 현재 _calculate_scores 함수 확인**

Read: `core/quant/quant_screening_service.py:412-460`

V100 식 (line 439): `total_score = value_score`
- value/quality/growth 모두 재무 데이터 기반
- mom 전환 시 재무 호출 자체 불필요

- [ ] **Step 2: 새 momentum 기반 _calculate_scores 작성**

Edit `core/quant/quant_screening_service.py` 의 `_calculate_scores`:

원본 함수의 위치는 `def _calculate_scores(self, ratio, income, balance, price_data, stock_code: str)` (line 412). 다음으로 교체:

```python
def _calculate_scores(self, ratio, income, balance, price_data, stock_code: str) -> Optional[Dict[str, Any]]:
    """mom_006676 risk-adjusted momentum 점수 계산.

    재무 데이터(ratio/income/balance)는 사용하지 않음.
    price_data 만으로 12M lookback / 1M skip momentum 계산.
    """
    from core.quant.momentum_scorer import compute_risk_adjusted_momentum

    if price_data is None or len(price_data) < 252:
        return None

    prices = price_data['close']
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    if not isinstance(score, (int, float)) or math.isnan(score) or math.isinf(score):
        return None

    # 운영 코드는 (V100과 호환) 0-100 스케일을 가정. risk-adjusted momentum은
    # 보통 -2~+5 범위. 단순 affine: score → 50 + 25 * score, clamp [0, 100].
    # 이 변환은 monthly 첫 거래일 cross-section 내 상대 순위에만 영향 (절대값 의미 없음)
    # → buy_min_score 임계값도 함께 재조정 (Task 6).
    scaled = max(0.0, min(100.0, 50.0 + 25.0 * score))

    details = {
        'value': 0.0,
        'momentum': scaled,
        'quality': 0.0,
        'growth': 0.0,
        'reason': f"momentum risk-adj raw={score:.3f} scaled={scaled:.1f}",
        'total_score': scaled,
    }
    return details
```

⚠️ 중요: 원본은 `'value' / 'momentum' / 'quality' / 'growth' / 'reason'` 키만 반환. 우리 구현은 `total_score` 도 추가로 넣고 호출부에서 재계산하지 않도록 변경 필요.

- [ ] **Step 3: 호출부 (line 380-400 근처) 수정**

원본 정렬 (line 387):
```python
rows.sort(key=lambda x: (x['total_score'], x.get('momentum_score', 0)), reverse=True)
```

→ 그대로 유지. momentum 시스템에서도 `total_score` 기준 내림차순. 단, `momentum_score` 폴백은 0이므로 동점 시 무의미. 동점 거의 없으므로 OK.

`_calc_value_score`, `_calc_quality_score`, `_calc_growth_score` 호출은 `_calculate_scores` 내부에서 제거되므로 외부 호출부 변경 불필요.

- [ ] **Step 4: 재무 데이터 조회 비활성화**

`_calculate_scores` 호출부 상단에서 ratio/income/balance 를 조회하는 코드가 있을 수 있음. mom 시스템에선 재무 데이터 가져올 필요 없음. 다만 함수 시그니처 호환을 위해 `None` 으로 전달.

Search:
```bash
grep -n "ratio.*income.*balance" core/quant/quant_screening_service.py | head -5
```

각 호출부에서 ratio/income/balance 자리에 `None` 전달 (단, `price_data` 는 그대로):
```python
# Before:
score_dict = self._calculate_scores(ratio, income, balance, price_data, stock_code)

# After:
score_dict = self._calculate_scores(None, None, None, price_data, stock_code)
```

- [ ] **Step 5: 단위 테스트**

기존 `tests/test_quant_factors.py` 가 V100 가정으로 작성되어 있을 가능성. 실패 예상.

Run: `pytest tests/test_quant_factors.py -v`
Expected: 일부 FAIL (V100 점수 가정과 충돌). 이 시점에서 momentum 가정으로 테스트 재작성 또는 skip 마크.

간이 통합 테스트:
```bash
python -c "
import pandas as pd, numpy as np
from datetime import date
class FakePrice:
    pass
prices = pd.Series(np.linspace(100, 200, 252), index=pd.date_range('2025-04-01', periods=252, freq='B'))
df = pd.DataFrame({'close': prices})
from core.quant.quant_screening_service import QuantScreeningService
# minimal instantiation skip - just call _calculate_scores statically
class S(QuantScreeningService):
    def __init__(self): pass
s = S()
import logging; s.logger = logging.getLogger('test')
res = s._calculate_scores(None, None, None, df, '005930')
print(res)
"
```
Expected: `total_score` > 50 (uptrend → 양수 momentum)

- [ ] **Step 6: Commit**

```bash
git add core/quant/quant_screening_service.py
git commit -m "$(cat <<'EOF'
feat(mom): quant_screening_service momentum 교체

- _calculate_scores: value/quality/growth 제거, risk-adjusted momentum만 사용
- 12M lookback / 1M skip
- 0-100 affine 스케일 (50 + 25*score, clamp)
- 재무 데이터(ratio/income/balance) 호출 제거 → None 전달

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: monthly 리밸런싱 트리거 (운영)

**Files:**
- Modify: `core/quant/quant_rebalancing_service.py`
- Modify: `main.py` (리밸런싱 호출부)

매월 첫 거래일에만 `execute_rebalancing()` 진입. 그 외엔 즉시 return.

- [ ] **Step 1: rebalancing_service 의 진입점 함수 확인**

Read `core/quant/quant_rebalancing_service.py` 메서드 시그니처. 대표적으로 `execute_rebalancing(today: date)` 또는 `run_daily_rebalancing()` 등이 있을 것.

Run: `grep -n "def execute\|def run_\|def rebalance" core/quant/quant_rebalancing_service.py | head -10`

- [ ] **Step 2: monthly 게이트 추가**

진입점 함수 첫줄에 추가:
```python
from utils.trading_calendar import is_first_trading_day_of_month

def execute_rebalancing(self, today: date) -> None:
    if not is_first_trading_day_of_month(today):
        self.logger.info(f"⏭️  {today} not first trading day. monthly skip.")
        return
    # 기존 로직 그대로
    ...
```

만약 진입점이 여러 개면 모두에 적용. 또는 가장 위에서 한 번 게이트.

- [ ] **Step 3: rebalancing_period 디폴트 변경**

`core/quant/quant_rebalancing_service.py:39`:
```python
# Before:
self.rebalancing_period = RebalancingPeriod.DAILY

# After:
self.rebalancing_period = RebalancingPeriod.MONTHLY
```

- [ ] **Step 4: target_portfolio_size 변경**

`core/quant/quant_rebalancing_service.py:40`:
```python
# Before:
self.target_portfolio_size = 10

# After:
self.target_portfolio_size = 15  # mom_006676
```

- [ ] **Step 5: buy_min_score 임계값 재조정**

V100은 95 (재무비율 0-100 직접 매핑) → momentum 0-100 affine 스케일은 다른 분포.

momentum scaled 분포: cross-section 내 상위 15개의 score 가 보통 75+. 단순 임계값 65로 시작 (다단계 스토프 65/67/75 와 정합).

`core/quant/quant_rebalancing_service.py:57`:
```python
# Before:
self.buy_min_score = 95.0

# After:
self.buy_min_score = 65.0  # momentum 0-100 affine, hard_stop과 정합
```

- [ ] **Step 6: 통합 동작 sanity 확인**

Run: `python -c "from core.quant.quant_rebalancing_service import QuantRebalancingService, RebalancingPeriod; print(RebalancingPeriod.MONTHLY.value)"`
Expected: `monthly`

- [ ] **Step 7: Commit**

```bash
git add core/quant/quant_rebalancing_service.py
git commit -m "$(cat <<'EOF'
feat(mom): monthly 리밸런싱 트리거 + paramset

- 매월 첫 거래일만 execute_rebalancing 진입 (utils.trading_calendar 게이트)
- rebalancing_period DAILY → MONTHLY
- target_portfolio_size 10 → 15
- buy_min_score 95 → 65 (momentum 0-100 affine 분포 기준)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: TP/SL + 장중 모니터링 + 장전 분석 + 재무 비활성화

**Files:**
- Modify: `core/quant/target_profit_loss_calculator.py`
- Modify: `core/trading_stock_manager.py`
- Modify: `main.py` (08:30 재무 수집, 08:40 장전 분석 호출 제거)

- [ ] **Step 1: TP/SL = 99 (사실상 무한) 설정**

Read `core/quant/target_profit_loss_calculator.py` 의 target_profit_rate / stop_loss_rate 정의 위치 확인.

대상 라인 수정:
```python
# Before:
target_profit_rate = 0.12  # 12%
stop_loss_rate = 0.06      # 6%

# After:
target_profit_rate = 99.0  # mom: TP/SL 비활성 (sim 동일)
stop_loss_rate = 99.0      # mom: TP/SL 비활성 (sim 동일)
```

- [ ] **Step 2: 장중 TP/SL 체크 no-op**

Read `core/trading_stock_manager.py` 의 3초 루프 / `decision_engine` 호출부.

가장 안전한 방식: `trading_decision_engine.evaluate_for_sale()` 같은 함수 진입 직후 즉시 return. 또는 luma 함수 호출을 if-guard 로 감쌈.

대표 위치 수정 — `core/trading_stock_manager.py` 또는 `core/trading_decision_engine.py` 의 매도 판단 함수 첫줄에:
```python
def should_sell(self, ...) -> bool:
    # mom-strategy: 장중 TP/SL 비활성, 다음 월초 리밸런싱에서만 청산
    return False
```

⚠️ 호출부 분기 영향 검증 필요. 부분적 변경 시 회귀 테스트:
```bash
grep -rn "should_sell\|evaluate_for_sale\|check_tp_sl" core/ | head -10
```

- [ ] **Step 3: 장전 분석 호출 제거**

Read `main.py` — 08:40 스케줄 호출 위치 (보통 `_run_pre_market_analysis()` 또는 비슷).

Run: `grep -n "pre_market\|08:40\|pre_market_analyzer" main.py`

호출부 if False / continue 처리 또는 호출 라인 주석:
```python
# Before:
if current_time >= time(8, 40) and not self._pre_market_done:
    await self._run_pre_market_analysis()

# After (mom-strategy: 장전 분석 비활성, sim regime_filter=off):
# 장전 분석은 mom-strategy 에서 비활성화. 필요시 활성화하려면 아래 if 복원.
```

`core/pre_market_analyzer.py` 파일은 그대로 보존 (향후 재활용).

- [ ] **Step 4: 재무 수집 호출 제거**

08:30 스케줄에서 `_run_daily_financial_data_collection()` 같은 함수 호출 제거.

Run: `grep -n "08:30\|financial.*collect\|재무.*수집" main.py`

해당 라인 주석 또는 if-guard:
```python
# 재무 수집 mom-strategy 에선 불필요 (momentum은 가격만 사용)
# await self._collect_financial_data()
```

일봉 수집은 그대로 유지 (momentum 이 사용).

- [ ] **Step 5: pre_market_analyzer import 검증**

main.py 에서 pre_market_analyzer 가 import 만 되고 호출 안 되는 dead import 가 되었는지 확인. dead import 는 lint 경고 수준이므로 지금은 그대로 두고 마지막 정리에서 제거.

- [ ] **Step 6: 통합 동작 검증**

Run: `python -c "import main; print('imports ok')"`
Expected: import 에러 없음 (런타임 에러는 main.py 실행 시 별도 검증)

- [ ] **Step 7: Commit**

```bash
git add core/quant/target_profit_loss_calculator.py core/trading_stock_manager.py main.py
git commit -m "$(cat <<'EOF'
feat(mom): TP/SL 무한대 + 장중 모니터링/장전 분석/재무 수집 비활성

- TP/SL 0.12/0.06 → 99/99 (사실상 무한, sim tp_sl_mode=none 동일)
- trading_stock_manager 매도 판단 always False
- main.py 08:30 재무 수집 호출 제거 (momentum 가격만 사용)
- main.py 08:40 장전 분석 호출 제거 (sim regime_filter=off 동일성)
- pre_market_analyzer.py 자체는 보존 (향후 재활용)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: cap_min 3조 필터

**Files:**
- Modify: `core/candidate_selector.py` 또는 `core/quant/quant_screening_service.py` (필터 적용 위치 검색 후 결정)

- [ ] **Step 1: 현재 cap_min 적용 위치 검색**

Run: `grep -rn "MIN_MARKET_CAP\|market_cap\|시총\|시가총액" core/ config/ | grep -iv test | head -20`

대표 후보:
- `core/candidate_selector.py` — 후보 선정 시 시총 필터
- `core/quant/quant_screening_service.py` — 스크리닝 후 시총 필터
- `config/constants.py` — MIN_MARKET_CAP 상수

- [ ] **Step 2: MIN_MARKET_CAP 변경**

가장 가능성 높은 위치 (Step 1 결과 따라 조정):

`config/constants.py` 또는 `core/quant/quant_screening_service.py` 파일 상단:
```python
# Before:
MIN_MARKET_CAP = 100_0000_0000  # 100억 (1e10)

# After:
MIN_MARKET_CAP = 3_0000_0000_0000  # 3조 (3e12), mom_006676 paramset
```

또는 변수 이름이 다르면 그것도 변경.

- [ ] **Step 3: 검증**

Run:
```bash
grep -rn "MIN_MARKET_CAP\s*=" config/ core/ | head -3
```
Expected: 3e12 또는 3_0000_0000_0000

- [ ] **Step 4: Commit**

```bash
git add config/constants.py core/quant/quant_screening_service.py core/candidate_selector.py
git commit -m "$(cat <<'EOF'
feat(mom): cap_min 100억 → 3조 (mom_006676 paramset)

대형주 풀(~80종목) 한정. multiverse_min sim과 일치.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 백테스트 엔진 momentum + monthly

**Files:**
- Modify: `backtest/factor_calculator.py` (line 280-340)
- Modify: `backtest/backtester.py` (monthly 트리거 + TP/SL skip)
- Modify: `backtest/models.py` (TP/SL default)

- [ ] **Step 1: backtest factor_calculator V100 → momentum**

Edit `backtest/factor_calculator.py:280-310`. V100 점수 계산 (재무) 제거, momentum 호출:

```python
# Before (line 280-302):
fin_up_to = stock_fin[stock_fin['available_date'] <= calc_date]
if not fin_up_to.empty:
    latest_fin = fin_up_to.iloc[-1]
    ...
value_score = self._calc_value_score(...)
quality_score = self._calc_quality_score(...)
growth_score = self._calc_growth_score(...)
total_score = clamp(value_score)

# After:
from core.quant.momentum_scorer import compute_risk_adjusted_momentum

prices = stock_prices['close']
if len(prices) < 252:
    continue
score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
if not isinstance(score, (int, float)) or math.isnan(score):
    continue
value_score = 0.0
quality_score = 0.0
growth_score = 0.0
total_score = max(0.0, min(100.0, 50.0 + 25.0 * score))
```

- [ ] **Step 2: backtest factor_calculator 시총 필터**

같은 함수 내에서 시총 < 3조 종목 skip:
```python
# 종목 데이터 로드 직후
if today_row.get('market_cap', 0) < 3e12:
    continue
```

- [ ] **Step 3: backtester.py monthly 트리거**

Read `backtest/backtester.py` 의 main loop (보통 line 85-100 근처 `for date in trading_days`).

수정:
```python
# Before:
for date in trading_days:
    self._rebalance(date)
    self._check_tp_sl(date)

# After:
from utils.trading_calendar import is_first_trading_day_of_month

for date in trading_days:
    if is_first_trading_day_of_month(date):
        self._rebalance(date)
    # TP/SL 체크 비활성: tp_sl_mode=none 동일
    # (단, models.py 에서 99로 설정되어 있어 트리거 안 됨 — 이중 안전장치)
```

- [ ] **Step 4: backtest/models.py TP/SL default**

Read `backtest/models.py` 의 BacktestParams.target_profit_rate / stop_loss_rate default.

```python
# Before:
target_profit_rate: float = 0.16
stop_loss_rate: float = 0.08

# After:
target_profit_rate: float = 99.0  # mom: 비활성
stop_loss_rate: float = 99.0
```

- [ ] **Step 5: backtest 단위 동작 sanity**

가벼운 import 확인:
```bash
python -c "from backtest.backtester import Backtester; print('ok')"
```
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add backtest/factor_calculator.py backtest/backtester.py backtest/models.py
git commit -m "$(cat <<'EOF'
feat(mom): 백테스트 엔진 momentum + monthly

- backtest/factor_calculator V100 → risk-adjusted momentum
- backtest/backtester monthly 트리거 (is_first_trading_day_of_month)
- backtest/models TP/SL default 0.16/0.08 → 99/99
- 시총 < 3조 종목 skip (mom_006676 paramset)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 백테스트 실행 + sim 검증

**Files:**
- Create: `scripts/run_mom_backtest.py`
- Create: `docs/superpowers/reports/mom-strategy-backtest-result.md`

- [ ] **Step 1: 백테스트 실행 스크립트 작성**

Create `scripts/run_mom_backtest.py`:
```python
"""mom_006676 운영 백테스트 실행 + multiverse_min sim 비교.

기간: 2024-07-01 ~ 2026-03-31 (sim과 동일)
자본: 1,000만원
검증: sharpe / total_return / MDD / 2024H2 sharpe ±10%
"""
from __future__ import annotations

import json
from datetime import date

from backtest.backtester import Backtester
from backtest.models import BacktestParams


SIM_TARGET = {
    "sharpe": 1.76,
    "total_return_pct": 78.9,
    "mdd_pct": -16.6,
    "sharpe_2024H2": -0.37,
}
TOLERANCE = 0.10


def main() -> None:
    params = BacktestParams(
        start_date=date(2024, 7, 1),
        end_date=date(2026, 3, 31),
        starting_capital=10_000_000,
        portfolio_size=15,
        slippage_rate=0.0025,
        buy_cost_rate=0.00015,
        sell_cost_rate=0.00245,
        target_profit_rate=99.0,
        stop_loss_rate=99.0,
    )
    bt = Backtester(params)
    result = bt.run()
    print(json.dumps(result.to_metrics(), indent=2, default=str))

    # ±10% 게이트
    metrics = result.to_metrics()
    failed = []
    for key, target in SIM_TARGET.items():
        actual = metrics.get(key)
        if actual is None:
            failed.append(f"{key}: missing")
            continue
        if target == 0:
            ok = abs(actual) < TOLERANCE
        else:
            ok = abs(actual - target) / abs(target) <= TOLERANCE
        status = "OK" if ok else "FAIL"
        print(f"  {key}: actual={actual:.3f} target={target} [{status}]")
        if not ok:
            failed.append(key)

    n_ok = len(SIM_TARGET) - len(failed)
    print(f"\nGate: {n_ok}/{len(SIM_TARGET)} pass")
    if n_ok >= 3:
        print("✅ SUCCESS — paper trading 진입 가능")
    else:
        print("❌ FAIL — sim 격차 조사 필요")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 백테스트 실행**

Run: `python scripts/run_mom_backtest.py 2>&1 | tee backtest_output.log`
Expected: metrics + 게이트 4건 중 3+ pass

- [ ] **Step 3: 결과 리포트 작성**

Create `docs/superpowers/reports/mom-strategy-backtest-result.md`:
```markdown
# mom_006676 운영 백테스트 결과

기간: 2024-07-01 ~ 2026-03-31
자본: 1,000만원

## sim 대비 비교

| 지표 | sim 목표 | 운영 백테스트 | 격차 | ±10% 통과 |
|---|---|---|---|---|
| Sharpe | 1.76 | <fill> | <fill> | <fill> |
| Total return | +78.9% | <fill> | <fill> | <fill> |
| MDD | -16.6% | <fill> | <fill> | <fill> |
| 2024H2 sharpe | -0.37 | <fill> | <fill> | <fill> |

## Verdict

<SUCCESS / FAIL>

## 격차 원인 (FAIL 시)

- 데이터 가정 차이? slippage? cost? cap_min 적용 시점?
```

실제 수치는 Step 2 실행 후 채우기.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_mom_backtest.py docs/superpowers/reports/mom-strategy-backtest-result.md backtest_output.log
git commit -m "$(cat <<'EOF'
test(mom): 운영 백테스트 실행 + sim 비교 리포트

- scripts/run_mom_backtest.py: ±10% 게이트 자동화
- 결과 docs/superpowers/reports/mom-strategy-backtest-result.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: paper trading 준비 (계좌 정보 수령 후 진행)

**Files:**
- Modify: `config/settings.py` 또는 환경변수 (KIS APP_KEY, APP_SECRET, ACCOUNT_NO)

- [ ] **Step 1: KIS 신규 계좌 환경변수 설정**

신규 계좌 정보를 환경변수 또는 별도 config 파일로 분리:
```bash
export KIS_APP_KEY=<신규>
export KIS_APP_SECRET=<신규>
export KIS_ACCOUNT_NO=<신규>
```

또는 `config/kis_credentials_mom.json` 신규 파일 (gitignore에 추가).

- [ ] **Step 2: paper_trading 설정 (옵션)**

`trading_config.json` 에서 `paper_trading=false` (실전 — 신규 계좌가 paper 역할).

또는 `paper_trading=true` 로 두고 진짜 신규 계좌 자금 0 으로 가상 검증. 사용자 결정.

- [ ] **Step 3: 시작 자금 한정 검증**

`fund_manager` 또는 `config/constants.py` 에서 max_total_investment 를 신규 계좌 자본 (예: 200만원) 에 맞게 조정.

- [ ] **Step 4: 첫 월초 매매 모니터링**

매월 첫 거래일 09:05 에 mom_006676 가 매수 결정 후 대기. 이후 모니터링:
- 종목 선정이 sim 결과와 일치하는지
- 슬리피지 실측이 0.0025 가정과 일치하는지
- 1개월 hold 동안 별 조작 없이 진행되는지

- [ ] **Step 5: paper 결과 정리 (1-2개월 후)**

신규 리포트: `docs/superpowers/reports/mom-strategy-paper-result.md`

---

## Self-Review

### Spec coverage
- [x] section 5.1 scorer 교체 → Task 2 (신규 모듈) + Task 4 (operational 통합) + Task 8 (backtest 통합)
- [x] section 5.2 monthly 트리거 → Task 5 (operational) + Task 8 (backtest)
- [x] section 5.3 장중 모니터링 비활성 → Task 6
- [x] section 5.4 cap_min 3조 → Task 7
- [x] section 5.5 장전 분석 비활성 → Task 6
- [x] section 5.6 재무 수집 비활성 → Task 6
- [x] section 5.7 백테스트 엔진 → Task 8
- [x] section 5.8 DB 분리 → Task 1
- [x] section 5.9 로그/PID 분리 → Task 1
- [x] section 9.1 백테스트 검증 ±10% → Task 9

### 알려진 ambiguity (실행 시 확인 필요)
- Task 6 Step 2: `should_sell()` 정확한 위치는 `core/trading_stock_manager.py` 또는 `core/trading_decision_engine.py` 어느 쪽인지 grep 후 확인
- Task 7 Step 1: `MIN_MARKET_CAP` 정의 위치는 `config/constants.py`에 없을 수 있음 — grep 결과 따라 위치 결정
- Task 4 Step 4: `_calculate_scores` 호출부의 `ratio/income/balance` 인자는 호출부 검색으로 추적
- Task 8 Step 1: `backtest/factor_calculator.py:280-310` 정확한 라인은 실제 파일에서 재확인 (현재 spec 작성 시 280-302 였음)

### 보류된 결정
- paper trading 자본 규모 (집에서 결정)
- KIS 신규 계좌 정보 (집에서 받은 후)
- buy_min_score 임계값 65.0 — momentum 0-100 affine 분포에서 적절한지 백테스트 후 재조정 가능

---

## 진행 순서

T1 (DB) → T2 (scorer 모듈) → T3 (캘린더) → T4 (operational scorer) → T5 (monthly 트리거) → T6 (비활성) → T7 (cap_min) → T8 (backtest) → T9 (검증) → T10 (paper, 계좌 후)

T1~T9 까지 ~8.5h 추정, T10 은 1-2h + 1-2개월 관찰.
