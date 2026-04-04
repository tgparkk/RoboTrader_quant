#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
신호 필터 워크포워드 검증

signal_filter_multiverse에서 발견된 필터를 연도별로 분할 검증합니다.
- 전체 기간 결과가 특정 연도에 의존하는지 확인
- 모든 연도에서 일관되게 개선되면 진짜 신호, 아니면 과적합

검증 대상:
  1. rank_change_min = -8  (샤프 89, 의심)
  2. score_momentum_min = 1.5  (샤프 71, 의심)
  3. ma60_dist_max = 50  (샤프 16, 합리적)
  4. ret_20d_max = 60  (샤프 15, 합리적)
  + 조합: score_momentum + rank_change
  + 조합: ma60_dist + ret_20d

사용법:
    python scripts/signal_filter_walkforward.py
"""
import sys
import time
import logging
import numpy as np
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from scripts.signal_filter_multiverse import FilteredBacktester


def make_base_params():
    return BacktestParams(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        min_hold_days=0,
        use_dynamic_targets=True,
        rebalancing_sell_cooldown_days=3,
    )


# 검증 기간
PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026Q1", "2026-01-01", "2026-03-31"),
    ("전체", "2023-01-01", "2026-03-31"),
]

# 검증 필터 조합
FILTER_CONFIGS = [
    ("베이스라인 (필터 없음)", {}),
    ("rank_change <= -8", {"rank_change_min": -8}),
    ("rank_change <= -5", {"rank_change_min": -5}),
    ("rank_change <= -3", {"rank_change_min": -3}),
    ("score_momentum >= 1.5", {"score_momentum_min": 1.5}),
    ("score_momentum >= 1.0", {"score_momentum_min": 1.0}),
    ("score_momentum >= 0.5", {"score_momentum_min": 0.5}),
    ("ma60_dist <= 50%", {"ma60_dist_max": 50}),
    ("ma60_dist <= 40%", {"ma60_dist_max": 40}),
    ("ma60_dist <= 30%", {"ma60_dist_max": 30}),
    ("ret_20d <= 60%", {"ret_20d_max": 60}),
    ("ret_20d <= 50%", {"ret_20d_max": 50}),
    ("ret_20d <= 40%", {"ret_20d_max": 40}),
    # 조합
    ("score_mom>=1.5 + rank_chg<=-8", {"score_momentum_min": 1.5, "rank_change_min": -8}),
    ("ma60<=50 + ret20d<=60", {"ma60_dist_max": 50, "ret_20d_max": 60}),
    ("score_mom>=1.0 + ma60<=50", {"score_momentum_min": 1.0, "ma60_dist_max": 50}),
    ("rank_chg<=-5 + ma60<=50", {"rank_change_min": -5, "ma60_dist_max": 50}),
    ("score_mom>=0.5 + ma60<=50 + ret20d<=60", {"score_momentum_min": 0.5, "ma60_dist_max": 50, "ret_20d_max": 60}),
]


def run_single(params, filter_kwargs, start, end, saved_prices, saved_portfolio, saved_factors):
    """단일 백테스트 실행 (조용히)"""
    bt = FilteredBacktester(params=params, **filter_kwargs)
    bt.daily_prices_cache = saved_prices
    bt.portfolio_cache = saved_portfolio
    bt.factors_cache = saved_factors
    bt._reset_state()
    bt.capital = params.initial_capital

    logging.disable(logging.CRITICAL)
    try:
        result = bt.backtest(start, end)
    finally:
        logging.disable(logging.NOTSET)
    return result


def main():
    print(f"{'#' * 110}")
    print(f"  신호 필터 워크포워드 검증")
    print(f"  검증 기간: 2023 / 2024 / 2025 / 2026Q1 / 전체")
    print(f"  검증 필터: {len(FILTER_CONFIGS)}개")
    print(f"{'#' * 110}")

    base_params = make_base_params()
    total_start = time.time()

    # 데이터 로드 (전체 기간)
    print("\n데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date("2023-01-01")
    end_norm = loader._normalize_date("2026-03-31")
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    # ═══════════════════════════════════════════════════════
    # 전체 결과 수집
    # ═══════════════════════════════════════════════════════
    # results[filter_name][period_name] = {sharpe, return, mdd, win_rate, trades, pf}
    results = {}

    total_runs = len(FILTER_CONFIGS) * len(PERIODS)
    run_count = 0

    for filter_name, filter_kwargs in FILTER_CONFIGS:
        results[filter_name] = {}
        for period_name, start, end in PERIODS:
            run_count += 1
            r = run_single(base_params, filter_kwargs, start, end,
                          saved_prices, saved_portfolio, saved_factors)
            results[filter_name][period_name] = {
                'sharpe': r.sharpe_ratio,
                'return': r.total_return,
                'mdd': r.max_drawdown,
                'win_rate': r.win_rate,
                'trades': r.total_trades,
                'pf': r.profit_factor,
            }
            if run_count % 10 == 0:
                print(f"  진행: {run_count}/{total_runs} ({run_count / total_runs * 100:.0f}%)")

    print(f"  완료: {total_runs}회 백테스트\n")

    # ═══════════════════════════════════════════════════════
    # 결과 출력
    # ═══════════════════════════════════════════════════════

    baseline = results["베이스라인 (필터 없음)"]

    # --- 1. 샤프 비율 테이블 ---
    print("=" * 110)
    print("1. 샤프 비율 (연도별)")
    print("=" * 110)
    period_names = [p[0] for p in PERIODS]
    header = f"  {'필터':>38} |"
    for pn in period_names:
        header += f" {pn:>8} |"
    header += " 일관성"
    print(header)
    print(f"  {'-' * 38}-+" + "+".join([f"-{'-' * 8}-" for _ in period_names]) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>38} |"
        yearly_improvements = []
        for pn in period_names:
            s = results[filter_name][pn]['sharpe']
            b = baseline[pn]['sharpe']
            diff = s - b
            if pn != "전체":
                yearly_improvements.append(diff > 0)
            # 색상 표시: 베이스라인 대비 개선(+) / 악화(-)
            if filter_name == "베이스라인 (필터 없음)":
                row += f" {s:>8.2f} |"
            else:
                arrow = "+" if diff > 0 else "-" if diff < 0 else " "
                row += f" {s:>6.2f}{arrow}{abs(diff):>1.0f} |" if abs(diff) < 10 else f" {s:>6.1f}{arrow} |"
        # 일관성: 4개 연도 중 개선된 비율
        if filter_name != "베이스라인 (필터 없음)":
            consistency = sum(yearly_improvements) / len(yearly_improvements) * 100
            row += f" {consistency:>5.0f}%"
            if consistency == 100:
                row += " ***"
            elif consistency >= 75:
                row += " **"
            elif consistency >= 50:
                row += " *"
        print(row)

    # --- 2. 승률 테이블 ---
    print(f"\n{'=' * 110}")
    print("2. 승률 (연도별)")
    print("=" * 110)
    print(header.replace("일관성", "일관성"))
    print(f"  {'-' * 38}-+" + "+".join([f"-{'-' * 8}-" for _ in period_names]) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>38} |"
        yearly_improvements = []
        for pn in period_names:
            wr = results[filter_name][pn]['win_rate'] * 100
            bwr = baseline[pn]['win_rate'] * 100
            diff = wr - bwr
            if pn != "전체":
                yearly_improvements.append(diff > 0)
            if filter_name == "베이스라인 (필터 없음)":
                row += f" {wr:>7.1f}% |"
            else:
                row += f" {wr:>7.1f}% |"
        if filter_name != "베이스라인 (필터 없음)":
            consistency = sum(yearly_improvements) / len(yearly_improvements) * 100
            row += f" {consistency:>5.0f}%"
        print(row)

    # --- 3. 거래수 테이블 (과소 거래 확인) ---
    print(f"\n{'=' * 110}")
    print("3. 거래수 (연도별) - 과소 거래 주의")
    print("=" * 110)
    print(f"  {'필터':>38} |" + "".join(f" {pn:>8} |" for pn in period_names) + " 감소율")
    print(f"  {'-' * 38}-+" + "+".join([f"-{'-' * 8}-" for _ in period_names]) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>38} |"
        for pn in period_names:
            t = results[filter_name][pn]['trades']
            row += f" {t:>8} |"
        if filter_name != "베이스라인 (필터 없음)":
            total_t = results[filter_name]["전체"]['trades']
            base_t = baseline["전체"]['trades']
            reduction = (1 - total_t / base_t) * 100 if base_t > 0 else 0
            row += f" {reduction:>5.0f}%"
            if reduction > 70:
                row += " !!!"  # 과소 거래 경고
            elif reduction > 50:
                row += " !!"
        print(row)

    # --- 4. MDD 테이블 ---
    print(f"\n{'=' * 110}")
    print("4. MDD (연도별)")
    print("=" * 110)
    print(f"  {'필터':>38} |" + "".join(f" {pn:>8} |" for pn in period_names))
    print(f"  {'-' * 38}-+" + "+".join([f"-{'-' * 8}-" for _ in period_names]) + "+")

    for filter_name in results:
        row = f"  {filter_name:>38} |"
        for pn in period_names:
            mdd = results[filter_name][pn]['mdd'] * 100
            row += f" {mdd:>7.1f}% |"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 최종 판정
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 110}")
    print("5. 최종 판정")
    print("=" * 110)

    for filter_name in results:
        if filter_name == "베이스라인 (필터 없음)":
            continue

        yearly_sharpe_diffs = []
        yearly_wr_diffs = []
        for pn in [p[0] for p in PERIODS if p[0] != "전체"]:
            s_diff = results[filter_name][pn]['sharpe'] - baseline[pn]['sharpe']
            wr_diff = results[filter_name][pn]['win_rate'] - baseline[pn]['win_rate']
            yearly_sharpe_diffs.append(s_diff)
            yearly_wr_diffs.append(wr_diff)

        sharpe_consistent = sum(1 for d in yearly_sharpe_diffs if d > 0)
        wr_consistent = sum(1 for d in yearly_wr_diffs if d > 0)
        total_trades = results[filter_name]["전체"]['trades']
        base_trades = baseline["전체"]['trades']
        trade_reduction = (1 - total_trades / base_trades) * 100 if base_trades > 0 else 0

        # 판정 기준
        # - 샤프 4/4 일관 + 거래수 감소 < 50% = 강력 추천
        # - 샤프 3/4 일관 + 거래수 감소 < 50% = 추천
        # - 거래수 감소 > 70% = 과적합 위험
        # - 샤프 2/4 이하 = 불안정

        if trade_reduction > 70:
            verdict = "과적합 위험 (거래 70%+ 감소)"
        elif sharpe_consistent == 4 and trade_reduction < 50:
            verdict = "강력 추천 (4/4 일관, 거래 유지)"
        elif sharpe_consistent >= 3 and trade_reduction < 50:
            verdict = "추천 (3/4 일관)"
        elif sharpe_consistent >= 3 and trade_reduction < 70:
            verdict = "조건부 추천 (일관적이나 거래 감소 큼)"
        elif sharpe_consistent == 2:
            verdict = "불안정 (2/4만 개선)"
        else:
            verdict = "비추천 (일관성 없음)"

        avg_sharpe_diff = np.mean(yearly_sharpe_diffs)
        print(f"  {filter_name:>38} | 샤프 {sharpe_consistent}/4 | 승률 {wr_consistent}/4 | "
              f"거래 -{trade_reduction:.0f}% | 평균 샤프 차이 {avg_sharpe_diff:>+6.1f} | {verdict}")

    elapsed = time.time() - total_start
    print(f"\n  총 소요 시간: {elapsed:.0f}초")


if __name__ == '__main__':
    main()
