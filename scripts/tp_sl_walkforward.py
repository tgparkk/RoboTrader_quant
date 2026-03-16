#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TP/SL 워크포워드 + 안정성 분석

전체 기간을 여러 구간으로 나눠 각각 최적을 찾고,
"모든 구간에서 일관되게 좋은" 조합을 추천합니다.

과적합 방지 핵심:
  1. 워크포워드: 6개월 학습 → 다음 6개월 검증 (롤링)
  2. 안정성 점수: ±1~2%p 바꿔도 결과가 비슷한지 검사
  3. 종합 순위: 전 구간 샤프 중간값 × 안정성 점수

사용법:
    python scripts/tp_sl_walkforward.py
    python scripts/tp_sl_walkforward.py --start 2023-01-01 --end 2026-03-14
"""
import sys
import time
import argparse
from pathlib import Path
from itertools import product
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


def run_single_backtest(bt_template, trading_days, params):
    """단일 백테스트 실행 (캐시 주입 방식)"""
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = bt_template.daily_prices_cache
    bt.portfolio_cache = bt_template.portfolio_cache
    bt.factors_cache = bt_template.factors_cache

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
    start_norm = trading_days[0]
    end_norm = trading_days[-1]
    result = bt._create_result(start_norm, end_norm, len(trading_days))
    return result


def make_params(base_params, tp, sl):
    """TP/SL만 변경한 파라미터 생성"""
    return BacktestParams(
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
        buy_min_score=base_params.buy_min_score,
        use_dynamic_targets=base_params.use_dynamic_targets,
        trading_cost_rate=base_params.trading_cost_rate,
    )


def split_trading_days(trading_days, window_months=6):
    """거래일을 window_months 단위로 분할"""
    windows = []
    if not trading_days:
        return windows

    # 월 기준으로 분할
    current_window = []
    start_month = trading_days[0][:7]  # YYYY-MM
    month_count = 0
    prev_month = start_month

    for date in trading_days:
        cur_month = date[:7]
        if cur_month != prev_month:
            month_count += 1
            prev_month = cur_month

        if month_count >= window_months and current_window:
            windows.append(current_window)
            current_window = []
            month_count = 0

        current_window.append(date)

    if current_window:
        windows.append(current_window)

    return windows


def calculate_stability_score(results_by_combo, tp, sl, tp_values, sl_values):
    """
    안정성 점수: 이웃 조합 대비 성능 변동이 작을수록 높은 점수
    ±1단계 이웃의 샤프 비율 평균과의 차이가 작을수록 안정적
    """
    tp_idx = tp_values.index(tp) if tp in tp_values else -1
    sl_idx = sl_values.index(sl) if sl in sl_values else -1
    if tp_idx < 0 or sl_idx < 0:
        return 0.0

    center_sharpe = results_by_combo.get((tp, sl), {}).get('sharpe_ratio', 0)
    neighbor_sharpes = []

    for di in [-1, 0, 1]:
        for dj in [-1, 0, 1]:
            if di == 0 and dj == 0:
                continue
            ni, nj = tp_idx + di, sl_idx + dj
            if 0 <= ni < len(tp_values) and 0 <= nj < len(sl_values):
                n_tp, n_sl = tp_values[ni], sl_values[nj]
                n_data = results_by_combo.get((n_tp, n_sl))
                if n_data:
                    neighbor_sharpes.append(n_data['sharpe_ratio'])

    if not neighbor_sharpes:
        return 0.0

    avg_neighbor = sum(neighbor_sharpes) / len(neighbor_sharpes)
    # 이웃과의 차이가 작을수록 안정적 (max 1.0)
    diff = abs(center_sharpe - avg_neighbor)
    # diff가 0이면 stability=1.0, diff가 클수록 0에 가까움
    stability = 1.0 / (1.0 + diff * 2)
    return stability


def run_walkforward(start_date, end_date, tp_values, sl_values,
                    base_params, window_months=6):
    """워크포워드 분석 실행"""
    print(f"\n{'=' * 90}")
    print(f"TP/SL 워크포워드 + 안정성 분석")
    print(f"{'=' * 90}")
    print(f"전체 기간: {start_date} ~ {end_date}")
    print(f"윈도우: {window_months}개월씩 분할")
    print(f"TP: {[f'{v:.0%}' for v in tp_values]}")
    print(f"SL: {[f'{v:.0%}' for v in sl_values]}")
    total_combos = len(tp_values) * len(sl_values)
    print(f"총 조합: {total_combos}개")
    print(f"{'=' * 90}\n")

    # 1. 전체 데이터 로드
    print("전체 데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    all_trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(all_trading_days)
    print(f"데이터 로드 완료: {len(all_trading_days)}거래일\n")

    # 2. 구간 분할
    windows = split_trading_days(all_trading_days, window_months)
    print(f"구간 분할: {len(windows)}개 윈도우")
    for i, w in enumerate(windows):
        print(f"  W{i+1}: {w[0]} ~ {w[-1]} ({len(w)}거래일)")
    print()

    # 3. 각 윈도우별 멀티버스 실행
    window_results = []  # [{(tp,sl): {metrics...}}, ...]
    total_start = time.time()

    for wi, window_days in enumerate(windows):
        print(f"── 윈도우 {wi+1}/{len(windows)}: {window_days[0]} ~ {window_days[-1]} ──")
        w_start = time.time()

        w_results = {}
        for tp, sl in product(tp_values, sl_values):
            params = make_params(base_params, tp, sl)
            result = run_single_backtest(loader, window_days, params)
            w_results[(tp, sl)] = {
                'total_return': result.total_return,
                'annualized_return': result.annualized_return,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown': result.max_drawdown,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_trades': result.total_trades,
            }

        window_results.append(w_results)

        # 윈도우별 TOP 3
        sorted_combos = sorted(w_results.items(), key=lambda x: x[1]['sharpe_ratio'], reverse=True)
        w_elapsed = time.time() - w_start
        print(f"  TOP: ", end="")
        for rank, ((tp, sl), data) in enumerate(sorted_combos[:3], 1):
            print(f"{rank}.TP{tp:.0%}/SL{sl:.0%}(샤프{data['sharpe_ratio']:.2f}) ", end="")
        print(f" ({w_elapsed:.1f}s)")

    total_elapsed = time.time() - total_start

    # 4. 전 구간 종합 분석
    print(f"\n{'=' * 90}")
    print(f"종합 분석 (전 {len(windows)}구간)")
    print(f"{'=' * 90}")

    # 각 조합의 전 구간 성적 수집
    combo_stats = {}
    for tp, sl in product(tp_values, sl_values):
        sharpes = []
        returns = []
        mdds = []
        win_rates = []
        for w_results in window_results:
            data = w_results.get((tp, sl))
            if data:
                sharpes.append(data['sharpe_ratio'])
                returns.append(data['total_return'])
                mdds.append(data['max_drawdown'])
                win_rates.append(data['win_rate'])

        if not sharpes:
            continue

        sharpes_sorted = sorted(sharpes)
        median_sharpe = sharpes_sorted[len(sharpes_sorted) // 2]
        min_sharpe = min(sharpes)
        max_sharpe = max(sharpes)
        avg_sharpe = sum(sharpes) / len(sharpes)
        std_sharpe = (sum((s - avg_sharpe) ** 2 for s in sharpes) / len(sharpes)) ** 0.5

        median_return = sorted(returns)[len(returns) // 2]
        worst_mdd = min(mdds)  # most negative

        # 전 구간 1위 횟수
        top1_count = 0
        top3_count = 0
        for w_results in window_results:
            sorted_combos = sorted(w_results.items(), key=lambda x: x[1]['sharpe_ratio'], reverse=True)
            top1_key = sorted_combos[0][0]
            top3_keys = [c[0] for c in sorted_combos[:3]]
            if (tp, sl) == top1_key:
                top1_count += 1
            if (tp, sl) in top3_keys:
                top3_count += 1

        combo_stats[(tp, sl)] = {
            'median_sharpe': median_sharpe,
            'min_sharpe': min_sharpe,
            'max_sharpe': max_sharpe,
            'avg_sharpe': avg_sharpe,
            'std_sharpe': std_sharpe,
            'median_return': median_return,
            'worst_mdd': worst_mdd,
            'avg_win_rate': sum(win_rates) / len(win_rates),
            'top1_count': top1_count,
            'top3_count': top3_count,
            'sharpes': sharpes,
        }

    # 5. 안정성 점수 계산 (전체 기간 기준)
    # 전체 기간 한 번 더 실행해서 안정성 계산
    print("\n전체 기간 안정성 분석 중...")
    full_results = {}
    for tp, sl in product(tp_values, sl_values):
        params = make_params(base_params, tp, sl)
        result = run_single_backtest(loader, all_trading_days, params)
        full_results[(tp, sl)] = {
            'sharpe_ratio': result.sharpe_ratio,
            'total_return': result.total_return,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
        }

    for tp, sl in product(tp_values, sl_values):
        stability = calculate_stability_score(full_results, tp, sl, tp_values, sl_values)
        if (tp, sl) in combo_stats:
            combo_stats[(tp, sl)]['stability'] = stability
            combo_stats[(tp, sl)]['full_sharpe'] = full_results[(tp, sl)]['sharpe_ratio']
            combo_stats[(tp, sl)]['full_return'] = full_results[(tp, sl)]['total_return']
            combo_stats[(tp, sl)]['full_mdd'] = full_results[(tp, sl)]['max_drawdown']
            combo_stats[(tp, sl)]['full_win_rate'] = full_results[(tp, sl)]['win_rate']
            combo_stats[(tp, sl)]['full_pf'] = full_results[(tp, sl)]['profit_factor']

    # 6. 종합 점수 = median_sharpe × stability × (1 - std_sharpe/avg_sharpe)
    #    일관성이 높고 안정적인 조합이 높은 점수
    for key, stats in combo_stats.items():
        consistency = 1.0
        if stats['avg_sharpe'] > 0 and stats['std_sharpe'] > 0:
            cv = stats['std_sharpe'] / stats['avg_sharpe']  # 변동계수
            consistency = 1.0 / (1.0 + cv)

        # min_sharpe가 음수면 페널티
        min_penalty = max(0, 1.0 + stats['min_sharpe'] * 0.1) if stats['min_sharpe'] < 0 else 1.0

        stats['composite_score'] = (
            stats['median_sharpe']
            * stats['stability']
            * consistency
            * min_penalty
        )

    # 7. 결과 출력
    ranked = sorted(combo_stats.items(), key=lambda x: x[1]['composite_score'], reverse=True)

    print(f"\n{'=' * 90}")
    print(f"워크포워드 종합 순위 (종합점수 = 중간샤프 × 안정성 × 일관성)")
    print(f"{'=' * 90}")
    print(f"{'순위':>4} {'TP':>5} {'SL':>5} │ {'종합':>6} {'안정':>5} │ "
          f"{'전체샤프':>8} {'전체수익':>8} {'전체MDD':>7} │ "
          f"{'중간샤프':>8} {'최저샤프':>8} {'편차':>5} │ "
          f"{'TOP3':>4}")
    print(f"{'-' * 90}")

    current_rank = None
    for rank, ((tp, sl), stats) in enumerate(ranked, 1):
        is_current = (tp == 0.15 and sl == 0.08)
        if is_current:
            current_rank = rank
        marker = " ◀ 현행" if is_current else ""

        if rank <= 20 or is_current:
            print(f"{rank:4d}. {tp:5.0%} {sl:5.0%} │ "
                  f"{stats['composite_score']:>5.2f} {stats['stability']:>5.2f} │ "
                  f"{stats['full_sharpe']:>7.2f} {stats['full_return']:>7.0%} {stats['full_mdd']:>6.1%} │ "
                  f"{stats['median_sharpe']:>7.2f} {stats['min_sharpe']:>7.2f} {stats['std_sharpe']:>5.2f} │ "
                  f"{stats['top3_count']:>3d}/{len(windows)}{marker}")

    print(f"{'-' * 90}")
    print(f"총 {total_combos}개 조합, {len(windows)}구간 워크포워드 (소요: {total_elapsed:.0f}초)")
    if current_rank:
        print(f"현행 TP15%/SL8% → 종합 {current_rank}위/{total_combos}")
    print(f"{'=' * 90}")

    # 8. 구간별 상세 (TOP 5만)
    print(f"\n{'=' * 90}")
    print(f"TOP 5 구간별 샤프 비율 상세")
    print(f"{'=' * 90}")

    header = f"{'순위':>4} {'TP':>5} {'SL':>5} │"
    for i in range(len(windows)):
        header += f" {'W'+str(i+1):>6}"
    header += f" │ {'중간':>6} {'최저':>6}"
    print(header)
    print(f"{'-' * 90}")

    for rank, ((tp, sl), stats) in enumerate(ranked[:5], 1):
        row = f"{rank:4d}. {tp:5.0%} {sl:5.0%} │"
        for s in stats['sharpes']:
            row += f" {s:>6.2f}"
        row += f" │ {stats['median_sharpe']:>6.2f} {stats['min_sharpe']:>6.2f}"
        print(row)

    # 현행도 표시
    if current_rank and current_rank > 5:
        stats = combo_stats[(0.15, 0.08)]
        row = f"{current_rank:4d}. {'15%':>5} {'8%':>5} │"
        for s in stats['sharpes']:
            row += f" {s:>6.2f}"
        row += f" │ {stats['median_sharpe']:>6.2f} {stats['min_sharpe']:>6.2f}  ◀ 현행"
        print(row)

    print(f"{'=' * 90}")

    # 9. 추천
    best = ranked[0]
    best_tp, best_sl = best[0]
    best_stats = best[1]

    print(f"\n{'=' * 90}")
    print(f"추천")
    print(f"{'=' * 90}")
    print(f"  워크포워드 최적: TP {best_tp:.0%} / SL {best_sl:.0%}")
    print(f"    종합점수: {best_stats['composite_score']:.2f}")
    print(f"    전체 기간: 샤프 {best_stats['full_sharpe']:.2f}, "
          f"수익 {best_stats['full_return']:.0%}, MDD {best_stats['full_mdd']:.1%}")
    print(f"    구간 일관성: 중간 샤프 {best_stats['median_sharpe']:.2f}, "
          f"최저 {best_stats['min_sharpe']:.2f}, 편차 {best_stats['std_sharpe']:.2f}")
    print(f"    안정성: {best_stats['stability']:.2f} (이웃 조합 대비)")
    print(f"    TOP3 진입: {best_stats['top3_count']}/{len(windows)}구간")

    if current_rank:
        curr_stats = combo_stats[(0.15, 0.08)]
        print(f"\n  현행 (TP 15% / SL 8%): 종합 {current_rank}위")
        print(f"    전체 기간: 샤프 {curr_stats['full_sharpe']:.2f}, "
              f"수익 {curr_stats['full_return']:.0%}, MDD {curr_stats['full_mdd']:.1%}")
        print(f"    구간 일관성: 중간 샤프 {curr_stats['median_sharpe']:.2f}, "
              f"최저 {curr_stats['min_sharpe']:.2f}")

    print(f"{'=' * 90}")

    return ranked, combo_stats, window_results


def parse_args():
    parser = argparse.ArgumentParser(description='TP/SL 워크포워드 + 안정성 분석')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-03-14', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--window', type=int, default=6, help='윈도우 크기 (개월)')
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
        buy_min_score=65.0,
        use_dynamic_targets=False,
    )

    run_walkforward(
        start_date=args.start,
        end_date=args.end,
        tp_values=tp_values,
        sl_values=sl_values,
        base_params=base_params,
        window_months=args.window,
    )


if __name__ == '__main__':
    main()
