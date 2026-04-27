"""Risk-adjusted momentum scorer.

multiverse_min `strategy_v2/multiverse_min/indicators.py` 의 `mom_rskip_lb_1` 패널과
식 일치. 운영 + 백테스트 모듈에서 공통 사용.

Canonical 식 (indicators.py:209-219):
    mom_lb_skip[t] = close[t - skip*21] / close[t - (lookback+skip)*21] - 1
    vol_20[t]      = pct_change(close).rolling(20, min_periods=20).std()[t]
                     # ⚠️ 비-연환산 (sqrt(252) 곱 안 함)
    score[t]       = mom_lb_skip[t] / vol_20[t]

vol_20 은 마지막 20일 분포 기반이며 lookback 윈도우와 무관.
"""
from __future__ import annotations

import math

import pandas as pd


TRADING_DAYS_PER_MONTH = 21
VOL_WINDOW = 20


def compute_risk_adjusted_momentum(
    prices: pd.Series,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> float:
    """Risk-adjusted momentum 점수 (last index 기준).

    Args:
        prices: 일봉 종가 시계열 (오름차순 날짜 인덱스).
            최소 (lookback + skip) * 21 + 1 영업일 필요 (mom 정의 조건).
        lookback_months: 모멘텀 측정 기간 (개월).
        skip_months: 직전 제외 구간 (개월).

    Returns:
        float 점수. 이력 부족, vol_20 정의 불가, p_old<=0 → NaN.
        flat prices (raw_return=0 + vol_20=0) → 0.0.
    """
    lookback_days = lookback_months * TRADING_DAYS_PER_MONTH
    skip_days = skip_months * TRADING_DAYS_PER_MONTH
    required_history = lookback_days + skip_days + 1

    if len(prices) < required_history:
        return float("nan")

    p_recent = float(prices.iloc[-1 - skip_days])
    p_old = float(prices.iloc[-1 - skip_days - lookback_days])
    if p_old <= 0:
        return float("nan")

    raw_return = p_recent / p_old - 1.0

    # vol_20: 마지막 인덱스의 20일 rolling std of pct_change (multiverse_min과 동일)
    if len(prices) < VOL_WINDOW + 1:
        return float("nan")
    vol_20 = float(
        prices.pct_change().rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std().iloc[-1]
    )
    if math.isnan(vol_20):
        return float("nan")
    if vol_20 <= 0:
        return 0.0 if math.isclose(raw_return, 0.0) else float("nan")

    return raw_return / vol_20
