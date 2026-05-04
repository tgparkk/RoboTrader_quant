#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BUY_RET5D_MAX 멀티버스 백테스트

5일 누적 수익률 상한 가드(모멘텀 과열 차단) 임계값 탐색.
2026-04-30 058430(5일 +94%) 매수 후 -6.11% 손절 사례 대응.

단위: 백분율 (예: 30.0 = 30% 초과 시 매수 차단). None이면 비활성.

사용법:
    python scripts/buy_ret5d_max_multiverse.py
    python scripts/buy_ret5d_max_multiverse.py --output results/buy_ret5d_max.csv
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


START_DATE = "2023-01-01"
END_DATE = "2026-02-28"

# 현재 운영 설정 + V100 환경 (V100 전환 후 buy_min_score=95, sm 비활성)
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
    buy_ret5d_min=-3.0,  # 백분율
    buy_ret5d_max=None,
)

# Sweep 값 (백분율, None=비활성, 양수=상한)
SWEEP_VALUES = [None, 70.0, 50.0, 40.0, 30.0, 25.0, 20.0, 15.0, 10.0]

YEARS = ["2023", "2024", "2025", "2026"]


def yearly_sharpe(snapshots, year_prefix):
    subset = [s for s in snapshots if s.date.startswith(year_prefix)]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def run_one(loader, trading_days, ret5d_max, start_norm, end_norm):
    merged = {**BASE, 'buy_ret5d_max': ret5d_max}
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
        'buy_ret5d_max': ret5d_max,
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


def fmt(v, pct=False, dp=2):
    if v != v:  # NaN
        return "  n/a"
    if pct:
        return f"{v:>6.1%}"
    return f"{v:>6.{dp}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=START_DATE)
    ap.add_argument('--end', default=END_DATE)
    ap.add_argument('--output', default='results/buy_ret5d_max_multiverse.csv')
    args = ap.parse_args()

    print("=" * 90)
    print("  BUY_RET5D_MAX 멀티버스 (5일 누적 수익률 상한, 백분율 단위)")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  기준: TP12/SL6, buy_min_score=95 (V100), buy_ret5d_min=-3%")
    print("=" * 90)

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
        label = "OFF" if v is None else f"+{v:.0f}%"
        marker = " ★ 현행" if v is None else ""
        print(f"  [{i}/{len(SWEEP_VALUES)}] MAX={label:>5} → "
              f"샤프 {r['sharpe']:>5.2f}  수익 {r['total_return']:>7.0%}  "
              f"MDD {r['mdd']:>5.1%}  승률 {r['win_rate']:>5.1%}  "
              f"거래 {r['trades']:>4d}  ({elapsed:.1f}s){marker}")
        rows.append(r)
    total = time.time() - t0
    print(f"\n총 소요: {total:.1f}초")

    # 결과 표 (sharpe 순)
    print("\n" + "=" * 100)
    print("  결과 (전체 기간 sharpe 순)")
    print("=" * 100)
    print(f"  {'MAX':>6} │ {'sharpe':>6} {'return':>8} {'MDD':>6} {'wr':>5} "
          f"{'PF':>5} {'trades':>6} │ {'2023':>6} {'2024':>6} {'2025':>6} {'2026':>6}")
    print("-" * 100)
    sorted_rows = sorted(rows, key=lambda x: x['sharpe'], reverse=True)
    for r in sorted_rows:
        v = r['buy_ret5d_max']
        label = "OFF" if v is None else f"+{v:.0f}%"
        marker = " ★" if v is None else "  "
        print(f"  {label:>6} │ {r['sharpe']:>6.2f} {r['total_return']:>7.0%} "
              f"{r['mdd']:>5.1%} {r['win_rate']:>4.0%} {r['pf']:>5.2f} {r['trades']:>6d} │ "
              f"{fmt(r['sharpe_2023'])} {fmt(r['sharpe_2024'])} "
              f"{fmt(r['sharpe_2025'])} {fmt(r['sharpe_2026'])}{marker}")

    # 채택 기준 평가 (현행 None 대비)
    base = next(r for r in rows if r['buy_ret5d_max'] is None)
    print("\n" + "=" * 100)
    print("  채택 기준 평가 (현행 None 대비)")
    print("=" * 100)
    print(f"  기준: ① in-sample sharpe ≥ base  ② 연도별 4개 중 ≥3개 우위  ③ 거래수 감소 ≤30%")
    print(f"  base sharpe={base['sharpe']:.2f}, trades={base['trades']}, "
          f"yearly={[round(base[f'sharpe_{y}'], 2) for y in YEARS]}")
    print()
    candidates = []
    for r in sorted(rows, key=lambda x: (x['buy_ret5d_max'] is None, -(x['buy_ret5d_max'] or 0))):
        if r['buy_ret5d_max'] is None:
            continue
        c1 = r['sharpe'] >= base['sharpe']
        years_better = sum(
            1 for y in YEARS
            if (r[f'sharpe_{y}'] == r[f'sharpe_{y}'] and base[f'sharpe_{y}'] == base[f'sharpe_{y}']
                and r[f'sharpe_{y}'] >= base[f'sharpe_{y}'])
        )
        c2 = years_better >= 3
        trade_drop = 1 - r['trades'] / base['trades'] if base['trades'] > 0 else 0
        c3 = trade_drop <= 0.30
        passed = c1 and c2 and c3
        if passed:
            candidates.append(r)
        flag = "PASS" if passed else "FAIL"
        print(f"  MAX +{r['buy_ret5d_max']:>4.0f}% | "
              f"sharpe {r['sharpe']:>5.2f} {'OK' if c1 else 'NO':<3} | "
              f"yearly {years_better}/4 {'OK' if c2 else 'NO':<3} | "
              f"trades drop {trade_drop:>5.1%} {'OK' if c3 else 'NO':<3} | {flag}")

    print()
    if candidates:
        best = max(candidates, key=lambda x: x['sharpe'])
        print(f"  [PASS] 채택 후보: MAX = +{best['buy_ret5d_max']:.0f}% (sharpe {best['sharpe']:.2f})")
    else:
        print("  [FAIL] 채택 기준을 모두 만족하는 임계값 없음 (도입 보류)")

    # CSV 저장
    out_path = project_root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n결과 저장: {out_path}")


if __name__ == '__main__':
    main()
