#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 + Momentum 게이트/부스트 조합 멀티버스 백테스트

V100 (buy_min_score=95) 운영 베이스라인에 4축 추가:
  - buy_momentum_score_min: momentum_score 하한 게이트
  - buy_ret20d_max:         20일 누적 수익률 천장 게이트 (백분율)
  - buy_vol20d_max:         20일 변동성 상한 게이트 (일별 std, 백분율)
  - momentum_boost_alpha:   V100 통과 후보 정렬 가중

조합 6 × 5 × 5 × 5 = 750. 결과는 parquet 단독 저장.
연도별 sharpe (2023/2024/2025/2026) 동시 기록.

사용법:
    python scripts/v100_momentum_combo_multiverse.py
    python scripts/v100_momentum_combo_multiverse.py --output results/v100_momentum_combo.parquet
    python scripts/v100_momentum_combo_multiverse.py --quick   # smoke test (8조합)
"""
import sys
import time
import argparse
import itertools
from pathlib import Path
from typing import Optional

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


START_DATE = "2023-01-01"
END_DATE = "2026-02-28"
YEARS = ["2023", "2024", "2025", "2026"]

# 운영 baseline 고정값 (BUY_RET5D_MAX=17 포함)
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

# 4축 그리드 (None = 게이트 비활성)
SWEEP = {
    'buy_momentum_score_min': [None, 30.0, 40.0, 50.0, 60.0, 70.0],   # 6
    'buy_ret20d_max':         [None, 30.0, 50.0, 80.0, 120.0],         # 5
    'buy_vol20d_max':         [None, 3.0, 4.0, 5.0, 6.0],              # 5
    'momentum_boost_alpha':   [0.0, 0.05, 0.1, 0.2, 0.3],              # 5
}

# 빠른 smoke test용 축소 그리드 (8조합)
QUICK_SWEEP = {
    'buy_momentum_score_min': [None, 50.0],
    'buy_ret20d_max':         [None, 80.0],
    'buy_vol20d_max':         [None],
    'momentum_boost_alpha':   [0.0, 0.1],
}


def yearly_sharpe(snapshots, year_prefix):
    subset = [s for s in snapshots if s.date.startswith(year_prefix)]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def run_one(loader, trading_days, combo, start_norm, end_norm):
    merged = {**BASE, **combo}
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
    yearly = {y: yearly_sharpe(bt.daily_snapshots, y) for y in YEARS}

    row = dict(combo)
    row.update({
        'sharpe': float(result.sharpe_ratio),
        'total_return': float(result.total_return),
        'mdd': float(result.max_drawdown),
        'win_rate': float(result.win_rate),
        'pf': float(result.profit_factor),
        'trades': int(result.total_trades),
        'sharpe_2023': yearly['2023'],
        'sharpe_2024': yearly['2024'],
        'sharpe_2025': yearly['2025'],
        'sharpe_2026': yearly['2026'],
    })
    return row


def expand(grid):
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=START_DATE)
    ap.add_argument('--end', default=END_DATE)
    ap.add_argument('--output', default='results/v100_momentum_combo.parquet')
    ap.add_argument('--quick', action='store_true', help='smoke test (8조합)')
    ap.add_argument('--checkpoint-every', type=int, default=50,
                    help='N개 조합마다 parquet 저장 (재시작 안전)')
    args = ap.parse_args()

    grid = QUICK_SWEEP if args.quick else SWEEP
    combos = list(expand(grid))
    total = len(combos)

    print("=" * 90)
    print(f"  V100 + Momentum 조합 멀티버스 ({'QUICK' if args.quick else 'FULL'})")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  조합 수: {total}")
    print(f"  baseline: V100 buy_min_score=95, ret5d ∈ [-3, 17]")
    print(f"  output:   {args.output}")
    print("=" * 90)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(args.start)
    end_norm = loader._normalize_date(args.end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    t0 = time.time()
    for i, combo in enumerate(combos, 1):
        ts = time.time()
        try:
            row = run_one(loader, trading_days, combo, start_norm, end_norm)
        except Exception as e:
            print(f"  [{i}/{total}] FAILED {combo}: {e}")
            continue
        elapsed = time.time() - ts
        rows.append(row)

        if i <= 5 or i % 25 == 0 or i == total:
            label = (f"M={combo['buy_momentum_score_min']!s:>5} "
                     f"R={combo['buy_ret20d_max']!s:>5} "
                     f"V={combo['buy_vol20d_max']!s:>4} "
                     f"α={combo['momentum_boost_alpha']:.2f}")
            print(f"  [{i:>3}/{total}] {label} → "
                  f"sh {row['sharpe']:>5.2f} ret {row['total_return']:>+7.1%} "
                  f"mdd {row['mdd']:>5.1%} wr {row['win_rate']:>4.0%} "
                  f"trd {row['trades']:>4d} ({elapsed:.2f}s)")

        if i % args.checkpoint_every == 0:
            df = pd.DataFrame(rows)
            df.to_parquet(output_path, index=False)
            eta = (time.time() - t0) / i * (total - i)
            print(f"  ── checkpoint @ {i} (eta {eta:.0f}s) → {output_path}")

    df = pd.DataFrame(rows)
    df.to_parquet(output_path, index=False)
    total_elapsed = time.time() - t0

    print(f"\n총 소요: {total_elapsed:.1f}초 ({total_elapsed / total:.2f}초/조합)")
    print(f"결과 저장: {output_path} ({len(df)}행)")

    # 베이스라인 (모두 None/0) 출력
    base_mask = (
        df['buy_momentum_score_min'].isna()
        & df['buy_ret20d_max'].isna()
        & df['buy_vol20d_max'].isna()
        & (df['momentum_boost_alpha'] == 0.0)
    )
    if base_mask.any():
        b = df[base_mask].iloc[0]
        print(f"\nBASELINE (모두 None/0):")
        print(f"  sharpe={b['sharpe']:.3f} return={b['total_return']:+.1%} "
              f"mdd={b['mdd']:.1%} wr={b['win_rate']:.0%} trades={int(b['trades'])}")
        yearly = [round(b[f'sharpe_{y}'], 2) for y in YEARS]
        print(f"  yearly={yearly}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
