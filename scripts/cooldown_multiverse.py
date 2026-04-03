#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
리밸런싱 매도 쿨다운 멀티버스 백테스트

쿨다운 일수(REBALANCING_SELL_COOLDOWN_DAYS)를 0/1/2/3일로 변경하며
TP12/SL6 고정 조건에서 성과를 비교합니다.

배경:
  - 현재 설정: 쿨다운 3일 (리밸런싱 매도 후 재매수 차단)
  - 문제: 쿨다운 8종목 동시에 걸려 포트 10칸 중 2칸만 사용 (가동률 20%)
  - 목적: 쿨다운 일수별 성과 비교 (샤프, 수익률, MDD, 거래횟수, 평균보유종목수)

사용법:
    python scripts/cooldown_multiverse.py
    python scripts/cooldown_multiverse.py --start 2023-01-01 --end 2026-02-28
    python scripts/cooldown_multiverse.py --output results/cooldown.csv
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


# 고정 TP/SL (현행 설정)
FIXED_TP = 0.12
FIXED_SL = 0.06

# 테스트할 쿨다운 일수
COOLDOWN_VALUES = [0, 1, 2, 3]


def run_multiverse(start_date: str, end_date: str,
                   cooldown_values: list,
                   base_params: BacktestParams = None,
                   output_csv: str = None):
    """
    쿨다운 멀티버스 실행 (데이터 1회 로드)
    """
    if base_params is None:
        base_params = BacktestParams()

    total_combos = len(cooldown_values)
    print(f"\n{'=' * 70}")
    print(f"쿨다운 멀티버스 백테스트 (TP {FIXED_TP:.0%} / SL {FIXED_SL:.0%} 고정)")
    print(f"{'=' * 70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"쿨다운: {cooldown_values}일")
    print(f"총 조합: {total_combos}개")
    print(f"포트폴리오: {base_params.portfolio_size}종목")
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

    for i, cooldown in enumerate(cooldown_values, 1):
        combo_start = time.time()

        params = BacktestParams(
            initial_capital=base_params.initial_capital,
            portfolio_size=base_params.portfolio_size,
            target_profit_rate=FIXED_TP,
            stop_loss_rate=FIXED_SL,
            hard_stop_score=base_params.hard_stop_score,
            soft_stop_score=base_params.soft_stop_score,
            soft_stop_rank=base_params.soft_stop_rank,
            safe_score=base_params.safe_score,
            safe_rank=base_params.safe_rank,
            buy_min_score=base_params.buy_min_score,
            min_hold_days=base_params.min_hold_days,
            use_dynamic_targets=False,
            buy_cost_rate=base_params.buy_cost_rate,
            sell_cost_rate=base_params.sell_cost_rate,
            slippage_rate=base_params.slippage_rate,
            rebalancing_sell_cooldown_days=cooldown,
        )

        # 백테스터 생성 + 캐시 주입 (데이터 재로드 없이)
        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

        # 시뮬레이션 루프
        prev_total_value = params.initial_capital
        position_count_sum = 0

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
            position_count_sum += len(bt.positions)

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))

        # 평균 보유 종목 수
        avg_positions = position_count_sum / len(trading_days) if trading_days else 0
        # 포트폴리오 가동률 (평균 보유 / 목표 크기)
        utilization = avg_positions / params.portfolio_size if params.portfolio_size > 0 else 0

        combo_elapsed = time.time() - combo_start

        is_current = cooldown == 3
        marker = " ★ 현행" if is_current else ""

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
            'trading_cost': result.total_trading_cost,
        })

        print(f"  [{i}/{total_combos}] 쿨다운 {cooldown:1d}일 → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"평균보유 {avg_positions:>4.1f}종목 (가동률 {utilization:>4.0%})  "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 3. 결과 정렬 및 출력
    results_sorted = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 80}")
    print(f"쿨다운 멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 80}")
    print(f"{'순위':>4} {'쿨다운':>6} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'평균보유':>8} {'가동률':>6} {'거래':>5}")
    print(f"{'-' * 80}")

    for rank, r in enumerate(results_sorted, 1):
        is_current = r['cooldown'] == 3
        marker = " ◀ 현행" if is_current else ""
        print(f"{rank:4d}. {r['cooldown']:4d}일  "
              f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['avg_positions']:>7.1f}종목 "
              f"{r['utilization']:>5.0%} {r['total_trades']:>5d}{marker}")

    print(f"{'-' * 80}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    print(f"{'=' * 80}")

    # 4. 상세 비교표 출력
    _print_detail_table(results)

    # CSV 저장
    if output_csv:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def _print_detail_table(results: list):
    """쿨다운별 상세 비교표"""
    print(f"\n{'=' * 80}")
    print("쿨다운 일수별 상세 비교")
    print(f"{'=' * 80}")

    metrics = [
        ('총수익률',     'total_return',      '{:.0%}'),
        ('연환산수익률', 'annualized_return',  '{:.0%}'),
        ('샤프비율',     'sharpe_ratio',       '{:.2f}'),
        ('MDD',          'max_drawdown',       '{:.1%}'),
        ('승률',         'win_rate',           '{:.1%}'),
        ('수익팩터',     'profit_factor',      '{:.2f}'),
        ('총거래수',     'total_trades',       '{:.0f}'),
        ('평균보유종목', 'avg_positions',      '{:.1f}'),
        ('가동률',       'utilization',        '{:.0%}'),
    ]

    # 헤더
    header = f"{'지표':<14}"
    for r in results:
        marker = "★" if r['cooldown'] == 3 else " "
        header += f"  {r['cooldown']}일{marker}  "
    print(header)
    print("-" * 80)

    for label, key, fmt in metrics:
        row = f"{label:<14}"
        for r in results:
            val = r[key]
            cell = fmt.format(val)
            row += f"  {cell:>6}    "
        print(row)

    print(f"{'=' * 80}")
    print(f"  ★ = 현행 설정 (쿨다운 3일)")


def parse_args():
    parser = argparse.ArgumentParser(description='리밸런싱 쿨다운 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-02-28', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--output', type=str, default=None, help='CSV 저장 경로')
    return parser.parse_args()


def main():
    args = parse_args()

    base_params = BacktestParams(
        portfolio_size=args.portfolio,
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
        cooldown_values=COOLDOWN_VALUES,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
