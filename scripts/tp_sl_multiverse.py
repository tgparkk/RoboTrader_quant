#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TP/SL 멀티버스 백테스트

데이터를 한 번만 로드하고 TP/SL 조합만 변경하여 빠르게 탐색합니다.

사용법:
    python scripts/tp_sl_multiverse.py
    python scripts/tp_sl_multiverse.py --start 2023-01-01 --end 2026-02-28
    python scripts/tp_sl_multiverse.py --output results/multiverse.csv
"""
import sys
import time
import argparse
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


def run_multiverse(start_date: str, end_date: str,
                   tp_values: list, sl_values: list,
                   base_params: BacktestParams = None,
                   output_csv: str = None):
    """
    TP/SL 멀티버스 실행 (데이터 1회 로드)
    """
    if base_params is None:
        base_params = BacktestParams()

    total_combos = len(tp_values) * len(sl_values)
    print(f"\n{'=' * 70}")
    print(f"TP/SL 멀티버스 백테스트")
    print(f"{'=' * 70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"TP: {[f'{v:.0%}' for v in tp_values]}")
    print(f"SL: {[f'{v:.0%}' for v in sl_values]}")
    print(f"총 조합: {total_combos}개")
    print(f"포트폴리오: {base_params.portfolio_size}종목, 비용: {base_params.trading_cost_rate:.2%}")
    print(f"{'=' * 70}\n")

    # 1. 데이터 한 번만 로드
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    # 캐시 저장
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목\n")

    # 2. 멀티버스 실행
    results = []
    total_start = time.time()

    for i, (tp, sl) in enumerate(product(tp_values, sl_values), 1):
        combo_start = time.time()

        # 파라미터 설정
        params = BacktestParams(
            initial_capital=base_params.initial_capital,
            portfolio_size=base_params.portfolio_size,
            target_profit_rate=tp,
            stop_loss_rate=sl,
            hard_stop_score=base_params.hard_stop_score,
            soft_stop_score=base_params.soft_stop_score,
            soft_stop_rank=base_params.soft_stop_rank,
            safe_score=base_params.safe_score,
            safe_rank=base_params.safe_rank,
            min_hold_days=base_params.min_hold_days,
            use_dynamic_targets=base_params.use_dynamic_targets,
            buy_cost_rate=base_params.buy_cost_rate,
            sell_cost_rate=base_params.sell_cost_rate,
            slippage_rate=base_params.slippage_rate,
        )

        # 백테스터 생성 + 캐시 주입 (데이터 재로드 없이)
        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

        # 시뮬레이션 루프만 실행
        prev_total_value = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            # TP/SL을 리밸런싱보다 먼저 체크 (실전과 동일)
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

        combo_elapsed = time.time() - combo_start

        results.append({
            'tp': tp,
            'sl': sl,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
            'trading_cost': result.total_trading_cost,
        })

        # 진행 상황 (한 줄)
        marker = " ★ 현행" if tp == 0.16 and sl == 0.08 else ""
        print(f"  [{i:3d}/{total_combos}] TP {tp:5.1%} SL {sl:5.1%} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 3. 결과 정렬 및 출력
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 70}")
    print(f"멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 70}")
    print(f"{'순위':>4} {'TP':>5} {'SL':>5} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5}")
    print(f"{'-' * 70}")

    # 현행 설정 순위 찾기
    current_rank = None
    for rank, r in enumerate(results, 1):
        if r['tp'] == 0.17 and r['sl'] == 0.09:
            current_rank = rank

    for rank, r in enumerate(results, 1):
        is_current = r['tp'] == 0.17 and r['sl'] == 0.09
        marker = " ◀ 현행" if is_current else ""
        if rank <= 20 or is_current:
            print(f"{rank:4d}. {r['tp']:5.0%} {r['sl']:5.0%} "
                  f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
                  f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
                  f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} {r['total_trades']:>5d}{marker}")

    print(f"{'-' * 70}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    if current_rank:
        print(f"현행 TP 16%/SL 8% → {current_rank}위/{total_combos}")
    print(f"{'=' * 70}")

    # 히트맵 출력
    print_heatmap(results, tp_values, sl_values, metric='sharpe_ratio', label='샤프 비율')
    print_heatmap(results, tp_values, sl_values, metric='total_return', label='총 수익률(%)')

    # CSV 저장
    if output_csv:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def print_heatmap(results: list, tp_values: list, sl_values: list,
                  metric: str = 'sharpe_ratio', label: str = ''):
    """TP/SL 히트맵 출력 (텍스트)"""
    # 결과를 딕셔너리로 변환
    data = {}
    for r in results:
        data[(r['tp'], r['sl'])] = r[metric]

    # 최대값 찾기
    max_val = max(data.values())
    max_key = max(data, key=data.get)

    print(f"\n{'=' * 70}")
    print(f"히트맵: {label}")
    print(f"{'=' * 70}")

    # 헤더
    tp_sl_label = "TP\\SL"
    header = f"{tp_sl_label:>8}"
    for sl in sl_values:
        header += f" {sl:>7.0%}"
    print(header)
    print("-" * (8 + 8 * len(sl_values)))

    # 데이터 행
    for tp in tp_values:
        row = f"{tp:>7.0%} |"
        for sl in sl_values:
            val = data.get((tp, sl), 0)
            if metric == 'total_return':
                cell = f"{val * 100:>6.0f}%"
            else:
                cell = f"{val:>7.2f}"

            # 현행 마커
            if tp == 0.16 and sl == 0.08:
                cell = cell[:-1] + "★"
            # 최고값 마커
            elif (tp, sl) == max_key:
                cell = cell[:-1] + "●"

            row += cell
        print(row)

    print(f"\n  ★ = 현행 (TP 16%/SL 8%)")
    print(f"  ● = 최고 ({label}: {max_val:.2f} at TP {max_key[0]:.0%}/SL {max_key[1]:.0%})")


def parse_args():
    parser = argparse.ArgumentParser(description='TP/SL 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-02-28', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--output', type=str, default=None, help='CSV 저장 경로')
    return parser.parse_args()


def main():
    args = parse_args()

    # TP/SL 탐색 범위
    tp_values = [0.10, 0.12, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.22, 0.25]
    sl_values = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.14]

    base_params = BacktestParams(
        portfolio_size=args.portfolio,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        use_dynamic_targets=False,  # TP/SL을 params에서 직접 사용
    )

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        tp_values=tp_values,
        sl_values=sl_values,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
