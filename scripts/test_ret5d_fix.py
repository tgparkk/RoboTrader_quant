#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
buy_ret5d_min 필터 look-ahead 수정 전후 비교

A: buy_ret5d_min=None    (필터 제외)
B: buy_ret5d_min=-3.0    (수정된 D-1/D-6 기준)

기간: 최근 2년 (2024-04-01 ~ 2026-04-09)
기타 파라미터는 실전 운영값과 일치
"""
import sys
import time
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams

START_DATE = "2024-04-01"
END_DATE = "2026-04-09"


def make_params(buy_ret5d_min):
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
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
        buy_ret5d_min=buy_ret5d_min,
    )


def run(label, buy_ret5d_min, saved_prices, saved_portfolio, saved_factors,
        trading_days, start_norm, end_norm):
    params = make_params(buy_ret5d_min)
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = saved_prices
    bt.portfolio_cache = saved_portfolio
    bt.factors_cache = saved_factors
    bt.capital = params.initial_capital

    logging.disable(logging.CRITICAL)
    try:
        result = bt.backtest(start_norm, end_norm)
    finally:
        logging.disable(logging.NOTSET)

    return {
        'label': label,
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'annualized': result.annualized_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
        'final_value': result.final_total_value,
        'trading_cost': result.total_trading_cost,
    }


def main():
    print("=" * 90)
    print(f"  buy_ret5d_min 수정 영향 측정  ({START_DATE} ~ {END_DATE})")
    print("=" * 90)
    print("  공통: TP12/SL6, portfolio=10, buy_min_score=65, slippage=0.25% (실측), cooldown=3일")
    print()

    print("데이터 로딩 중...")
    t0 = time.time()
    loader = Backtester(params=make_params(None))
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드: {len(trading_days)}거래일, {len(saved_prices)}종목, {len(saved_factors)}일 팩터 "
          f"({time.time()-t0:.1f}초)\n")

    scenarios = [
        ("A: 필터 제외 (ret5d=None)", None),
        ("B: 수정된 필터 (ret5d=-3.0, D-1/D-6 기준)", -3.0),
    ]

    results = []
    for label, ret5d in scenarios:
        t0 = time.time()
        print(f"▶ {label} 시뮬 중...")
        r = run(label, ret5d, saved_prices, saved_portfolio, saved_factors,
                trading_days, start_norm, end_norm)
        results.append(r)
        print(f"  완료 ({time.time()-t0:.1f}초)\n")

    # 결과 출력
    print("=" * 90)
    print("결과 비교")
    print("=" * 90)
    print(f"{'지표':<18}  {'A: 필터 제외':>18}  {'B: 수정된 필터':>18}  {'B - A':>12}")
    print("-" * 90)

    a, b = results[0], results[1]
    rows = [
        ('총 수익률',      f"{a['total_return']:.1%}",      f"{b['total_return']:.1%}",
         f"{(b['total_return']-a['total_return'])*100:+.1f}%p"),
        ('연환산 수익률',  f"{a['annualized']:.1%}",        f"{b['annualized']:.1%}",
         f"{(b['annualized']-a['annualized'])*100:+.1f}%p"),
        ('샤프 비율',      f"{a['sharpe']:.2f}",            f"{b['sharpe']:.2f}",
         f"{b['sharpe']-a['sharpe']:+.2f}"),
        ('MDD',           f"{a['mdd']:.1%}",               f"{b['mdd']:.1%}",
         f"{(b['mdd']-a['mdd'])*100:+.1f}%p"),
        ('승률',           f"{a['win_rate']:.1%}",          f"{b['win_rate']:.1%}",
         f"{(b['win_rate']-a['win_rate'])*100:+.1f}%p"),
        ('Profit Factor',  f"{a['pf']:.2f}",                f"{b['pf']:.2f}",
         f"{b['pf']-a['pf']:+.2f}"),
        ('총 거래 수',     f"{a['trades']}",                f"{b['trades']}",
         f"{b['trades']-a['trades']:+d}"),
        ('최종 자산',      f"{a['final_value']:,.0f}",      f"{b['final_value']:,.0f}",
         f"{b['final_value']-a['final_value']:+,.0f}"),
    ]
    for name, av, bv, diff in rows:
        print(f"{name:<18}  {av:>18}  {bv:>18}  {diff:>12}")

    print("=" * 90)


if __name__ == '__main__':
    main()
