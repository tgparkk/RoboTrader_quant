#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BUY_RET20D_MAX 단일축 정밀 멀티버스

20일 누적 수익률 상한 가드. 058430 5/6 사고 (ret_20d=+61%) 회피 + V100 모멘텀 천장.

조합 멀티버스(750)에서 ret20d_max=30이 sharpe +0.25 개선 + 058430 5/6 차단으로
가장 강력한 단일 게이트로 발견 → 절벽/안정성 검증을 위한 정밀 sweep.

baseline: V100 buy_min_score=95, buy_ret5d ∈ [-3, 17]
sweep: None, 20, 22, 25, 28, 30, 32, 35, 40, 50, 60, 80
"""
import sys
import io
import time
import argparse
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


START_DATE = "2023-01-01"
END_DATE = "2026-02-28"
YEARS = ["2023", "2024", "2025", "2026"]

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

# 정밀 sweep — 30 주변 ±10%, 그리고 멀리 50/60/80도 비교용
SWEEP_VALUES = [None, 20.0, 22.0, 25.0, 28.0, 30.0, 32.0, 35.0, 40.0, 50.0, 60.0, 80.0]


def yearly_sharpe(snapshots, year_prefix):
    subset = [s for s in snapshots if s.date.startswith(year_prefix)]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def run_one(loader, trading_days, ret20d_max, start_norm, end_norm):
    merged = {**BASE, 'buy_ret20d_max': ret20d_max}
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

    return {
        'buy_ret20d_max': ret20d_max,
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
        'sharpe_2023': yearly['2023'],
        'sharpe_2024': yearly['2024'],
        'sharpe_2025': yearly['2025'],
        'sharpe_2026': yearly['2026'],
    }


def fmt(v, dp=2):
    if v != v:
        return "  n/a"
    return f"{v:>+5.{dp}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=START_DATE)
    ap.add_argument('--end', default=END_DATE)
    args = ap.parse_args()

    print("=" * 105)
    print("  BUY_RET20D_MAX 정밀 sweep (20일 누적 수익률 상한, 백분율 단위)")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  baseline: V100 buy_min_score=95, ret5d ∈ [-3, 17]")
    print("=" * 105)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(args.start)
    end_norm = loader._normalize_date(args.end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    rows = []
    t0 = time.time()
    for i, v in enumerate(SWEEP_VALUES, 1):
        ts = time.time()
        r = run_one(loader, trading_days, v, start_norm, end_norm)
        elapsed = time.time() - ts
        label = "OFF" if v is None else f"{v:.0f}%"
        marker = " <- baseline" if v is None else ""
        print(f"  [{i:>2}/{len(SWEEP_VALUES)}] MAX={label:>5} -> "
              f"sh {r['sharpe']:>+5.2f}  ret {r['total_return']:>+6.1%}  "
              f"MDD {r['mdd']:>5.1%}  wr {r['win_rate']:>4.0%}  "
              f"trd {r['trades']:>4d}  ({elapsed:.2f}s){marker}")
        rows.append(r)
    print(f"\n총 소요: {time.time() - t0:.1f}초")

    # 결과 표 (sharpe 순)
    print("\n" + "=" * 105)
    print("  결과 (전체 기간 sharpe 순)")
    print("=" * 105)
    print(f"  {'MAX':>5} | {'sharpe':>7} {'return':>8} {'MDD':>6} {'wr':>4} "
          f"{'PF':>5} {'trd':>5} | {'2023':>5} {'2024':>5} {'2025':>5} {'2026':>5}")
    print("-" * 105)
    sorted_rows = sorted(rows, key=lambda x: x['sharpe'], reverse=True)
    for r in sorted_rows:
        v = r['buy_ret20d_max']
        label = "OFF" if v is None else f"{v:.0f}%"
        marker = " *" if v is None else "  "
        print(f"  {label:>5} | {r['sharpe']:>+7.2f} {r['total_return']:>+8.1%} "
              f"{r['mdd']:>6.1%} {r['win_rate']:>4.0%} {r['pf']:>5.2f} {r['trades']:>5d} | "
              f"{fmt(r['sharpe_2023'])} {fmt(r['sharpe_2024'])} "
              f"{fmt(r['sharpe_2025'])} {fmt(r['sharpe_2026'])}{marker}")

    # 채택 기준 평가 (현행 None 대비)
    base = next(r for r in rows if r['buy_ret20d_max'] is None)
    print("\n" + "=" * 105)
    print("  채택 기준 평가 (현행 None=baseline 대비)")
    print("=" * 105)
    print(f"  baseline: sharpe={base['sharpe']:+.3f}, trades={base['trades']}, "
          f"yearly={[round(base[f'sharpe_{y}'], 2) for y in YEARS]}")
    print()
    print(f"  {'MAX':>5} | {'dSharpe':>8} {'dTrades':>8} | {'years better':>14} | verdict")
    print("-" * 105)
    for r in sorted_rows:
        if r['buy_ret20d_max'] is None:
            continue
        d_sh = r['sharpe'] - base['sharpe']
        d_trd = r['trades'] - base['trades']
        years_better = sum(
            1 for y in YEARS
            if (r[f'sharpe_{y}'] == r[f'sharpe_{y}'] and base[f'sharpe_{y}'] == base[f'sharpe_{y}']
                and r[f'sharpe_{y}'] >= base[f'sharpe_{y}'])
        )
        trade_drop = 1 - r['trades'] / base['trades'] if base['trades'] > 0 else 0
        c1 = d_sh > 0
        c2 = years_better >= 3
        c3 = trade_drop <= 0.30
        verdict = "PASS" if (c1 and c2 and c3) else "fail"
        flags = "".join(['s' if c1 else '.', 'y' if c2 else '.', 't' if c3 else '.'])
        print(f"  {r['buy_ret20d_max']:>4.0f}% | {d_sh:>+7.2f} {d_trd:>+8d} | "
              f"{years_better}/4 (drop {trade_drop:>4.0%}) | {verdict} [{flags}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
