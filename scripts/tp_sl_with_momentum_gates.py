#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M=30 + R=30 게이트 적용 상태에서 TP/SL 멀티버스
— 게이트와 TP/SL의 결합 효과 검증
"""
import sys, io, time
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
    ("4-5월", "2026-04-01", "2026-05-06"),
    ("전체",  "2023-01-01", "2026-05-06"),
]

TP_VALUES = [0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.18, 0.20, 0.25]
SL_VALUES = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]

# 두 케이스 비교: 게이트 OFF vs M=30+R=30
GATE_CASES = [
    ("OFF",        dict(buy_momentum_score_min=None, buy_ret20d_max=None)),
    ("M=30+R=30",  dict(buy_momentum_score_min=30.0, buy_ret20d_max=30.0)),
]

BASE = dict(
    initial_capital=50_000_000, portfolio_size=10,
    hard_stop_score=65.0, soft_stop_score=67.0, soft_stop_rank=30,
    safe_score=75.0, safe_rank=25,
    min_hold_days=0, max_hold_days=0,
    buy_min_score=95.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015, sell_cost_rate=0.00245, slippage_rate=0.0025,
    regime_filter_enabled=False,
    buy_ret5d_min=-3.0, buy_ret5d_max=17.0,
)


def run_one(loader, trading_days, tp, sl, gate_kwargs, start_norm, end_norm):
    merged = {**BASE, **gate_kwargs, 'target_profit_rate': tp, 'stop_loss_rate': sl}
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
        'sharpe': float(result.sharpe_ratio),
        'total_return': float(result.total_return),
        'mdd': float(result.max_drawdown),
        'trades': int(result.total_trades),
    }


def run_window(name, start, end):
    print(f"\n{'=' * 100}")
    print(f"  윈도우: {name} ({start} ~ {end})")
    print('=' * 100)

    loader = Backtester(params=BacktestParams(**BASE, target_profit_rate=0.12, stop_loss_rate=0.06))
    start_norm = loader._normalize_date(start)
    end_norm = loader._normalize_date(end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    rows = []
    for tp in TP_VALUES:
        for sl in SL_VALUES:
            for gate_name, gate_kwargs in GATE_CASES:
                r = run_one(loader, trading_days, tp, sl, gate_kwargs, start_norm, end_norm)
                r.update({'tp': tp, 'sl': sl, 'gate': gate_name, 'window': name})
                rows.append(r)
    df = pd.DataFrame(rows)

    # 게이트 OFF vs M=30+R=30 비교 표 (현행 TP12/SL6 기준)
    cur_off = df[(df['tp'] == 0.12) & (df['sl'] == 0.06) & (df['gate'] == 'OFF')].iloc[0]
    cur_gate = df[(df['tp'] == 0.12) & (df['sl'] == 0.06) & (df['gate'] == 'M=30+R=30')].iloc[0]
    print(f"\n  현행 TP12/SL6:")
    print(f"    게이트 OFF       : sharpe {cur_off['sharpe']:>+5.2f}  ret {cur_off['total_return']:>+6.1%}  trd {int(cur_off['trades']):>4d}")
    print(f"    M=30+R=30        : sharpe {cur_gate['sharpe']:>+5.2f}  ret {cur_gate['total_return']:>+6.1%}  trd {int(cur_gate['trades']):>4d}")
    print(f"    Δ                : sharpe {cur_gate['sharpe']-cur_off['sharpe']:>+5.2f}  ret {cur_gate['total_return']-cur_off['total_return']:>+6.1%}")

    # Top 5 게이트별
    print(f"\n  Top 5 by sharpe — 게이트 OFF")
    for _, r in df[df['gate'] == 'OFF'].nlargest(5, 'sharpe').iterrows():
        marker = " ★ 현행 TP/SL" if (r['tp'] == 0.12 and r['sl'] == 0.06) else ""
        print(f"    TP={r['tp']:.2f} SL={r['sl']:.2f} → sharpe {r['sharpe']:>+5.2f}  ret {r['total_return']:>+6.1%}  trd {int(r['trades']):>4d}{marker}")
    print(f"\n  Top 5 by sharpe — M=30+R=30 적용")
    for _, r in df[df['gate'] == 'M=30+R=30'].nlargest(5, 'sharpe').iterrows():
        marker = " ★ 현행 TP/SL" if (r['tp'] == 0.12 and r['sl'] == 0.06) else ""
        print(f"    TP={r['tp']:.2f} SL={r['sl']:.2f} → sharpe {r['sharpe']:>+5.2f}  ret {r['total_return']:>+6.1%}  trd {int(r['trades']):>4d}{marker}")

    return df


def main():
    print("=" * 100)
    print(f"  TP/SL × 모멘텀 게이트 결합 분석")
    print('=' * 100)

    dfs = []
    for name, start, end in WINDOWS:
        df = run_window(name, start, end)
        dfs.append(df)

    all_df = pd.concat(dfs, ignore_index=True)
    all_df.to_parquet('results/tp_sl_with_momentum_gates.parquet', index=False)
    print(f"\n결과 저장: results/tp_sl_with_momentum_gates.parquet ({len(all_df)}행)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
