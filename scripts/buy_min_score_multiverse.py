#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
매수 최소 점수(buy_min_score) 멀티버스 백테스트

"10종목 채우기"가 항상 최적인지 검증합니다.
buy_min_score > 0이면 해당 점수 미만 종목은 매수하지 않아 현금 비중이 자연스럽게 발생합니다.

사용법:
    python scripts/buy_min_score_multiverse.py
    python scripts/buy_min_score_multiverse.py --start 2023-01-01 --end 2026-02-28
    python scripts/buy_min_score_multiverse.py --output results/buy_min_score.csv
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


def run_multiverse(start_date: str, end_date: str,
                   score_values: list,
                   base_params: BacktestParams = None,
                   output_csv: str = None):
    """
    buy_min_score 멀티버스 실행 (데이터 1회 로드)
    """
    if base_params is None:
        base_params = BacktestParams()

    total_combos = len(score_values)
    print(f"\n{'=' * 80}")
    print(f"매수 최소 점수(buy_min_score) 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"고정: TP {base_params.target_profit_rate:.0%} / SL {base_params.stop_loss_rate:.0%} / "
          f"포트폴리오 {base_params.portfolio_size}종목")
    print(f"탐색: buy_min_score = {score_values}")
    print(f"총 조합: {total_combos}개")
    print(f"{'=' * 80}\n")

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

    for i, score in enumerate(score_values, 1):
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
            buy_min_score=score,
            use_dynamic_targets=base_params.use_dynamic_targets,
            buy_cost_rate=base_params.buy_cost_rate,
            sell_cost_rate=base_params.sell_cost_rate,
            slippage_rate=base_params.slippage_rate,
        )

        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

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

        # 평균 보유 종목 수 / 현금 비중 계산
        avg_positions = sum(s.position_count for s in bt.daily_snapshots) / len(bt.daily_snapshots)
        avg_cash_ratio = sum(s.capital / s.total_value for s in bt.daily_snapshots if s.total_value > 0) / len(bt.daily_snapshots)

        combo_elapsed = time.time() - combo_start

        results.append({
            'buy_min_score': score,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
            'trading_cost': result.total_trading_cost,
            'avg_positions': avg_positions,
            'avg_cash_ratio': avg_cash_ratio,
        })

        marker = " ★ 현행" if score == 0 else ""
        print(f"  [{i:2d}/{total_combos}] score>={score:5.1f} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"평균종목 {avg_positions:>4.1f}  현금 {avg_cash_ratio:>5.1%}  "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 3. 결과 정렬 및 출력
    print(f"\n{'=' * 80}")
    print(f"멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 80}")
    print(f"{'순위':>4} {'최소점수':>8} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5} "
          f"{'평균종목':>8} {'현금비중':>8}")
    print(f"{'-' * 80}")

    results_by_sharpe = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)

    for rank, r in enumerate(results_by_sharpe, 1):
        marker = " ◀ 현행(무필터)" if r['buy_min_score'] == 0 else ""
        print(f"{rank:4d}. {r['buy_min_score']:>7.1f} "
              f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} {r['total_trades']:>5d} "
              f"{r['avg_positions']:>7.1f} {r['avg_cash_ratio']:>7.1%}{marker}")

    print(f"{'-' * 80}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    print(f"{'=' * 80}")

    # 4. 상세 비교표 (점수 순서)
    print(f"\n{'=' * 80}")
    print(f"상세 비교 (buy_min_score 순)")
    print(f"{'=' * 80}")
    print(f"{'최소점수':>8} │ {'총수익률':>10} {'샤프':>6} {'MDD':>6} │ "
          f"{'승률':>6} {'PF':>5} │ {'평균종목':>8}/{base_params.portfolio_size} "
          f"{'현금비중':>8} │ {'거래수':>5}")
    print(f"{'-' * 80}")

    results_by_score = sorted(results, key=lambda x: x['buy_min_score'])
    baseline = results_by_score[0]  # score=0 (현행)

    for r in results_by_score:
        score = r['buy_min_score']
        ret_diff = (r['total_return'] - baseline['total_return']) * 100
        sharpe_diff = r['sharpe_ratio'] - baseline['sharpe_ratio']
        mdd_diff = (r['max_drawdown'] - baseline['max_drawdown']) * 100

        diff_str = ""
        if score > 0:
            diff_str = f"  (수익 {ret_diff:+.0f}%p, 샤프 {sharpe_diff:+.2f}, MDD {mdd_diff:+.1f}%p)"

        marker = "★" if score == 0 else " "
        print(f" {marker}{score:>6.1f}  │ "
              f"{r['total_return']:>9.0%} {r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} │ "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} │ "
              f"{r['avg_positions']:>7.1f}/{base_params.portfolio_size}  "
              f"{r['avg_cash_ratio']:>7.1%} │ {r['total_trades']:>5d}{diff_str}")

    print(f"{'=' * 80}")

    # 5. 핵심 인사이트
    best = results_by_sharpe[0]
    current = next(r for r in results if r['buy_min_score'] == 0)

    print(f"\n핵심 인사이트:")
    print(f"  현행 (무필터):  샤프 {current['sharpe_ratio']:.2f}, 수익 {current['total_return']:.0%}, "
          f"평균 {current['avg_positions']:.1f}종목")
    print(f"  최적 (>={best['buy_min_score']:.0f}점): 샤프 {best['sharpe_ratio']:.2f}, "
          f"수익 {best['total_return']:.0%}, 평균 {best['avg_positions']:.1f}종목")

    if best['buy_min_score'] > 0:
        print(f"\n  → 매수 최소 점수 {best['buy_min_score']:.0f}점 도입 시:")
        print(f"    샤프 {best['sharpe_ratio'] - current['sharpe_ratio']:+.2f}, "
              f"MDD {(best['max_drawdown'] - current['max_drawdown']) * 100:+.1f}%p, "
              f"승률 {(best['win_rate'] - current['win_rate']) * 100:+.1f}%p")
        print(f"    평균 {best['avg_positions']:.1f}종목 보유 (현금 {best['avg_cash_ratio']:.1%})")
    else:
        print(f"\n  → 현행(무필터)이 이미 최적. 매수 점수 필터 불필요.")

    # CSV 저장
    if output_csv:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def parse_args():
    parser = argparse.ArgumentParser(description='매수 최소 점수 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-02-28', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--output', type=str, default=None, help='CSV 저장 경로')
    return parser.parse_args()


def main():
    args = parse_args()

    # buy_min_score 탐색 범위
    # 0 = 현행(무필터), 60~75 = 점진적 강화
    score_values = [0, 60, 63, 65, 67, 68, 70, 72, 75]

    base_params = BacktestParams(
        portfolio_size=args.portfolio,
        target_profit_rate=0.16,
        stop_loss_rate=0.08,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        safe_score=75.0,
        safe_rank=25,
        use_dynamic_targets=False,
    )

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        score_values=score_values,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
