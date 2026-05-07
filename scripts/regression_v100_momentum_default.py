#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
회귀 검증 — V100 모멘텀 게이트/부스트 신규 파라미터의 기본값(None/0)이
기존 baseline과 동일한 결과를 내는지 확인.

조건1: 기존 코드 경로 (신규 파라미터 사용 안 함)
조건2: 신규 파라미터 명시 None/0 (기본값과 동일)
두 결과가 정확히 일치해야 게이트 코드가 baseline에 영향을 주지 않음을 증명.
"""
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


START_DATE = "2023-01-01"
END_DATE = "2026-02-28"

BASE = dict(
    initial_capital=50_000_000,
    portfolio_size=10,
    target_profit_rate=0.12,
    stop_loss_rate=0.06,
    hard_stop_score=65.0,
    soft_stop_score=67.0,
    soft_stop_rank=30,
    safe_score=75.0,
    safe_rank=25,
    min_hold_days=0,
    max_hold_days=0,
    buy_min_score=95.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015,
    sell_cost_rate=0.00245,
    slippage_rate=0.0025,
    regime_filter_enabled=False,
    buy_ret5d_min=-3.0,
    buy_ret5d_max=17.0,
)


def run(loader, trading_days, extra, start_norm, end_norm):
    merged = {**BASE, **extra}
    params = BacktestParams(**merged)
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = loader.daily_prices_cache
    bt.portfolio_cache = loader.portfolio_cache
    bt.factors_cache = loader.factors_cache

    prev_total_value = params.initial_capital
    for date in trading_days:
        bt._today_stop_profit_sold = set()
        bt._today_rebalancing_bought = set()
        bt._check_stop_profit_loss(date)
        bt._execute_rebalancing(date)
        total_value = bt._calculate_total_value(date)
        daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
        cumulative_return = (total_value - params.initial_capital) / params.initial_capital
        snapshot = DailySnapshot(
            date=date, capital=bt.capital,
            positions_value=total_value - bt.capital,
            total_value=total_value, position_count=len(bt.positions),
            daily_return=daily_return, cumulative_return=cumulative_return
        )
        bt.daily_snapshots.append(snapshot)
        prev_total_value = total_value

    bt._close_all_positions(trading_days[-1])
    result = bt._create_result(start_norm, end_norm, len(trading_days))
    return {
        'sharpe': round(result.sharpe_ratio, 6),
        'total_return': round(result.total_return, 6),
        'mdd': round(result.max_drawdown, 6),
        'win_rate': round(result.win_rate, 6),
        'trades': result.total_trades,
    }


def main():
    print("=" * 80)
    print("  회귀 검증: V100 모멘텀 신규 파라미터 기본값 = baseline 확인")
    print("=" * 80)

    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    print("Run A: 신규 파라미터 미지정 (BacktestParams 기본값)")
    t0 = time.time()
    a = run(loader, trading_days, {}, start_norm, end_norm)
    print(f"  → {a}  ({time.time() - t0:.1f}s)")

    print("\nRun B: 신규 파라미터 명시 None/0.0")
    t0 = time.time()
    b = run(loader, trading_days, {
        'buy_momentum_score_min': None,
        'buy_ret20d_max': None,
        'buy_vol20d_max': None,
        'momentum_boost_alpha': 0.0,
    }, start_norm, end_norm)
    print(f"  → {b}  ({time.time() - t0:.1f}s)")

    print("\n" + "=" * 80)
    if a == b:
        print("  [PASS] A == B, 신규 파라미터 기본값이 baseline에 영향 없음")
        return 0
    print("  [FAIL] A != B, 게이트 코드 기본값 처리에 버그")
    print(f"     diff: {[(k, a[k], b[k]) for k in a if a[k] != b[k]]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
