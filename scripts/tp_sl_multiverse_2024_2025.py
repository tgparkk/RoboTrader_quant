#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 + TP/SL 멀티버스 — 2024년만 / 2025년만
"""
import sys, io, time
from itertools import product
from pathlib import Path
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot

WINDOWS = [
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
]

TP_VALUES = [0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.18, 0.20, 0.25]
SL_VALUES = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]

BASE = dict(
    initial_capital=50_000_000,
    portfolio_size=10,
    hard_stop_score=65.0, soft_stop_score=67.0, soft_stop_rank=30,
    safe_score=75.0, safe_rank=25,
    min_hold_days=0, max_hold_days=0,
    buy_min_score=95.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015, sell_cost_rate=0.00245, slippage_rate=0.0025,
    regime_filter_enabled=False,
    buy_ret5d_min=-3.0, buy_ret5d_max=17.0,
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


def run_window(name, start, end):
    print(f"\n{'=' * 90}")
    print(f"  {name}년 ({start} ~ {end})")
    print('=' * 90)

    print("데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE, target_profit_rate=0.12, stop_loss_rate=0.06))
    start_norm = loader._normalize_date(start)
    end_norm = loader._normalize_date(end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일")

    rows = []
    t0 = time.time()
    for tp in TP_VALUES:
        for sl in SL_VALUES:
            r = run_one(loader, trading_days, tp, sl, start_norm, end_norm)
            r['window'] = name
            rows.append(r)
    print(f"멀티버스: {time.time() - t0:.1f}초 ({len(rows)} 조합)")

    df = pd.DataFrame(rows)

    print(f"\n  Top 15 by sharpe ({name}년)")
    print("  " + "-" * 88)
    print(f"  {'TP':>5} {'SL':>5} | {'sharpe':>7} {'return':>8} {'MDD':>6} {'wr':>4} {'PF':>5} {'trd':>5} | 비고")
    top = df.sort_values('sharpe', ascending=False).head(15)
    for _, r in top.iterrows():
        marker = " <- 현행" if (r['tp'] == 0.12 and r['sl'] == 0.06) else ""
        print(f"  {r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{r['sharpe']:>+7.2f} {r['total_return']:>+8.1%} {r['mdd']:>6.1%} "
              f"{r['win_rate']:>4.0%} {r['pf']:>5.2f} {int(r['trades']):>5d} |{marker}")

    cur = df[(df['tp'] == 0.12) & (df['sl'] == 0.06)]
    if len(cur) > 0:
        c = cur.iloc[0]
        rank = (df['sharpe'] > c['sharpe']).sum() + 1
        print(f"\n  현행 TP12/SL6: rank {rank}/{len(df)}, "
              f"sharpe {c['sharpe']:+.2f}, return {c['total_return']:+.1%}, "
              f"MDD {c['mdd']:.1%}, trd {int(c['trades'])}")

    return df


def main():
    print("=" * 90)
    print(f"  V100 + TP/SL — 2024년 / 2025년 (각 1년)")
    print(f"  TP: {[f'{v:.0%}' for v in TP_VALUES]}")
    print(f"  SL: {[f'{v:.0%}' for v in SL_VALUES]}")
    print('=' * 90)

    dfs = [run_window(name, start, end) for name, start, end in WINDOWS]
    all_df = pd.concat(dfs, ignore_index=True)
    all_df.to_parquet('results/tp_sl_2024_2025.parquet', index=False)

    # 통합 비교
    print("\n" + "=" * 90)
    print("  2024 + 2025 통합 (min sharpe 순 Top 15)")
    print("=" * 90)
    pivot = all_df.pivot_table(index=['tp', 'sl'], columns='window', values='sharpe')
    pivot = pivot[['2024', '2025']]
    pivot['avg'] = pivot.mean(axis=1)
    pivot['min'] = pivot.min(axis=1)
    pivot = pivot.sort_values('min', ascending=False)

    print(f"\n  {'TP':>5} {'SL':>5} | {'2024':>7} {'2025':>7} | {'avg':>7} {'min':>7}")
    print("  " + "-" * 56)
    for (tp, sl), row in pivot.head(15).iterrows():
        marker = " <- 현행" if (tp == 0.12 and sl == 0.06) else ""
        print(f"  {tp:>5.2f} {sl:>5.2f} | "
              f"{row['2024']:>+7.2f} {row['2025']:>+7.2f} | "
              f"{row['avg']:>+7.2f} {row['min']:>+7.2f}{marker}")

    if (0.12, 0.06) in pivot.index:
        c = pivot.loc[(0.12, 0.06)]
        rank = (pivot['min'] > c['min']).sum() + 1
        print(f"\n  현행 TP12/SL6 (min 기준): rank {rank}/{len(pivot)}, "
              f"min={c['min']:+.2f}, avg={c['avg']:+.2f}")
        print(f"  yearly: 2024={c['2024']:+.2f}, 2025={c['2025']:+.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
