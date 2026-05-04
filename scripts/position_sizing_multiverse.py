#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
종목당 자본비율 멀티버스

score_momentum 필터로 빈 슬롯이 많을 때,
종목당 배분 금액을 늘리면 총수익이 어떻게 변하는지 검증.

축:
  - score_momentum_min: None, 0.5, 1.0
  - portfolio_size: 5, 7, 8, 10, 12, 15 (종목당 자본 = 5천만/size)
  - ret_20d_max: None, 60

고정자본 기준으로 분석 (복리 제거)
"""
import sys
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


PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026", "2026-01-01", "2026-04-07"),
    ("전체", "2023-01-01", "2026-04-07"),
]

# 탐색 축
SCORE_MOM_VALUES = [None, 0.5, 1.0]
PORTFOLIO_SIZES = [5, 7, 8, 10, 12, 15]
RET20D_VALUES = [None, 60]


def make_params(portfolio_size):
    return BacktestParams(
        initial_capital=50_000_000,
        portfolio_size=portfolio_size,
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
    """고정자본 분석: 종목당 initial_capital/portfolio_size"""
    fixed_per_stock = initial_capital / portfolio_size

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
        return {'trades': 0, 'wins': 0, 'win_rate': 0, 'avg_profit_rate': 0,
                'total_pnl': 0, 'profit_factor': 0, 'max_consecutive_loss': 0}

    wins = losses = 0
    all_rates = []
    total_pnl = total_win = total_loss = 0
    consecutive_losses = max_consecutive = 0

    for buy_t, sell_t in pairs:
        prate = sell_t.profit_rate
        net_pnl = fixed_per_stock * prate - fixed_per_stock * 0.0026
        total_pnl += net_pnl
        all_rates.append(prate * 100)

        if prate > 0:
            wins += 1
            total_win += net_pnl
            consecutive_losses = 0
        else:
            losses += 1
            total_loss += abs(net_pnl)
            consecutive_losses += 1
            max_consecutive = max(max_consecutive, consecutive_losses)

    n = wins + losses
    return {
        'trades': n,
        'wins': wins,
        'win_rate': wins / n * 100 if n > 0 else 0,
        'avg_profit_rate': np.mean(all_rates) if all_rates else 0,
        'total_pnl': total_pnl,
        'profit_factor': total_win / total_loss if total_loss > 0 else 999,
        'max_consecutive_loss': max_consecutive,
    }


def main():
    print(f"{'#' * 120}")
    print(f"  종목당 자본비율 멀티버스")
    print(f"  자본: 5천만원 고정, portfolio_size별 종목당 배분액 변동")
    print(f"  축: score_momentum x portfolio_size x ret_20d_max")
    print(f"{'#' * 120}")

    total_start = time.time()

    # 데이터 1회 로드 (최대 portfolio_size로)
    print("\n데이터 로딩 중...")
    base = make_params(max(PORTFOLIO_SIZES))
    loader = Backtester(params=base)
    start_norm = loader._normalize_date("2023-01-01")
    end_norm = loader._normalize_date("2026-04-07")
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    # 전체 결과
    all_results = []
    total_combos = len(SCORE_MOM_VALUES) * len(PORTFOLIO_SIZES) * len(RET20D_VALUES) * len(PERIODS)
    run_count = 0

    for sm in SCORE_MOM_VALUES:
        for ret20d in RET20D_VALUES:
            for ps in PORTFOLIO_SIZES:
                params = make_params(ps)
                filter_kwargs = {}
                if sm is not None:
                    filter_kwargs['score_momentum_min'] = sm
                if ret20d is not None:
                    filter_kwargs['ret_20d_max'] = ret20d

                label = f"sm={sm or 'OFF'}|ps={ps}|ret20d={ret20d or 'OFF'}"
                per_stock = 50_000_000 / ps

                period_results = {}
                for period_name, start, end in PERIODS:
                    run_count += 1
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

                    stats = analyze_fixed_capital(result, params.initial_capital, ps)
                    period_results[period_name] = stats

                    if run_count % 20 == 0:
                        print(f"  진행: {run_count}/{total_combos}")

                all_results.append({
                    'label': label,
                    'sm': sm,
                    'ps': ps,
                    'ret20d': ret20d,
                    'per_stock': per_stock,
                    'periods': period_results,
                })

    print(f"  완료: {run_count}회\n")

    # ═══════════════════════════════════════════════════════
    # 1. 총 실현손익 매트릭스 (핵심)
    # ═══════════════════════════════════════════════════════
    for ret20d in RET20D_VALUES:
        ret_label = f"ret20d<={ret20d}" if ret20d else "ret20d=OFF"
        print(f"\n{'=' * 120}")
        print(f"총 실현손익 (만원, 고정자본 기준) — {ret_label}")
        print(f"{'=' * 120}")

        # 헤더
        col_header = "sm / ps"
        header = f"  {col_header:>12} |"
        for ps in PORTFOLIO_SIZES:
            per = int(50_000_000 / ps / 10000)
            header += f" {ps}종목({per}만) |"
        print(header)
        print(f"  {'-' * 12}-+" + "+".join(f"-{'-' * 12}-" for _ in PORTFOLIO_SIZES) + "+")

        for sm in SCORE_MOM_VALUES:
            sm_label = f"sm>={sm}" if sm is not None else "OFF"
            row = f"  {sm_label:>12} |"
            for ps in PORTFOLIO_SIZES:
                match = [r for r in all_results
                         if r['sm'] == sm and r['ps'] == ps and r['ret20d'] == ret20d]
                if match:
                    pnl = match[0]['periods']['전체']['total_pnl'] / 10000
                    row += f" {pnl:>+10.0f}만 |"
                else:
                    row += f" {'N/A':>11} |"
            print(row)

    # ═══════════════════════════════════════════════════════
    # 2. 연도별 일관성 (총손익)
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print(f"연도별 총손익 (만원) — 상위 조합")
    print(f"{'=' * 120}")

    # 전체 손익 기준 정렬
    ranked = sorted(all_results, key=lambda r: r['periods']['전체']['total_pnl'], reverse=True)

    header = f"  {'조합':>30} | {'종목당':>7} |"
    for pn in ['2023', '2024', '2025', '2026', '전체']:
        header += f" {pn:>8} |"
    header += " 일관성"
    print(header)
    print(f"  {'-' * 30}-+-{'-' * 7}-+" + "+".join(f"-{'-' * 8}-" for _ in range(5)) + "+--------")

    # 베이스라인 찾기 (sm=OFF, ps=10, ret20d=OFF)
    baseline = [r for r in all_results if r['sm'] is None and r['ps'] == 10 and r['ret20d'] is None]
    baseline_pnls = {pn: baseline[0]['periods'][pn]['total_pnl'] if baseline else 0
                     for pn in ['2023', '2024', '2025', '2026', '전체']}

    for r in ranked[:25]:
        label = r['label']
        per_stock = int(r['per_stock'] / 10000)
        row = f"  {label:>30} | {per_stock:>5}만 |"
        yearly_better = []
        for pn in ['2023', '2024', '2025', '2026', '전체']:
            pnl = r['periods'][pn]['total_pnl'] / 10000
            row += f" {pnl:>+7.0f}만 |"
            if pn != '전체':
                yearly_better.append(pnl > baseline_pnls.get(pn, 0) / 10000)
        c = sum(yearly_better)
        row += f"  {c}/4"
        if c == 4: row += " ***"
        elif c == 3: row += " **"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 3. 승률 + 거래수 + PF 매트릭스
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print(f"승률 / 거래수 / PF — 전체 기간 (ret20d=OFF)")
    print(f"{'=' * 120}")

    header = f"  {col_header:>12} |"
    for ps in PORTFOLIO_SIZES:
        header += f" {ps}종목       |"
    print(header)
    print(f"  {'-' * 12}-+" + "+".join(f"-{'-' * 13}-" for _ in PORTFOLIO_SIZES) + "+")

    for sm in SCORE_MOM_VALUES:
        sm_label = f"sm>={sm}" if sm is not None else "OFF"
        row = f"  {sm_label:>12} |"
        for ps in PORTFOLIO_SIZES:
            match = [r for r in all_results
                     if r['sm'] == sm and r['ps'] == ps and r['ret20d'] is None]
            if match:
                s = match[0]['periods']['전체']
                row += f" {s['win_rate']:>4.0f}%/{s['trades']:>4}/{s['profit_factor']:>4.1f} |"
            else:
                row += f" {'N/A':>13} |"
        print(row)

    # ═══════════════════════════════════════════════════════
    # 4. 최종 추천
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print(f"최종 추천 (총손익 상위, 4/4 또는 3/4 일관성)")
    print(f"{'=' * 120}")

    for r in ranked[:15]:
        yearly_better = []
        for pn in ['2023', '2024', '2025', '2026']:
            pnl = r['periods'][pn]['total_pnl']
            yearly_better.append(pnl > baseline_pnls.get(pn, 0))
        c = sum(yearly_better)
        total_pnl = r['periods']['전체']['total_pnl'] / 10000
        s = r['periods']['전체']

        if c >= 3:
            verdict = "추천" if c == 3 else "강력추천"
        elif c == 2:
            verdict = "불안정"
        else:
            verdict = "-"

        if s['trades'] < 300:
            verdict += " (거래부족)"

        print(f"  {r['label']:>35} | 총손익 {total_pnl:>+8.0f}만 | "
              f"승률 {s['win_rate']:>4.1f}% | 거래 {s['trades']:>4} | PF {s['profit_factor']:>4.2f} | "
              f"일관 {c}/4 | {verdict}")

    elapsed = time.time() - total_start
    print(f"\n  총 소요 시간: {elapsed:.0f}초")


if __name__ == '__main__':
    main()
