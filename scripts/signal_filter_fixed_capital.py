#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
고정 자본 신호 필터 워크포워드 검증

복리 효과를 제거하고, 매 거래마다 동일한 금액을 배분하여
필터의 순수한 엣지를 측정합니다.

방식: 매수 시 항상 initial_capital / portfolio_size 사용 (자본 성장 무시)
지표: 거래당 평균 수익률, 승률, 총 실현손익 (복리 없는 누적)

사용법:
    python scripts/signal_filter_fixed_capital.py
"""
import sys
import re
import time
import logging
import numpy as np
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import TradeAction
from scripts.signal_filter_multiverse import FilteredBacktester


# 검증 기간
PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026", "2026-01-01", "2026-04-07"),
    ("전체", "2023-01-01", "2026-04-07"),
]

FILTER_CONFIGS = [
    ("베이스라인", {}),
    ("score_mom>=0.5", {"score_momentum_min": 0.5}),
    ("score_mom>=1.0", {"score_momentum_min": 1.0}),
    ("score_mom>=1.5", {"score_momentum_min": 1.5}),
    ("rank_change<=-8", {"rank_change_min": -8}),
    ("ma60<=50", {"ma60_dist_max": 50}),
    ("ret20d<=60", {"ret_20d_max": 60}),
    ("sm>=0.5+ma60<=50", {"score_momentum_min": 0.5, "ma60_dist_max": 50}),
    ("sm>=0.5+ret20d<=60", {"score_momentum_min": 0.5, "ret_20d_max": 60}),
    ("sm>=1.0+ma60<=50", {"score_momentum_min": 1.0, "ma60_dist_max": 50}),
    ("sm>=1.0+ret20d<=60", {"score_momentum_min": 1.0, "ret_20d_max": 60}),
    ("sm>=1.5+rc<=-8", {"score_momentum_min": 1.5, "rank_change_min": -8}),
    ("sm>=1.0+rc<=-8", {"score_momentum_min": 1.0, "rank_change_min": -8}),
    ("sm>=0.5+rc<=-8", {"score_momentum_min": 0.5, "rank_change_min": -8}),
    ("sm>=1.5+ma60<=50+rc<=-8", {"score_momentum_min": 1.5, "ma60_dist_max": 50, "rank_change_min": -8}),
]


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


def analyze_fixed_capital(result, initial_capital, portfolio_size):
    """
    복리 제거 분석: 모든 거래를 고정 자본 기준으로 재계산

    매 거래의 수익률은 그대로 사용하되, 금액은 고정 배분(5백만원/종목)으로 환산
    """
    fixed_per_stock = initial_capital / portfolio_size  # 5,000,000원

    # 매수-매도 쌍 매칭
    open_buys = defaultdict(list)
    pairs = []
    for t in result.trades:
        if t.action == TradeAction.BUY:
            open_buys[t.stock_code].append(t)
        elif t.action == TradeAction.SELL:
            if open_buys[t.stock_code]:
                buy_t = open_buys[t.stock_code].pop(0)
                pairs.append((buy_t, t))

    if not pairs:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
            'avg_profit_rate': 0, 'avg_win_rate': 0, 'avg_loss_rate': 0,
            'total_pnl': 0, 'total_pnl_pct': 0,
            'profit_factor': 0, 'max_consecutive_loss': 0,
            'avg_hold_days': 0,
        }

    wins = 0
    losses = 0
    win_rates = []
    loss_rates = []
    all_rates = []
    total_pnl = 0
    total_win_pnl = 0
    total_loss_pnl = 0
    hold_days_list = []

    # 연속 손실 추적
    consecutive_losses = 0
    max_consecutive_losses = 0

    for buy_t, sell_t in pairs:
        prate = sell_t.profit_rate  # 실제 수익률 (비용 포함)
        # 고정 자본 기준 손익
        fixed_pnl = fixed_per_stock * prate
        # 고정 자본 기준 거래비용 (매수 0.015% + 매도 0.245%)
        fixed_cost = fixed_per_stock * 0.0026
        net_pnl = fixed_pnl - fixed_cost

        total_pnl += net_pnl
        all_rates.append(prate * 100)

        if prate > 0:
            wins += 1
            win_rates.append(prate * 100)
            total_win_pnl += net_pnl
            consecutive_losses = 0
        else:
            losses += 1
            loss_rates.append(prate * 100)
            total_loss_pnl += abs(net_pnl)
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

        # 보유 기간
        try:
            from datetime import datetime
            d1 = datetime.strptime(buy_t.date, "%Y-%m-%d")
            d2 = datetime.strptime(sell_t.date, "%Y-%m-%d")
            hold_days_list.append((d2 - d1).days)
        except:
            pass

    n = wins + losses
    win_rate = wins / n * 100 if n > 0 else 0
    avg_profit_rate = np.mean(all_rates) if all_rates else 0
    avg_win_rate = np.mean(win_rates) if win_rates else 0
    avg_loss_rate = np.mean(loss_rates) if loss_rates else 0
    profit_factor = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else 999
    total_pnl_pct = total_pnl / initial_capital * 100

    return {
        'trades': n,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_profit_rate': avg_profit_rate,
        'avg_win_rate': avg_win_rate,
        'avg_loss_rate': avg_loss_rate,
        'total_pnl': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'profit_factor': profit_factor,
        'max_consecutive_loss': max_consecutive_losses,
        'avg_hold_days': np.mean(hold_days_list) if hold_days_list else 0,
    }


def run_single(params, filter_kwargs, start, end, saved_prices, saved_portfolio, saved_factors):
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
    print(f"{'#' * 120}")
    print(f"  고정 자본 신호 필터 워크포워드 검증")
    print(f"  자본: 5천만원 고정 (복리 없음, 종목당 5백만원)")
    print(f"  기간: 2023 / 2024 / 2025 / 2026Q1")
    print(f"{'#' * 120}")

    base_params = make_base_params()
    total_start = time.time()

    # 데이터 로드
    print("\n데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date("2023-01-01")
    end_norm = loader._normalize_date("2026-04-07")
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    # 전체 결과 수집
    results = {}  # results[filter_name][period_name] = analyze_fixed_capital result

    total_runs = len(FILTER_CONFIGS) * len(PERIODS)
    run_count = 0

    for filter_name, filter_kwargs in FILTER_CONFIGS:
        results[filter_name] = {}
        for period_name, start, end in PERIODS:
            run_count += 1
            r = run_single(base_params, filter_kwargs, start, end,
                          saved_prices, saved_portfolio, saved_factors)
            stats = analyze_fixed_capital(r, base_params.initial_capital, base_params.portfolio_size)
            results[filter_name][period_name] = stats
            if run_count % 10 == 0:
                print(f"  진행: {run_count}/{total_runs}")

    print(f"  완료: {total_runs}회\n")

    baseline = results["베이스라인"]

    # ═══════════════════════════════════════════════════════
    # 1. 거래당 평균 수익률 (가장 중요한 지표)
    # ═══════════════════════════════════════════════════════
    print("=" * 120)
    print("1. 거래당 평균 수익률 (%) - 복리 무관, 필터의 순수 엣지")
    print("=" * 120)
    period_names = [p[0] for p in PERIODS]
    print(f"  {'필터':>35} |" + "".join(f" {pn:>9} |" for pn in period_names) + "  일관성")
    print(f"  {'-' * 35}-+" + "+".join(f"-{'-' * 9}-" for _ in period_names) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>35} |"
        yearly_improvements = []
        for pn in period_names:
            val = results[filter_name][pn]['avg_profit_rate']
            base_val = baseline[pn]['avg_profit_rate']
            if pn != "전체":
                yearly_improvements.append(val > base_val)
            row += f" {val:>+8.2f}% |"
        if filter_name != "베이스라인":
            c = sum(yearly_improvements)
            row += f"  {c}/4"
            if c == 4: row += " ***"
            elif c == 3: row += " **"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 2. 승률
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("2. 승률 (%)")
    print("=" * 120)
    print(f"  {'필터':>35} |" + "".join(f" {pn:>9} |" for pn in period_names) + "  일관성")
    print(f"  {'-' * 35}-+" + "+".join(f"-{'-' * 9}-" for _ in period_names) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>35} |"
        yearly_improvements = []
        for pn in period_names:
            val = results[filter_name][pn]['win_rate']
            base_val = baseline[pn]['win_rate']
            if pn != "전체":
                yearly_improvements.append(val > base_val)
            row += f" {val:>8.1f}% |"
        if filter_name != "베이스라인":
            c = sum(yearly_improvements)
            row += f"  {c}/4"
            if c == 4: row += " ***"
            elif c == 3: row += " **"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 3. 총 실현손익 (고정 자본 기준)
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("3. 총 실현손익 (만원, 고정자본 5천만원 기준)")
    print("=" * 120)
    print(f"  {'필터':>35} |" + "".join(f" {pn:>9} |" for pn in period_names) + "  일관성")
    print(f"  {'-' * 35}-+" + "+".join(f"-{'-' * 9}-" for _ in period_names) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>35} |"
        yearly_improvements = []
        for pn in period_names:
            val = results[filter_name][pn]['total_pnl'] / 10000  # 만원
            base_val = baseline[pn]['total_pnl'] / 10000
            if pn != "전체":
                yearly_improvements.append(val > base_val)
            row += f" {val:>+8.0f}만 |"
        if filter_name != "베이스라인":
            c = sum(yearly_improvements)
            row += f"  {c}/4"
            if c == 4: row += " ***"
            elif c == 3: row += " **"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 4. 거래수 + 평균 보유일
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("4. 거래수 / 평균 보유일")
    print("=" * 120)
    print(f"  {'필터':>35} |" + "".join(f" {pn:>9} |" for pn in period_names) + "  감소율")
    print(f"  {'-' * 35}-+" + "+".join(f"-{'-' * 9}-" for _ in period_names) + "+--------")

    for filter_name in results:
        row = f"  {filter_name:>35} |"
        for pn in period_names:
            t = results[filter_name][pn]['trades']
            h = results[filter_name][pn]['avg_hold_days']
            row += f" {t:>4}/{h:>3.1f}d |"
        if filter_name != "베이스라인":
            total_t = results[filter_name]["전체"]['trades']
            base_t = baseline["전체"]['trades']
            reduction = (1 - total_t / base_t) * 100 if base_t > 0 else 0
            row += f"  {reduction:>4.0f}%"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 5. Profit Factor + 최대 연속 손실
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("5. Profit Factor / 최대 연속 손실")
    print("=" * 120)
    print(f"  {'필터':>35} |" + "".join(f" {pn:>9} |" for pn in period_names))
    print(f"  {'-' * 35}-+" + "+".join(f"-{'-' * 9}-" for _ in period_names) + "+")

    for filter_name in results:
        row = f"  {filter_name:>35} |"
        for pn in period_names:
            pf = results[filter_name][pn]['profit_factor']
            mcl = results[filter_name][pn]['max_consecutive_loss']
            pf_str = f"{pf:.2f}" if pf < 100 else "99+"
            row += f" {pf_str:>4}/{mcl:>2}연패 |"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 6. 평균 수익/손실 비율
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("6. 평균 수익 vs 평균 손실 (%) - 전체 기간")
    print("=" * 120)
    print(f"  {'필터':>35} | {'평균승리':>8} | {'평균패배':>8} | {'승/패비':>7} | {'기대값':>8}")
    print(f"  {'-' * 35}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 7}-+-{'-' * 8}")

    for filter_name in results:
        s = results[filter_name]["전체"]
        avg_w = s['avg_win_rate']
        avg_l = s['avg_loss_rate']
        ratio = abs(avg_w / avg_l) if avg_l != 0 else 999
        # 기대값 = 승률*평균승리 + (1-승률)*평균패배
        wr = s['win_rate'] / 100
        expected = wr * avg_w + (1 - wr) * avg_l
        print(f"  {filter_name:>35} | {avg_w:>+7.2f}% | {avg_l:>+7.2f}% | {ratio:>6.2f}x | {expected:>+7.2f}%")

    # ═══════════════════════════════════════════════════════
    # 7. 최종 판정
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("7. 최종 판정 (고정 자본 기준)")
    print("=" * 120)

    for filter_name in results:
        if filter_name == "베이스라인":
            continue

        # 연도별 개선 체크
        pnl_improvements = []
        wr_improvements = []
        rate_improvements = []
        for pn in [p[0] for p in PERIODS if p[0] != "전체"]:
            pnl_improvements.append(
                results[filter_name][pn]['total_pnl'] > baseline[pn]['total_pnl'])
            wr_improvements.append(
                results[filter_name][pn]['win_rate'] > baseline[pn]['win_rate'])
            rate_improvements.append(
                results[filter_name][pn]['avg_profit_rate'] > baseline[pn]['avg_profit_rate'])

        pnl_c = sum(pnl_improvements)
        wr_c = sum(wr_improvements)
        rate_c = sum(rate_improvements)

        total_t = results[filter_name]["전체"]['trades']
        base_t = baseline["전체"]['trades']
        reduction = (1 - total_t / base_t) * 100 if base_t > 0 else 0

        total_pnl = results[filter_name]["전체"]['total_pnl']
        base_pnl = baseline["전체"]['total_pnl']
        pnl_diff = total_pnl - base_pnl

        if reduction > 70:
            verdict = "과적합 위험"
        elif pnl_c == 4 and reduction < 50:
            verdict = "강력 추천"
        elif pnl_c >= 3 and reduction < 50:
            verdict = "추천"
        elif pnl_c >= 3:
            verdict = "조건부"
        elif pnl_c == 2:
            verdict = "불안정"
        else:
            verdict = "비추천"

        print(f"  {filter_name:>35} | 손익 {pnl_c}/4 | 승률 {wr_c}/4 | 수익률 {rate_c}/4 | "
              f"거래 -{reduction:.0f}% | 총손익차이 {pnl_diff / 10000:>+8.0f}만원 | {verdict}")

    elapsed = time.time() - total_start
    print(f"\n  총 소요 시간: {elapsed:.0f}초")


if __name__ == '__main__':
    main()
