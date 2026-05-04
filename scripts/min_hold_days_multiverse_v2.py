#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
최소 보유 기간 멀티버스 — 강제 회전율 감소

V100 + TP12/SL6 + 10종목 + buy_min=65 고정.
min_hold_days만 변경: 0/5/10/15/20/30/60일

min_hold_days 의미:
  - 매수 후 N일 이내에는 리밸런싱 매도 차단 (점수 떨어져도 보유)
  - TP/SL은 항상 작동 (이건 별도 처리)
"""
import sys
import time
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


PERIODS = [
    ("2024-04~2025-06 (15개월)", "2024-04-01", "2025-06-30"),
    ("2025-07~2026-04 (9개월)",  "2025-07-01", "2026-04-09"),
    ("전체 2년",                 "2024-04-01", "2026-04-09"),
]


def common_params(min_hold=0, **ov):
    base = dict(
        initial_capital=10_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        min_hold_days=min_hold,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )
    base.update(ov)
    return BacktestParams(**base)


def build_v100_cache(saved_factors, saved_portfolio):
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])
    new_factors, new_portfolio = {}, {}
    for calc_date, stocks in saved_factors.items():
        scored = []
        new_stocks = {}
        for code, f in stocks.items():
            nt = f.get('value_score', 0)
            nf = dict(f)
            nf['total_score'] = nt
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, nt))
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks
        port = []
        for rank, (code, ts) in enumerate(scored[:50], 1):
            port.append({'calc_date': calc_date, 'stock_code': code,
                         'stock_name': stock_names.get(code, code),
                         'rank': rank, 'total_score': ts, 'reason': f'V100 {ts:.1f}'})
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


def run_bt(start, end, factors, portfolio, prices, params):
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors
    bt.capital = params.initial_capital

    s_ymd = start.replace("-", "")
    e_ymd = end.replace("-", "")
    trading_days = [f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    for ymd in sorted(factors.keys()) if s_ymd <= ymd <= e_ymd]
    if not trading_days:
        return None
    logging.disable(logging.CRITICAL)
    try:
        prev = params.initial_capital
        for date in trading_days:
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
        bt._close_all_positions(trading_days[-1])
        return bt._create_result(start, end, len(trading_days))
    finally:
        logging.disable(logging.NOTSET)


def kospi_returns_money(prices, initial=10_000_000):
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            ratio = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close'])
            out[tag] = {'return': ratio - 1, 'final': initial * ratio, 'profit': initial * (ratio - 1)}
    return out


HOLD_DAYS = [0, 5, 10, 15, 20, 30, 60]


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  최소 보유 기간 멀티버스 (V100 + TP12/SL6 + 10종목, min_hold_days만 변경)")
    emit("  (자본 1,000만원 기준)")
    emit("=" * 130)

    print("\n[1/2] 데이터 + V100 cache...", flush=True)
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    fc, pc = build_v100_cache(saved_factors, saved_portfolio)
    emit(f"  {time.time()-t0:.1f}초")

    k = kospi_returns_money(prices)
    emit("")
    emit("[KOSPI B&H - 천만원 기준]")
    for tag, s, e in PERIODS:
        r = k.get(tag)
        if r:
            emit(f"  {tag:<28}  1,000만 -> {r['final']/10000:,.0f}만 ({r['return']:+.1%})")

    print("\n[2/2] min_hold_days별 백테스트...", flush=True)
    t1 = time.time()
    emit("")
    emit("=" * 130)
    emit(f"{'min_hold':<10} | {'구간':<28} | {'최종':>10} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    emit("-" * 130)

    results = []
    for hd in HOLD_DAYS:
        row = {'min_hold': hd}
        label = f"{hd}일" if hd > 0 else "0일(현행)"
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params(min_hold=hd))
            row[tag] = r
            profit = r.final_total_value - 10_000_000
            k_prof = k.get(tag, {}).get('profit', 0)
            diff = profit - k_prof
            emit(f"{label:<10} | {tag:<28} | {r.final_total_value/10000:>8,.0f}만 | "
                  f"{profit/10000:>+8,.0f}만 | {r.total_return:>+7.1%} | "
                  f"{diff/10000:>+8,.0f}만 | {r.total_trades:>6d}")
        emit("")
        results.append(row)

    emit(f"총 {time.time()-t1:.1f}초")

    # 순위
    emit("")
    emit("=" * 130)
    emit("전체 2년 기준 순위 (KOSPI 대비 알파)")
    emit("=" * 130)
    k_all = k.get("전체 2년", {}).get('profit', 0)
    sorted_res = sorted(results, key=lambda r: r["전체 2년"].total_return, reverse=True)
    emit(f"{'순위':>4} {'min_hold':<10} | {'최종':>10} | {'수익':>10} | {'KOSPI차':>10} | {'거래수':>6}")
    for i, r in enumerate(sorted_res, 1):
        res = r["전체 2년"]
        profit = res.final_total_value - 10_000_000
        diff = profit - k_all
        marker = " ★" if r['min_hold'] == 0 else ""
        label = f"{r['min_hold']}일"
        emit(f"{i:>4} {label:<10}{marker} | {res.final_total_value/10000:>8,.0f}만 | "
              f"{profit/10000:>+8,.0f}만 | {diff/10000:>+8,.0f}만 | {res.total_trades:>6d}")

    out = Path("results/min_hold_days_v2.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
