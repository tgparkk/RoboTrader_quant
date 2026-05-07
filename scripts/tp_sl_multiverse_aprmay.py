#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 + TP/SL 멀티버스 — 2026년 4월~5월만 (March 사고 이후 회복 구간)
"""
import sys
import io
import time
from itertools import product
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


START = "2026-04-01"
END = "2026-05-06"

TP_VALUES = [0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.18, 0.20, 0.25]
SL_VALUES = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]

BASE = dict(
    initial_capital=50_000_000,
    portfolio_size=10,
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


def run_one(loader, trading_days, tp, sl, start_norm, end_norm):
    merged = {**BASE, 'target_profit_rate': tp, 'stop_loss_rate': sl}
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
        'tp': tp, 'sl': sl,
        'sharpe': float(result.sharpe_ratio),
        'total_return': float(result.total_return),
        'mdd': float(result.max_drawdown),
        'win_rate': float(result.win_rate),
        'pf': float(result.profit_factor),
        'trades': int(result.total_trades),
    }


def main():
    print("=" * 90)
    print(f"  V100 + TP/SL — 4월~5월만 ({START} ~ {END})")
    print(f"  TP: {[f'{v:.0%}' for v in TP_VALUES]}")
    print(f"  SL: {[f'{v:.0%}' for v in SL_VALUES]}")
    print("=" * 90)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE, target_profit_rate=0.12, stop_loss_rate=0.06))
    start_norm = loader._normalize_date(START)
    end_norm = loader._normalize_date(END)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일")

    rows = []
    t0 = time.time()
    for tp in TP_VALUES:
        for sl in SL_VALUES:
            r = run_one(loader, trading_days, tp, sl, start_norm, end_norm)
            rows.append(r)
    print(f"멀티버스 실행: {time.time() - t0:.1f}초 ({len(rows)} 조합)")

    df = pd.DataFrame(rows)
    df.to_parquet('results/tp_sl_aprmay.parquet', index=False)

    # Top 15 by sharpe
    print(f"\n  Top 15 by sharpe (4월~5월)")
    print("  " + "-" * 88)
    print(f"  {'TP':>5} {'SL':>5} | {'sharpe':>7} {'return':>8} {'MDD':>6} {'wr':>4} {'PF':>5} {'trd':>4} | 비고")
    top = df.sort_values('sharpe', ascending=False).head(15)
    for _, r in top.iterrows():
        marker = " <- 현행" if (r['tp'] == 0.12 and r['sl'] == 0.06) else ""
        print(f"  {r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{r['sharpe']:>+7.2f} {r['total_return']:>+8.1%} {r['mdd']:>6.1%} "
              f"{r['win_rate']:>4.0%} {r['pf']:>5.2f} {int(r['trades']):>4d} |{marker}")

    # 현행 위치
    cur = df[(df['tp'] == 0.12) & (df['sl'] == 0.06)]
    if len(cur) > 0:
        cur_row = cur.iloc[0]
        rank = (df['sharpe'] > cur_row['sharpe']).sum() + 1
        print(f"\n  현행 TP12/SL6: rank {rank}/{len(df)}, sharpe {cur_row['sharpe']:+.2f}, "
              f"trades {int(cur_row['trades'])}, return {cur_row['total_return']:+.1%}")

    # SL별 평균 (TP가중)
    print(f"\n  SL별 평균 sharpe (TP 9개 평균)")
    print(f"  {'SL':>5} | {'avg':>+7} {'min':>+7} {'max':>+7} | {'avg ret':>+8} | {'avg trd':>+8}")
    sl_pivot = df.groupby('sl').agg({
        'sharpe': ['mean', 'min', 'max'],
        'total_return': 'mean',
        'trades': 'mean',
    })
    for sl, row in sl_pivot.iterrows():
        print(f"  {sl:>5.2f} | "
              f"{row[('sharpe', 'mean')]:>+7.2f} {row[('sharpe', 'min')]:>+7.2f} "
              f"{row[('sharpe', 'max')]:>+7.2f} | "
              f"{row[('total_return', 'mean')]:>+8.1%} | "
              f"{row[('trades', 'mean')]:>8.1f}")

    # TP별 평균
    print(f"\n  TP별 평균 sharpe (SL 8개 평균)")
    print(f"  {'TP':>5} | {'avg':>+7} {'min':>+7} {'max':>+7} | {'avg ret':>+8} | {'avg trd':>+8}")
    tp_pivot = df.groupby('tp').agg({
        'sharpe': ['mean', 'min', 'max'],
        'total_return': 'mean',
        'trades': 'mean',
    })
    for tp, row in tp_pivot.iterrows():
        print(f"  {tp:>5.2f} | "
              f"{row[('sharpe', 'mean')]:>+7.2f} {row[('sharpe', 'min')]:>+7.2f} "
              f"{row[('sharpe', 'max')]:>+7.2f} | "
              f"{row[('total_return', 'mean')]:>+8.1%} | "
              f"{row[('trades', 'mean')]:>8.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
