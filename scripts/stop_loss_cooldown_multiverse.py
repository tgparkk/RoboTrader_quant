#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TP/SL 손절 cooldown 멀티버스 — 정본 운영 세팅(V100+M30/R30+TP12/SL6) 위에서 N일 sweep.

base 구성: current_config_full_sim.py와 동일 (V100 cache 재구성 + FilteredBacktester)
- 자본 1,000만, 포트 10, V100 buy_min=95, ret5d≥-3, M30(=BUY_MOMENTUM_SCORE_MIN)
- BUY_SCORE_MOMENTUM_MIN=None (V100 시대 비활성)
- rebalancing_sell_cooldown_days=3 (운영 동일)
- slippage 0.0025 (실측)

sweep: stop_loss_cooldown_days = [0, 1, 2, 3, 5, 7, 10, 14, 21] (캘린더일)
"""
import sys
import time
import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from scripts.signal_filter_multiverse import FilteredBacktester
from scripts.v100_threshold_multiverse import build_v100_cache


COOLDOWN_VALUES = [0, 1, 2, 3, 5, 7, 10, 14, 21]


def make_base_params(cooldown_days: int) -> BacktestParams:
    """정본 운영 세팅 (current_config_full_sim.py 기준)."""
    from config.constants import (
        BUY_RET5D_MIN, BUY_RET5D_MAX, BUY_RET20D_MAX, BUY_MOMENTUM_SCORE_MIN,
    )
    return BacktestParams(
        initial_capital=10_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=95.0,
        buy_ret5d_min=BUY_RET5D_MIN,
        buy_ret5d_max=BUY_RET5D_MAX,
        buy_ret20d_max=BUY_RET20D_MAX,
        buy_momentum_score_min=BUY_MOMENTUM_SCORE_MIN,
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
        stop_loss_cooldown_days=cooldown_days,
        regime_filter_enabled=False,
    )


def run_multiverse(start_date: str, end_date: str, cooldown_values, output_csv=None):
    from config.constants import BUY_SCORE_MOMENTUM_MIN

    total_combos = len(cooldown_values)
    print(f"\n{'=' * 84}")
    print(f"손절 cooldown 멀티버스 (정본 base: V100+M30/R30+TP12/SL6, FilteredBacktester+V100 cache)")
    print(f"{'=' * 84}")
    print(f"기간: {start_date} ~ {end_date}")
    sm_str = f"sm>={BUY_SCORE_MOMENTUM_MIN}" if BUY_SCORE_MOMENTUM_MIN is not None else "sm off"
    print(f"  자본 1,000만 | TP12/SL6 | portfolio 10 | buy_min=95 | {sm_str} | reb_cooldown=3d")
    print(f"sweep: SL cooldown = {cooldown_values}일 (캘린더)")
    print(f"{'=' * 84}\n")

    # 1. 데이터 1회 로드
    print("데이터 로딩 중...")
    loader_params = make_base_params(0)
    loader = Backtester(params=loader_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    # V100 cache 재구성 (정본 정합)
    v100_factors, v100_portfolio = build_v100_cache(loader.factors_cache, loader.portfolio_cache)
    saved_prices = loader.daily_prices_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목, V100 cache 재구성 완료\n")

    # 2. 멀티버스
    results = []
    total_start = time.time()
    logging.disable(logging.INFO)  # backtester 노이즈 억제

    for i, cooldown in enumerate(cooldown_values, 1):
        combo_start = time.time()
        params = make_base_params(cooldown)

        bt = FilteredBacktester(params=params, score_momentum_min=BUY_SCORE_MOMENTUM_MIN)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = v100_portfolio
        bt.factors_cache = v100_factors
        bt.capital = params.initial_capital

        prev_total_value = params.initial_capital
        position_count_sum = 0

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
                daily_return=daily_return, cumulative_return=cumulative_return,
            )
            bt.daily_snapshots.append(snapshot)
            prev_total_value = total_value
            position_count_sum += len(bt.positions)

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))

        avg_positions = position_count_sum / len(trading_days) if trading_days else 0
        utilization = avg_positions / params.portfolio_size if params.portfolio_size > 0 else 0
        combo_elapsed = time.time() - combo_start
        marker = " * 현행" if cooldown == 0 else ""

        results.append({
            'cooldown': cooldown,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'avg_positions': avg_positions,
            'utilization': utilization,
            'final_value': result.final_total_value,
        })

        print(f"  [{i}/{total_combos}] SL cooldown {cooldown:>2d}일 -> "
              f"수익 {result.total_return:>7.1%}  연환산 {result.annualized_return:>6.1%}  "
              f"샤프 {result.sharpe_ratio:>5.2f}  MDD {result.max_drawdown:>5.1%}  "
              f"승률 {result.win_rate:>5.1%}  거래 {result.total_trades:>4d}  "
              f"보유 {avg_positions:>4.1f}/{params.portfolio_size} "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start
    logging.disable(logging.NOTSET)

    # 3. 결과 (샤프 순)
    results_sorted = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)
    print(f"\n{'=' * 88}")
    print(f"손절 cooldown 결과 (샤프 순)")
    print(f"{'=' * 88}")
    print(f"{'순위':>4} {'cooldown':>9} {'총수익':>9} {'연환산':>8} {'샤프':>6} "
          f"{'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5} {'보유':>5}")
    print(f"{'-' * 88}")
    for rank, r in enumerate(results_sorted, 1):
        marker = " <- 현행" if r['cooldown'] == 0 else ""
        print(f"{rank:>4d}  {r['cooldown']:>6d}일   "
              f"{r['total_return']:>8.1%} {r['annualized_return']:>7.1%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} "
              f"{r['total_trades']:>5d} {r['avg_positions']:>4.1f}{marker}")
    print(f"{'-' * 88}")
    print(f"총 {total_combos}개 조합, 소요 {total_elapsed:.1f}초")
    print(f"{'=' * 88}")

    # 4. baseline 대비 Δ
    base = next((r for r in results if r['cooldown'] == 0), None)
    if base is not None:
        print(f"\n[baseline(cooldown=0) 대비 Δ]")
        print(f"{'cooldown':>9} | {'Δ수익률':>9} {'Δ샤프':>7} {'ΔMDD':>7} {'Δ승률':>7} {'Δ거래':>6}")
        print(f"{'-' * 62}")
        for r in sorted(results, key=lambda x: x['cooldown']):
            print(f"{r['cooldown']:>6d}일   | "
                  f"{(r['total_return']-base['total_return']):>+9.1%} "
                  f"{(r['sharpe_ratio']-base['sharpe_ratio']):>+7.2f} "
                  f"{(r['max_drawdown']-base['max_drawdown']):>+7.1%} "
                  f"{(r['win_rate']-base['win_rate']):>+7.1%} "
                  f"{(r['total_trades']-base['total_trades']):>+6d}")

    if output_csv:
        import pandas as pd
        pd.DataFrame(results).to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def parse_args():
    parser = argparse.ArgumentParser(description='TP/SL 손절 cooldown 멀티버스 (정본 base)')
    parser.add_argument('--start', type=str, default='2023-01-02', help='시작일')
    parser.add_argument('--end', type=str, default='2026-05-23', help='종료일')
    parser.add_argument('--output', type=str, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    run_multiverse(args.start, args.end, COOLDOWN_VALUES, args.output)


if __name__ == '__main__':
    main()
