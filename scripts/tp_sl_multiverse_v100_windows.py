#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 운영 베이스에서 TP/SL 멀티버스 (최근 2년/1년/3달 3개 윈도우)

BASE: V100 buy_min_score=95, ret5d ∈ [-3, +17] (현행 운영)
sweep: TP 9개 × SL 8개 = 72 조합
window: 3개 (각 윈도우에서 동일 grid)

사용법:
    python scripts/tp_sl_multiverse_v100_windows.py
    python scripts/tp_sl_multiverse_v100_windows.py --output results/tp_sl_v100_windows.parquet
"""
import sys
import io
import time
import argparse
from itertools import product
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


# 데이터 종료일 (backtest DB 기준 5/6까지)
DATA_END = "2026-05-06"

# 윈도우 정의 (오늘 = 2026-05-07 기준)
WINDOWS = [
    ("2년",  "2024-05-07", DATA_END),
    ("1년",  "2025-05-07", DATA_END),
    ("3달",  "2026-02-07", DATA_END),
]

# TP/SL 그리드
TP_VALUES = [0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.18, 0.20, 0.25]   # 9개
SL_VALUES = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]          # 8개

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


def run_window(name, start, end):
    print(f"\n{'=' * 90}")
    print(f"  윈도우: 최근 {name}  ({start} ~ {end})")
    print(f"{'=' * 90}")

    print("데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE, target_profit_rate=0.12, stop_loss_rate=0.06))
    start_norm = loader._normalize_date(start)
    end_norm = loader._normalize_date(end)
    trading_days_full = loader._get_trading_days(start_norm, end_norm)
    # 2026-03 제외 (3월만 구멍, Feb + Apr-May 적용)
    trading_days = [d for d in trading_days_full
                    if not (d.startswith('2026-03') or d.startswith('20260301')
                            or d.startswith('202603'))]
    skipped = len(trading_days_full) - len(trading_days)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일 "
          f"(2026-03 {skipped}일 제외)")

    rows = []
    t0 = time.time()
    for tp in TP_VALUES:
        for sl in SL_VALUES:
            r = run_one(loader, trading_days, tp, sl, start_norm, end_norm)
            r['window'] = name
            rows.append(r)
    print(f"멀티버스 실행: {time.time() - t0:.1f}초 ({len(rows)} 조합)")

    df = pd.DataFrame(rows)

    # Top 10 by sharpe
    print(f"\n  Top 10 by sharpe (최근 {name})")
    print("  " + "-" * 88)
    print(f"  {'TP':>5} {'SL':>5} | {'sharpe':>7} {'return':>8} {'MDD':>6} {'wr':>4} {'PF':>5} {'trd':>4} | 비고")
    top10 = df.sort_values('sharpe', ascending=False).head(10)
    for _, r in top10.iterrows():
        marker = " <- 현행" if (r['tp'] == 0.12 and r['sl'] == 0.06) else ""
        print(f"  {r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{r['sharpe']:>+7.2f} {r['total_return']:>+8.1%} {r['mdd']:>6.1%} "
              f"{r['win_rate']:>4.0%} {r['pf']:>5.2f} {int(r['trades']):>4d} |{marker}")

    # 현행 0.12/0.06 위치
    cur = df[(df['tp'] == 0.12) & (df['sl'] == 0.06)]
    if len(cur) > 0:
        cur_row = cur.iloc[0]
        rank = (df['sharpe'] > cur_row['sharpe']).sum() + 1
        print(f"\n  현행 TP12/SL6: rank {rank}/{len(df)}, sharpe {cur_row['sharpe']:+.2f}, "
              f"trades {int(cur_row['trades'])}")

    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='results/tp_sl_v100_windows_no_mar2026.parquet')
    args = ap.parse_args()

    print("=" * 90)
    print(f"  V100 + TP/SL 멀티버스 — 윈도우 3개 (2026-03 제외)")
    print(f"  BASE: V100 buy_min_score=95, ret5d ∈ [-3, +17], slippage 0.25%")
    print(f"  TP: {[f'{v:.0%}' for v in TP_VALUES]}")
    print(f"  SL: {[f'{v:.0%}' for v in SL_VALUES]}")
    print(f"  조합: {len(TP_VALUES) * len(SL_VALUES)} × {len(WINDOWS)} 윈도우 = "
          f"{len(TP_VALUES) * len(SL_VALUES) * len(WINDOWS)} backtests")
    print("=" * 90)

    all_rows = []
    for name, start, end in WINDOWS:
        df = run_window(name, start, end)
        all_rows.append(df)

    all_df = pd.concat(all_rows, ignore_index=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_parquet(output_path, index=False)
    print(f"\n결과 저장: {output_path} ({len(all_df)}행)")

    # 최종 요약 — 3개 윈도우에서 모두 좋은 TP/SL 찾기
    print("\n" + "=" * 90)
    print("  3개 윈도우 통합 분석 — 일관성 있는 TP/SL")
    print("=" * 90)
    pivot = all_df.pivot_table(index=['tp', 'sl'], columns='window', values='sharpe')
    pivot = pivot[['2년', '1년', '3달']]
    pivot['avg'] = pivot.mean(axis=1)
    pivot['min'] = pivot.min(axis=1)
    pivot = pivot.sort_values('min', ascending=False)

    print(f"\n  Top 15 by min(sharpe) — 3개 윈도우 모두에서 안정적인 조합")
    print(f"  {'TP':>5} {'SL':>5} | {'2년':>6} {'1년':>6} {'3달':>6} | {'avg':>6} {'min':>6}")
    print("  " + "-" * 60)
    for (tp, sl), row in pivot.head(15).iterrows():
        marker = " <- 현행" if (tp == 0.12 and sl == 0.06) else ""
        print(f"  {tp:>5.2f} {sl:>5.2f} | "
              f"{row['2년']:>+6.2f} {row['1년']:>+6.2f} {row['3달']:>+6.2f} | "
              f"{row['avg']:>+6.2f} {row['min']:>+6.2f}{marker}")

    # 현행 위치
    if (0.12, 0.06) in pivot.index:
        cur = pivot.loc[(0.12, 0.06)]
        rank = (pivot['min'] > cur['min']).sum() + 1
        print(f"\n  현행 TP12/SL6 (min 기준): rank {rank}/{len(pivot)}, "
              f"min={cur['min']:+.2f}, avg={cur['avg']:+.2f}")
        print(f"  yearly: 2년={cur['2년']:+.2f}, 1년={cur['1년']:+.2f}, 3달={cur['3달']:+.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
