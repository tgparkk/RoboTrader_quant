#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
레짐 필터 멀티버스 백테스트
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""

KOSPI 시가 갭(NXT 프록시) + S&P500 + VIX 조합별 성과를 비교합니다.
데이터를 한 번만 로드하고 파라미터 조합만 변경하여 빠르게 탐색합니다.

사용법:
    python scripts/regime_multiverse.py
    python scripts/regime_multiverse.py --start 2023-01-01 --end 2026-02-28
    python scripts/regime_multiverse.py --output results/regime_multiverse.csv
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


def run_regime_multiverse(start_date: str, end_date: str,
                          base_params: BacktestParams = None,
                          output_csv: str = None):
    """
    레짐 필터 멀티버스 실행 (데이터 1회 로드)
    """
    if base_params is None:
        base_params = BacktestParams(
            hard_stop_score=65.0,
            soft_stop_score=67.0,
            buy_min_score=65.0,
            use_dynamic_targets=False,
        )

    # 탐색 범위
    gap_cautions = [-0.01, -0.015, -0.02, -0.03]       # KOSPI 시가 갭 CAUTION 임계
    sp500_cautions = [-0.02, -0.03, -0.04]              # S&P500 CAUTION 임계
    vix_cautions = [25.0, 30.0, 35.0]                   # VIX CAUTION 임계
    caution_buys = [3, 5, 7]                            # CAUTION 시 최대 매수

    total_combos = len(gap_cautions) * len(sp500_cautions) * len(vix_cautions) * len(caution_buys)

    print(f"\n{'=' * 80}")
    print(f"레짐 필터 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"갭 CAUTION: {gap_cautions}")
    print(f"S&P500 CAUTION: {sp500_cautions}")
    print(f"VIX CAUTION: {vix_cautions}")
    print(f"CAUTION 매수: {caution_buys}")
    print(f"총 조합: {total_combos}개 + 기준선(필터 없음)")
    print(f"포트폴리오: {base_params.portfolio_size}종목, TP {base_params.target_profit_rate:.0%}/SL {base_params.stop_loss_rate:.0%}")
    print(f"buy_min_score: {base_params.buy_min_score}")
    print(f"{'=' * 80}\n")

    # 1. 데이터 한 번만 로드
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    # US 마켓 데이터도 한 번만 로드
    print("US 마켓 데이터(S&P500, VIX) 로딩 중...")
    loader.params.regime_filter_enabled = True  # US 데이터 로드를 위해 임시 활성화
    loader._preload_us_market_data(trading_days[0], trading_days[-1])

    # 캐시 저장
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    saved_us_market = loader.us_market_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목\n")

    def run_single(params: BacktestParams, label: str = "") -> dict:
        """단일 조합 시뮬레이션"""
        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors
        bt.us_market_cache = saved_us_market

        prev_total_value = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._today_regime = bt._determine_regime(date)
            bt._regime_stats[bt._today_regime] = bt._regime_stats.get(bt._today_regime, 0) + 1

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

        return {
            'result': result,
            'regime_stats': dict(bt._regime_stats),
        }

    # 2. 기준선 실행 (필터 없음)
    print("기준선 (레짐 필터 없음) 실행 중...")
    baseline_start = time.time()
    baseline_params = BacktestParams(
        initial_capital=base_params.initial_capital,
        portfolio_size=base_params.portfolio_size,
        target_profit_rate=base_params.target_profit_rate,
        stop_loss_rate=base_params.stop_loss_rate,
        hard_stop_score=base_params.hard_stop_score,
        soft_stop_score=base_params.soft_stop_score,
        soft_stop_rank=base_params.soft_stop_rank,
        safe_score=base_params.safe_score,
        safe_rank=base_params.safe_rank,
        buy_min_score=base_params.buy_min_score,
        use_dynamic_targets=base_params.use_dynamic_targets,
        trading_cost_rate=base_params.trading_cost_rate,
        regime_filter_enabled=False,
    )
    baseline = run_single(baseline_params)
    baseline_result = baseline['result']
    baseline_elapsed = time.time() - baseline_start
    print(f"  기준선: 수익 {baseline_result.total_return:>8.0%}  샤프 {baseline_result.sharpe_ratio:>5.2f}  "
          f"MDD {baseline_result.max_drawdown:>5.1%}  거래 {baseline_result.total_trades}건 ({baseline_elapsed:.1f}s)\n")

    # 3. 멀티버스 실행
    results = []
    total_start = time.time()

    for i, (gap_c, sp_c, vix_c, max_buy) in enumerate(
        product(gap_cautions, sp500_cautions, vix_cautions, caution_buys), 1
    ):
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
            buy_min_score=base_params.buy_min_score,
            use_dynamic_targets=base_params.use_dynamic_targets,
            trading_cost_rate=base_params.trading_cost_rate,
            regime_filter_enabled=True,
            gap_caution_pct=gap_c,
            gap_crisis_pct=gap_c * 2.5,         # CAUTION의 2.5배
            sp500_caution_pct=sp_c,
            sp500_crisis_pct=sp_c * 1.67,        # CAUTION의 1.67배
            vix_caution=vix_c,
            vix_crisis=vix_c + 10,               # CAUTION + 10
            caution_max_buy=max_buy,
        )

        out = run_single(params)
        result = out['result']
        regime_stats = out['regime_stats']
        combo_elapsed = time.time() - combo_start

        results.append({
            'gap_caution': gap_c,
            'sp500_caution': sp_c,
            'vix_caution': vix_c,
            'caution_max_buy': max_buy,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
            'normal_days': regime_stats.get('NORMAL', 0),
            'caution_days': regime_stats.get('CAUTION', 0),
            'crisis_days': regime_stats.get('CRISIS', 0),
        })

        # 진행 상황
        print(f"  [{i:3d}/{total_combos}] 갭{gap_c:>6.1%} SP{sp_c:>5.1%} VIX{vix_c:>3.0f} 매수{max_buy} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  거래 {result.total_trades:>4d}  "
              f"C/CA/CR {regime_stats.get('NORMAL', 0)}/{regime_stats.get('CAUTION', 0)}/{regime_stats.get('CRISIS', 0)} "
              f"({combo_elapsed:.1f}s)")

    total_elapsed = time.time() - total_start

    # 4. 결과 정렬 및 출력
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 100}")
    print(f"멀티버스 결과 (샤프 비율 순) — 기준선: 샤프 {baseline_result.sharpe_ratio:.2f}, "
          f"수익 {baseline_result.total_return:.0%}, MDD {baseline_result.max_drawdown:.1%}")
    print(f"{'=' * 100}")
    print(f"{'순위':>4} {'갭C':>6} {'SPC':>5} {'VIX':>4} {'매수':>3} "
          f"{'총수익률':>10} {'샤프':>6} {'MDD':>6} {'승률':>6} {'거래':>5} "
          f"{'CAUT':>5} {'CRIS':>5} {'vs기준':>7}")
    print(f"{'-' * 100}")

    for rank, r in enumerate(results, 1):
        sharpe_diff = r['sharpe_ratio'] - baseline_result.sharpe_ratio
        diff_str = f"{sharpe_diff:>+6.2f}"

        if rank <= 20:
            print(f"{rank:4d}. {r['gap_caution']:>5.1%} {r['sp500_caution']:>4.1%} "
                  f"{r['vix_caution']:>4.0f} {r['caution_max_buy']:>3d} "
                  f"{r['total_return']:>9.0%} {r['sharpe_ratio']:>6.2f} "
                  f"{r['max_drawdown']:>5.1%} {r['win_rate']:>5.1%} "
                  f"{r['total_trades']:>5d} {r['caution_days']:>5d} "
                  f"{r['crisis_days']:>5d} {diff_str}")

    # 기준선보다 좋은 조합 수
    better_count = sum(1 for r in results if r['sharpe_ratio'] > baseline_result.sharpe_ratio)
    mdd_improved = sum(1 for r in results
                       if abs(r['max_drawdown']) < abs(baseline_result.max_drawdown))

    print(f"{'-' * 100}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    print(f"기준선 대비: 샤프 개선 {better_count}/{total_combos}개, MDD 개선 {mdd_improved}/{total_combos}개")
    print(f"{'=' * 100}")

    # 5. 기준선 vs 최적 비교
    if results:
        best = results[0]
        print(f"\n{'=' * 60}")
        print(f"기준선 vs 최적 조합 비교")
        print(f"{'=' * 60}")
        print(f"{'':>20} {'기준선':>12} {'최적':>12} {'차이':>10}")
        print(f"{'-' * 60}")
        print(f"{'샤프 비율':>20} {baseline_result.sharpe_ratio:>12.2f} {best['sharpe_ratio']:>12.2f} "
              f"{best['sharpe_ratio'] - baseline_result.sharpe_ratio:>+10.2f}")
        print(f"{'총 수익률':>20} {baseline_result.total_return:>11.0%} {best['total_return']:>11.0%}")
        print(f"{'MDD':>20} {baseline_result.max_drawdown:>11.1%} {best['max_drawdown']:>11.1%}")
        print(f"{'승률':>20} {baseline_result.win_rate:>11.1%} {best['win_rate']:>11.1%}")
        print(f"{'거래 수':>20} {baseline_result.total_trades:>12d} {best['total_trades']:>12d} "
              f"{best['total_trades'] - baseline_result.total_trades:>+10d}")
        print(f"{'-' * 60}")
        print(f"최적 파라미터:")
        print(f"  갭 CAUTION: {best['gap_caution']:.1%} (CRISIS: {best['gap_caution'] * 2.5:.1%})")
        print(f"  S&P500 CAUTION: {best['sp500_caution']:.1%} (CRISIS: {best['sp500_caution'] * 1.67:.1%})")
        print(f"  VIX CAUTION: {best['vix_caution']:.0f} (CRISIS: {best['vix_caution'] + 10:.0f})")
        print(f"  CAUTION 매수: {best['caution_max_buy']}종목")
        print(f"  레짐 분포: NORMAL {best['normal_days']}일, CAUTION {best['caution_days']}일, CRISIS {best['crisis_days']}일")

        # 과적합 경고
        trade_reduction = (baseline_result.total_trades - best['total_trades']) / baseline_result.total_trades
        if trade_reduction > 0.5:
            print(f"\n  ⚠ 경고: 거래 {trade_reduction:.0%} 감소 — 과적합 가능성!")
        print(f"{'=' * 60}")

    # CSV 저장
    if output_csv:
        import pandas as pd
        # 기준선 행 추가
        baseline_row = {
            'gap_caution': 0, 'sp500_caution': 0, 'vix_caution': 0,
            'caution_max_buy': 0,
            'total_return': baseline_result.total_return,
            'annualized_return': baseline_result.annualized_return,
            'sharpe_ratio': baseline_result.sharpe_ratio,
            'max_drawdown': baseline_result.max_drawdown,
            'win_rate': baseline_result.win_rate,
            'profit_factor': baseline_result.profit_factor,
            'total_trades': baseline_result.total_trades,
            'final_value': baseline_result.final_total_value,
            'normal_days': len(trading_days), 'caution_days': 0, 'crisis_days': 0,
        }
        all_results = [baseline_row] + results
        df = pd.DataFrame(all_results)
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def parse_args():
    parser = argparse.ArgumentParser(description='레짐 필터 멀티버스 백테스트')
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
        buy_min_score=65.0,
        use_dynamic_targets=False,
    )

    run_regime_multiverse(
        start_date=args.start,
        end_date=args.end,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
