"""Momentum scorer 단위 테스트 (multiverse_min 식 일치 검증).

Canonical 식 (multiverse_min/indicators.py:209-219):
    mom_rskip[t] = (close[t-skip*21] / close[t-(lookback+skip)*21] - 1)
                   / pct_change(close).rolling(20).std()[t]

lookback=12, skip=1 기준 최소 이력: 12*21 + 1*21 + 1 = 274 영업일.
"""
import math

import numpy as np
import pandas as pd

from core.quant.momentum_scorer import compute_risk_adjusted_momentum


# 캐노니컬 식의 (lb=12, skip=1) 최소 길이는 274. 마진 6 추가.
_N = 280


def _bdays(n: int = _N) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=n, freq="B")


def test_returns_zero_for_flat_prices():
    """가격 변화 0 → raw_return=0, vol_20=0 → 0.0 (정의)."""
    prices = pd.Series([100.0] * _N, index=_bdays())
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert math.isclose(score, 0.0, abs_tol=1e-12)


def test_positive_for_uptrend():
    """단조 상승 → 양수 점수."""
    prices = pd.Series(np.linspace(100.0, 200.0, _N), index=_bdays())
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert score > 0


def test_skip_excludes_recent_month():
    """최근 21일 폭등이 있어도 skip=1이면 mom 측정에서 그 구간 제외 → score 낮음.

    vol_20 은 동일(마지막 20일)이므로 분모 동일, 분자만 차이.
    """
    n = _N
    calm = list(np.linspace(100.0, 110.0, n - 21))   # 캄 구간
    spike = list(np.linspace(110.0, 300.0, 21))      # 직전 1개월 폭등
    series = pd.Series(calm + spike, index=_bdays(n))
    score_skip1 = compute_risk_adjusted_momentum(series, lookback_months=12, skip_months=1)
    score_skip0 = compute_risk_adjusted_momentum(series, lookback_months=12, skip_months=0)
    assert not math.isnan(score_skip0) and not math.isnan(score_skip1)
    assert score_skip1 < score_skip0


def test_insufficient_history_returns_nan():
    """이력이 (lookback+skip)*21+1 미만 → NaN."""
    prices = pd.Series([100.0] * 50, index=pd.date_range("2025-01-01", periods=50, freq="B"))
    score = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert math.isnan(score)


def test_matches_multiverse_min_formula():
    """canonical 식을 직접 재계산하여 1e-9 이내 일치 검증."""
    rng = np.random.default_rng(seed=42)
    # geometric Brownian-ish series, strictly positive
    log_rets = rng.normal(0.0005, 0.02, size=_N)
    prices = pd.Series(100.0 * np.exp(np.cumsum(log_rets)), index=_bdays())

    # multiverse_min canonical replication
    lb_days, skip_days = 12 * 21, 1 * 21
    p_recent = prices.iloc[-1 - skip_days]
    p_old = prices.iloc[-1 - skip_days - lb_days]
    raw_return = p_recent / p_old - 1.0
    vol_20 = prices.pct_change().rolling(20, min_periods=20).std().iloc[-1]
    expected = raw_return / vol_20

    actual = compute_risk_adjusted_momentum(prices, lookback_months=12, skip_months=1)
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
