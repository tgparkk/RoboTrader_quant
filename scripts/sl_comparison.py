#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SL 비교 백테스트: SL 8% (현행) vs SL 9% vs SL 10%

TP 16% 고정, 손절률만 변경하여 비교합니다.
워크포워드 검증: 전체 기간 + 2분할 기간별 비교.

사용법:
    python scripts/sl_comparison.py
"""
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


def run_single_backtest(start_date: str, end_date: str, params: BacktestParams,
                        saved_prices=None, saved_portfolio=None, saved_factors=None,
                        trading_days=None) -> BacktestResult:
    """단일 백테스트 실행 (캐시 주입 지원)"""
    bt = Backtester(params=params)

    if saved_prices is not None:
        # 캐시 주입 모드: 데이터 재로드 없이 시뮬레이션만 실행
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

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
        start_norm = bt._normalize_date(start_date)
        end_norm = bt._normalize_date(end_date)
        result = bt._create_result(start_norm, end_norm, len(trading_days))
        return result
    else:
        # 전체 백테스트 실행 (데이터 로드 포함)
        return bt.backtest(start_date, end_date)


def load_data_once(start_date: str, end_date: str, base_params: BacktestParams):
    """데이터를 한 번만 로드하고 캐시 반환"""
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    return (
        loader.daily_prices_cache,
        loader.portfolio_cache,
        loader.factors_cache,
        trading_days,
    )


def filter_trading_days(trading_days, start_date, end_date):
    """거래일 리스트에서 기간 필터링"""
    return [d for d in trading_days if start_date <= d <= end_date]


def print_comparison_table(results_dict: dict, period_label: str):
    """비교 테이블 출력"""
    print(f"\n{'=' * 90}")
    print(f"  {period_label}")
    print(f"{'=' * 90}")
    print(f"{'지표':<20} ", end="")
    for label in results_dict.keys():
        print(f"{'':>2}{label:>18}", end="")
    print()
    print(f"{'-' * 90}")

    # 지표 목록
    metrics = [
        ("총 수익률", lambda r: f"{r.total_return:>15.2%}"),
        ("연환산 수익률", lambda r: f"{r.annualized_return:>15.2%}"),
        ("샤프 비율", lambda r: f"{r.sharpe_ratio:>15.2f}"),
        ("MDD", lambda r: f"{r.max_drawdown:>15.2%}"),
        ("변동성", lambda r: f"{r.volatility:>15.2%}"),
        ("승률", lambda r: f"{r.win_rate:>15.1%}"),
        ("수익 팩터(PF)", lambda r: f"{r.profit_factor:>15.2f}"),
        ("총 거래 수", lambda r: f"{r.total_trades:>15,d}건"),
        ("승리 거래", lambda r: f"{r.winning_trades:>15,d}건"),
        ("패배 거래", lambda r: f"{r.losing_trades:>15,d}건"),
        ("평균 수익", lambda r: f"{r.avg_profit:>13,.0f}원"),
        ("평균 손실", lambda r: f"{r.avg_loss:>13,.0f}원"),
        ("총 거래비용", lambda r: f"{r.total_trading_cost:>13,.0f}원"),
        ("최종 자산", lambda r: f"{r.final_total_value:>13,.0f}원"),
    ]

    for metric_name, formatter in metrics:
        print(f"  {metric_name:<18} ", end="")
        for label, result in results_dict.items():
            print(f"  {formatter(result)}", end="")
        print()

    print(f"{'-' * 90}")

    # 현행 대비 변화량
    labels = list(results_dict.keys())
    results = list(results_dict.values())
    base = results[0]  # SL 8% (현행)

    print(f"\n  ▶ 현행(SL 8%) 대비 변화:")
    for i in range(1, len(labels)):
        r = results[i]
        label = labels[i]
        sharpe_diff = r.sharpe_ratio - base.sharpe_ratio
        return_diff = r.total_return - base.total_return
        mdd_diff = r.max_drawdown - base.max_drawdown
        wr_diff = r.win_rate - base.win_rate
        pf_diff = r.profit_factor - base.profit_factor

        print(f"    [{label}]")
        print(f"      샤프: {sharpe_diff:+.2f}  |  총수익률: {return_diff:+.2%}  |  "
              f"MDD: {mdd_diff:+.2%}  |  승률: {wr_diff:+.1%}  |  PF: {pf_diff:+.2f}")

    print(f"{'=' * 90}")


def main():
    print("=" * 90)
    print("  SL 비교 백테스트: TP16% 고정, SL 8% vs 9% vs 10%")
    print("  프로덕션 파라미터 기준 (portfolio=10, buy_min_score=65)")
    print("=" * 90)

    # 공통 파라미터 (프로덕션과 동일)
    common_kwargs = dict(
        initial_capital=50_000_000,
        portfolio_size=10,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        min_hold_days=0,
        max_hold_days=0,
        buy_min_score=65.0,
        use_dynamic_targets=False,
        buy_cost_rate=0.00015,
        sell_cost_rate=0.00245,
        slippage_rate=0.001,
    )

    # SL 조합 정의
    sl_configs = [
        ("TP16/SL8 (현행)", 0.16, 0.08),
        ("TP16/SL9", 0.16, 0.09),
        ("TP16/SL10", 0.16, 0.10),
    ]

    # 기간 정의
    full_start = "2023-01-01"
    full_end = "2026-03-21"

    # 워크포워드 분할
    wf_periods = [
        ("전반기 (2023-01 ~ 2024-06)", "2023-01-01", "2024-06-28"),
        ("후반기 (2024-07 ~ 2026-03)", "2024-07-01", "2026-03-21"),
    ]

    # ============================================================
    # 1단계: 전체 기간 데이터 로드 (1회만)
    # ============================================================
    print("\n데이터 로딩 중...")
    load_start = time.time()

    base_params = BacktestParams(
        target_profit_rate=0.16,
        stop_loss_rate=0.08,
        **common_kwargs,
    )
    prices, portfolio, factors, all_trading_days = load_data_once(full_start, full_end, base_params)
    load_elapsed = time.time() - load_start
    print(f"데이터 로드 완료: {len(all_trading_days)}거래일, {len(prices)}종목 ({load_elapsed:.1f}초)")

    # ============================================================
    # 2단계: 전체 기간 비교
    # ============================================================
    print("\n[1/3] 전체 기간 백테스트 실행 중...")
    full_results = {}

    for label, tp, sl in sl_configs:
        t0 = time.time()
        params = BacktestParams(
            target_profit_rate=tp,
            stop_loss_rate=sl,
            **common_kwargs,
        )
        result = run_single_backtest(
            full_start, full_end, params,
            saved_prices=prices,
            saved_portfolio=portfolio,
            saved_factors=factors,
            trading_days=all_trading_days,
        )
        elapsed = time.time() - t0
        full_results[label] = result
        print(f"  {label}: 샤프 {result.sharpe_ratio:.2f}, "
              f"수익 {result.total_return:.1%}, MDD {result.max_drawdown:.1%} ({elapsed:.1f}초)")

    print_comparison_table(full_results, f"전체 기간 비교 ({full_start} ~ {full_end}, {len(all_trading_days)}거래일)")

    # ============================================================
    # 3단계: 워크포워드 분할 비교
    # ============================================================
    for period_idx, (period_label, wf_start, wf_end) in enumerate(wf_periods):
        print(f"\n[{period_idx + 2}/3] {period_label} 백테스트 실행 중...")
        wf_trading_days = filter_trading_days(all_trading_days, wf_start, wf_end)

        if not wf_trading_days:
            print(f"  경고: {wf_start} ~ {wf_end} 구간에 거래일이 없습니다.")
            continue

        wf_results = {}
        for label, tp, sl in sl_configs:
            t0 = time.time()
            params = BacktestParams(
                target_profit_rate=tp,
                stop_loss_rate=sl,
                **common_kwargs,
            )
            result = run_single_backtest(
                wf_start, wf_end, params,
                saved_prices=prices,
                saved_portfolio=portfolio,
                saved_factors=factors,
                trading_days=wf_trading_days,
            )
            elapsed = time.time() - t0
            wf_results[label] = result
            print(f"  {label}: 샤프 {result.sharpe_ratio:.2f}, "
                  f"수익 {result.total_return:.1%}, MDD {result.max_drawdown:.1%} ({elapsed:.1f}초)")

        print_comparison_table(wf_results, f"{period_label} ({len(wf_trading_days)}거래일)")

    # ============================================================
    # 4단계: 최종 요약 판정
    # ============================================================
    print(f"\n{'=' * 90}")
    print(f"  최종 요약 판정")
    print(f"{'=' * 90}")

    # 전체 기간 기준 최고 샤프
    best_label = max(full_results, key=lambda k: full_results[k].sharpe_ratio)
    best_result = full_results[best_label]
    current_result = full_results["TP16/SL8 (현행)"]

    print(f"\n  전체 기간 최고 샤프: {best_label} (샤프 {best_result.sharpe_ratio:.2f})")
    print(f"  현행 TP16/SL8 샤프: {current_result.sharpe_ratio:.2f}")

    if best_label == "TP16/SL8 (현행)":
        print(f"\n  결론: 현행 SL 8%가 최적입니다. 변경 불필요.")
    else:
        sharpe_improvement = best_result.sharpe_ratio - current_result.sharpe_ratio
        mdd_change = best_result.max_drawdown - current_result.max_drawdown
        print(f"\n  {best_label}이 현행 대비:")
        print(f"    - 샤프 {sharpe_improvement:+.2f} 개선")
        print(f"    - MDD {mdd_change:+.2%} 변화")
        print(f"\n  주의: 워크포워드 양 기간 모두 우위인지 확인 필요 (과적합 경계)")

    print(f"{'=' * 90}\n")


if __name__ == '__main__':
    main()
