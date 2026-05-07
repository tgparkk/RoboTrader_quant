#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
buy_ret20d_max=30 우위가 다른 multiverse 축에서도 유지되는지 검증

TP/SL 5조합 × portfolio_size 4조합 × {None, 30, 20} = 60회 백테스트
각 셋업에서 baseline 대비 MAX=30/20의 sharpe 개선 폭이 일관되는지 확인.
"""
import sys
import io
import time
import itertools
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

TP_SL_COMBOS = [
    (0.10, 0.05),
    (0.12, 0.06),  # current
    (0.15, 0.07),
    (0.16, 0.08),
    (0.20, 0.10),
]
PORTFOLIO_SIZES = [8, 10, 12, 15]
RET20D_VALUES = [None, 30.0, 20.0]


def yearly_sharpe(snapshots, year_prefix):
    subset = [s for s in snapshots if s.date.startswith(year_prefix)]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def run_one(loader, trading_days, tp, sl, ps, ret20d_max, start_norm, end_norm):
    merged = {**BASE,
              'target_profit_rate': tp,
              'stop_loss_rate': sl,
              'portfolio_size': ps,
              'buy_ret20d_max': ret20d_max}
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
        'tp': tp, 'sl': sl, 'ps': ps, 'ret20d_max': ret20d_max,
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'mdd': result.max_drawdown,
        'trades': result.total_trades,
    }


def main():
    print("=" * 110)
    print("  buy_ret20d_max 안정성 — TP/SL 5조합 × portfolio_size 4조합 × {OFF, 30, 20}")
    print(f"  기간: {START_DATE} ~ {END_DATE}, 총 60 backtest")
    print("=" * 110)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    rows = []
    t0 = time.time()
    for tp, sl in TP_SL_COMBOS:
        for ps in PORTFOLIO_SIZES:
            for r20 in RET20D_VALUES:
                r = run_one(loader, trading_days, tp, sl, ps, r20, start_norm, end_norm)
                rows.append(r)
    print(f"\n총 소요: {time.time() - t0:.1f}초")

    # baseline vs MAX=30 vs MAX=20 비교 (각 셋업별)
    print("\n" + "=" * 110)
    print("  셋업별 baseline vs MAX=30 vs MAX=20 (sharpe)")
    print("=" * 110)
    print(f"  {'TP/SL':>10} {'PS':>3} | {'baseline':>10} | {'MAX=30':>10} {'Δ30':>7} | "
          f"{'MAX=20':>10} {'Δ20':>7} | {'best':>8} | trades(B/30/20)")
    print("-" * 110)

    setup_summary = []
    for tp, sl in TP_SL_COMBOS:
        for ps in PORTFOLIO_SIZES:
            base = next(r for r in rows
                        if r['tp'] == tp and r['sl'] == sl and r['ps'] == ps and r['ret20d_max'] is None)
            r30 = next(r for r in rows
                       if r['tp'] == tp and r['sl'] == sl and r['ps'] == ps and r['ret20d_max'] == 30.0)
            r20 = next(r for r in rows
                       if r['tp'] == tp and r['sl'] == sl and r['ps'] == ps and r['ret20d_max'] == 20.0)
            d30 = r30['sharpe'] - base['sharpe']
            d20 = r20['sharpe'] - base['sharpe']
            best = max(('OFF', base['sharpe']), ('30', r30['sharpe']), ('20', r20['sharpe']),
                       key=lambda x: x[1])
            setup_summary.append((tp, sl, ps, base['sharpe'], r30['sharpe'], r20['sharpe'],
                                  d30, d20, best[0]))
            tp_sl_str = f"{tp:.2f}/{sl:.2f}"
            current_marker = " <-current" if (tp, sl, ps) == (0.12, 0.06, 10) else ""
            print(f"  {tp_sl_str:>10} {ps:>3} | "
                  f"{base['sharpe']:>+10.3f} | "
                  f"{r30['sharpe']:>+10.3f} {d30:>+7.3f} | "
                  f"{r20['sharpe']:>+10.3f} {d20:>+7.3f} | "
                  f"{best[0]:>8} | "
                  f"{base['trades']:>3}/{r30['trades']:>3}/{r20['trades']:>3}{current_marker}")

    # 통계 요약
    print("\n" + "=" * 110)
    print("  안정성 통계")
    print("=" * 110)
    n_setup = len(setup_summary)
    n_30_better = sum(1 for s in setup_summary if s[6] > 0)
    n_30_equal = sum(1 for s in setup_summary if s[6] == 0)
    n_30_worse = sum(1 for s in setup_summary if s[6] < 0)
    n_20_better = sum(1 for s in setup_summary if s[7] > 0)
    n_20_equal = sum(1 for s in setup_summary if s[7] == 0)
    n_20_worse = sum(1 for s in setup_summary if s[7] < 0)
    avg_d30 = sum(s[6] for s in setup_summary) / n_setup
    avg_d20 = sum(s[7] for s in setup_summary) / n_setup
    best_30 = sum(1 for s in setup_summary if s[8] == '30')
    best_20 = sum(1 for s in setup_summary if s[8] == '20')
    best_off = sum(1 for s in setup_summary if s[8] == 'OFF')

    print(f"  총 셋업: {n_setup}개 (TP/SL × portfolio_size)")
    print(f"\n  MAX=30 vs OFF:")
    print(f"    개선 {n_30_better}개 / 동일 {n_30_equal}개 / 악화 {n_30_worse}개  "
          f"(평균 ΔSharpe {avg_d30:+.3f})")
    print(f"  MAX=20 vs OFF:")
    print(f"    개선 {n_20_better}개 / 동일 {n_20_equal}개 / 악화 {n_20_worse}개  "
          f"(평균 ΔSharpe {avg_d20:+.3f})")
    print(f"\n  최고 조합 분포: OFF={best_off}, MAX=30={best_30}, MAX=20={best_20}")

    if best_30 + best_20 >= n_setup * 0.7:
        verdict = "ROBUST: MAX 게이트가 다양한 셋업에서 우위"
    elif best_30 + best_20 >= n_setup * 0.5:
        verdict = "MIXED: 일부 셋업에서만 우위, 추가 검증 필요"
    else:
        verdict = "WEAK: MAX 게이트가 현행 셋업에 한정된 효과 (과적합 의심)"
    print(f"\n  판정: {verdict}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
