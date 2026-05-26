#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
정본 V100 sharpe 2.48 재현 검증.

memory v100_multiverse_corrected_20260507:
  - 운영 backtester, 2023-2026 (~3.3년)
  - 수정 후 baseline (V100, 게이트 OFF, TP12/SL6): sharpe +1.93, +164%, 거래 192
  - + M30/R30 게이트, TP12/SL6 = 현행 운영: sharpe +2.48, +236.7%, 거래 173

목적: 여러 base 변형을 돌려서 정본 수치 (sharpe 1.93~2.48) 재현되는 변형 식별.
"""
import sys
import time
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from scripts.v100_threshold_multiverse import build_v100_cache


def make_params(**kwargs):
    """기본 base + override."""
    defaults = dict(
        initial_capital=10_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=95.0,
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )
    defaults.update(kwargs)
    return BacktestParams(**defaults)


def run_bt(params, factors, portfolio, prices, start, end, label):
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors

    s_ymd = start.replace("-", "")
    e_ymd = end.replace("-", "")
    trading_days = sorted([d for d in factors.keys() if s_ymd <= d <= e_ymd])
    if not trading_days:
        print(f"[{label}] 거래일 없음")
        return None
    trading_days_iso = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in trading_days]
    logging.disable(logging.CRITICAL)
    try:
        prev = params.initial_capital
        for date in trading_days_iso:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)
            total = bt._calculate_total_value(date)
            dr = (total - prev) / prev if prev > 0 else 0
            cum = (total - params.initial_capital) / params.initial_capital
            bt.daily_snapshots.append(DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total - bt.capital,
                total_value=total, position_count=len(bt.positions),
                daily_return=dr, cumulative_return=cum,
            ))
            prev = total
        bt._close_all_positions(trading_days_iso[-1])
        return bt._create_result(trading_days_iso[0], trading_days_iso[-1], len(trading_days_iso))
    finally:
        logging.disable(logging.NOTSET)


def main():
    print("=" * 100)
    print("정본 V100 baseline 재현 검증 (목표: sharpe 1.93 게이트 OFF / 2.48 게이트 ON)")
    print("=" * 100)
    print()

    t0 = time.time()
    print("[데이터 로드]")
    loader = Backtester(params=make_params())
    start_iso = loader._normalize_date("2023-01-02")
    end_iso = loader._normalize_date("2026-05-23")
    days = loader._get_trading_days(start_iso, end_iso)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    sf, sp = loader.factors_cache, loader.portfolio_cache

    v100_factors, v100_portfolio = build_v100_cache(sf, sp)
    print(f"  raw cache 종목: {len(prices)}, 거래일: {len(days)}, V100 cache 재구성 완료 ({time.time()-t0:.1f}s)")
    print()

    # value_score 분포 점검
    sample_date = sorted(v100_factors.keys())[-1]
    scores = [f.get('total_score', 0) for f in v100_factors[sample_date].values()]
    scores_sorted = sorted(scores, reverse=True)
    print(f"[{sample_date} V100 점수 분포] n={len(scores)}")
    print(f"  >=99: {sum(1 for s in scores if s >= 99)}개")
    print(f"  >=95: {sum(1 for s in scores if s >= 95)}개")
    print(f"  >=90: {sum(1 for s in scores if s >= 90)}개")
    print(f"  >=80: {sum(1 for s in scores if s >= 80)}개")
    print(f"  Top 20: {[round(s,1) for s in scores_sorted[:20]]}")
    print()

    # raw factor cache (V100 적용 전) 비교
    raw_scores = [f.get('total_score', 0) for f in sf[sample_date].values()]
    raw_sorted = sorted(raw_scores, reverse=True)
    print(f"[{sample_date} raw factor cache 점수 분포] n={len(raw_scores)}")
    print(f"  >=99: {sum(1 for s in raw_scores if s >= 99)}개")
    print(f"  >=95: {sum(1 for s in raw_scores if s >= 95)}개")
    print(f"  >=90: {sum(1 for s in raw_scores if s >= 90)}개")
    print(f"  Top 20: {[round(s,1) for s in raw_sorted[:20]]}")
    print()

    scenarios = [
        ("정본 base: V100 cache + 게이트 OFF + TP12/SL6 + 자본1천만",
         dict(buy_min_score=95.0), v100_factors, v100_portfolio),
        ("정본 base + M30 게이트",
         dict(buy_min_score=95.0, buy_momentum_score_min=30.0), v100_factors, v100_portfolio),
        ("정본 base + M30/R30 게이트 (현행)",
         dict(buy_min_score=95.0, buy_momentum_score_min=30.0, buy_ret20d_max=30.0), v100_factors, v100_portfolio),
        ("정본 base + 전체 게이트(M30/R30/ret5d:-3~17)",
         dict(buy_min_score=95.0, buy_momentum_score_min=30.0, buy_ret20d_max=30.0,
              buy_ret5d_min=-3.0, buy_ret5d_max=17.0), v100_factors, v100_portfolio),
        ("정본 base + rebal_cooldown=0",
         dict(buy_min_score=95.0, rebalancing_sell_cooldown_days=0), v100_factors, v100_portfolio),
        ("정본 base + 자본 5천만",
         dict(buy_min_score=95.0, initial_capital=50_000_000), v100_factors, v100_portfolio),
        ("raw cache (V100 미적용)",
         dict(buy_min_score=95.0), sf, sp),
        ("raw cache + buy_min=65 (옛 hybrid 시대 임계값)",
         dict(buy_min_score=65.0), sf, sp),
    ]

    print(f"{'시나리오':<60} | {'sharpe':>7} {'수익':>8} {'MDD':>6} {'거래':>5} {'승률':>6}")
    print("-" * 100)
    for label, overrides, fc, pc in scenarios:
        params = make_params(**overrides)
        r = run_bt(params, fc, pc, prices, "2023-01-02", "2026-05-23", label)
        if r is None:
            print(f"{label:<60} | {'N/A':>7}")
            continue
        print(f"{label:<60} | {r.sharpe_ratio:>7.2f} {r.total_return:>+7.1%} "
              f"{r.max_drawdown:>5.1%} {r.total_trades:>5d} {r.win_rate:>5.1%}")

    print()
    print(f"전체 소요: {time.time()-t0:.1f}s")
    print("=" * 100)
    print("정본 목표: 게이트 OFF sharpe 1.93/+164%/192거래, 게이트 ON sharpe 2.48/+236.7%/173거래")


if __name__ == '__main__':
    main()
