#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
최대 보유일수 멀티버스 백테스트

max_hold_days 값을 변경하며 장기 횡보 종목 강제 매도의 효과를 검증합니다.
TP/SL은 현행(16%/8%) 고정, max_hold_days만 변경.

사용법:
    python scripts/max_hold_days_multiverse.py
    python scripts/max_hold_days_multiverse.py --start 2023-01-01 --end 2026-03-17
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


def run_multiverse(start_date: str, end_date: str,
                   max_hold_values: list,
                   base_params: BacktestParams = None):
    """
    max_hold_days 멀티버스 실행 (데이터 1회 로드)
    """
    if base_params is None:
        base_params = BacktestParams()

    total_combos = len(max_hold_values)
    print(f"\n{'=' * 70}")
    print(f"최대 보유일수 멀티버스 백테스트")
    print(f"{'=' * 70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"TP/SL: {base_params.target_profit_rate:.0%}/{base_params.stop_loss_rate:.0%} (고정)")
    print(f"max_hold_days: {max_hold_values}")
    print(f"총 조합: {total_combos}개")
    print(f"{'=' * 70}\n")

    # 1. 데이터 한 번만 로드
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목\n")

    # 2. 멀티버스 실행
    results = []
    total_start = time.time()

    for i, max_hold in enumerate(max_hold_values, 1):
        combo_start = time.time()

        params = BacktestParams(
            initial_capital=base_params.initial_capital,
            portfolio_size=base_params.portfolio_size,
            target_profit_rate=base_params.target_profit_rate,
            stop_loss_rate=base_params.stop_loss_rate,
            hard_stop_score=base_params.hard_stop_score,
            soft_stop_score=base_params.soft_stop_score,
            soft_stop_rank=base_params.soft_stop_rank,
            safe_score=base_params.safe_score,
            safe_rank=base_params.safe_rank,
            min_hold_days=base_params.min_hold_days,
            max_hold_days=max_hold,
            buy_min_score=base_params.buy_min_score,
            use_dynamic_targets=base_params.use_dynamic_targets,
            trading_cost_rate=base_params.trading_cost_rate,
            buy_cost_rate=base_params.buy_cost_rate,
            sell_cost_rate=base_params.sell_cost_rate,
            slippage_rate=base_params.slippage_rate,
        )

        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

        # 시뮬레이션 루프
        prev_total_value = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._execute_rebalancing(date)
            bt._check_stop_profit_loss(date)

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

        # 최대보유초과 매도 횟수 집계
        max_hold_sells = sum(1 for t in bt.trades
                            if t.action.value == 'SELL' and '최대보유초과' in t.reason)

        combo_elapsed = time.time() - combo_start

        results.append({
            'max_hold_days': max_hold,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'max_hold_sells': max_hold_sells,
            'final_value': result.final_total_value,
        })

        label = "무제한" if max_hold == 0 else f"{max_hold:>3d}일"
        marker = " ★ 현행" if max_hold == 0 else ""
        print(f"  [{i:2d}/{total_combos}] max_hold={label} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"강제매도 {max_hold_sells:>4d}건  "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 3. 결과 정렬 및 출력 (샤프 순)
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 80}")
    print(f"멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 80}")
    print(f"{'순위':>4} {'max_hold':>10} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5} {'강제매도':>6}")
    print(f"{'-' * 80}")

    current_rank = None
    for rank, r in enumerate(results, 1):
        if r['max_hold_days'] == 0:
            current_rank = rank

    for rank, r in enumerate(results, 1):
        is_current = r['max_hold_days'] == 0
        marker = " ◀ 현행(무제한)" if is_current else ""
        label = "무제한" if r['max_hold_days'] == 0 else f"{r['max_hold_days']}일"
        print(f"{rank:4d}. {label:>8} "
              f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} "
              f"{r['total_trades']:>5d} {r['max_hold_sells']:>5d}{marker}")

    print(f"{'-' * 80}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    if current_rank:
        print(f"현행 (무제한) → {current_rank}위/{total_combos}")
    print(f"{'=' * 80}")

    return results


def parse_args():
    parser = argparse.ArgumentParser(description='최대 보유일수 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-03-17', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    return parser.parse_args()


def main():
    args = parse_args()

    # 탐색 범위: 0(무제한), 5, 7, 10, 14, 20, 30, 45, 60, 90, 120일
    max_hold_values = [0, 5, 7, 10, 14, 20, 30, 45, 60, 90, 120]

    base_params = BacktestParams(
        portfolio_size=args.portfolio,
        target_profit_rate=0.15,
        stop_loss_rate=0.08,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        use_dynamic_targets=False,
    )

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        max_hold_values=max_hold_values,
        base_params=base_params,
    )


if __name__ == '__main__':
    main()
