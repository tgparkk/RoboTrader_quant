#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 점수 vs 승률·수익률 관계 + 임계값 극단 검증

1. 임계값을 극단(buy_min=95, hard_stop=80, safe_score=95 등)까지 밀어서
   멀티버스가 실제로 파라미터를 반영하는지 증명
2. V100 실전 거래 273건에서 매수 시점 value_score → 승/패/수익 관계
"""
import sys
import time
import logging
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot, TradeAction


def params(buy_min=65, hard_stop=65, soft_stop=67, safe_score=75, safe_rank=25):
    return BacktestParams(
        initial_capital=10_000_000, portfolio_size=10,
        target_profit_rate=0.12, stop_loss_rate=0.06,
        hard_stop_score=hard_stop, soft_stop_score=soft_stop,
        soft_stop_rank=30, safe_score=safe_score, safe_rank=safe_rank,
        buy_min_score=buy_min, min_hold_days=0, use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )


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
                         'rank': rank, 'total_score': ts, 'reason': f'{ts:.1f}'})
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


def run_bt(start, end, factors, portfolio, prices, p):
    bt = Backtester(params=p)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors
    bt.capital = p.initial_capital

    s_ymd = start.replace("-", "")
    e_ymd = end.replace("-", "")
    trading_days = [f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    for ymd in sorted(factors.keys()) if s_ymd <= ymd <= e_ymd]
    logging.disable(logging.CRITICAL)
    try:
        prev = p.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)
            total = bt._calculate_total_value(date)
            dr = (total - prev) / prev if prev > 0 else 0
            cum = (total - p.initial_capital) / p.initial_capital
            bt.daily_snapshots.append(DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total - bt.capital,
                total_value=total, position_count=len(bt.positions),
                daily_return=dr, cumulative_return=cum,
            ))
            prev = total
        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start, end, len(trading_days))
    finally:
        logging.disable(logging.NOTSET)
    return result, bt.trades


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  V100 점수 vs 승률·수익 + 임계값 극단 검증 (자본 1,000만원)")
    emit("=" * 130)

    print("\n[로드]", flush=True)
    t0 = time.time()
    loader = Backtester(params=params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    fc, pc = build_v100_cache(saved_factors, saved_portfolio)
    emit(f"  {time.time()-t0:.1f}초")

    # ═══════════════════════════════════════════════
    # 1. 임계값 극단 검증
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit("[1] 임계값 극단 검증 (멀티버스 작동 증명)")
    emit("=" * 130)
    emit("")

    def test(label, p):
        r, _ = run_bt("2024-04-01", "2026-04-09", fc, pc, prices, p)
        profit = r.final_total_value - 10_000_000
        emit(f"  {label:<40} | 최종 {r.final_total_value/10000:>6,.0f}만 | "
              f"수익 {profit/10000:>+5,.0f}만 | 거래 {r.total_trades:>4}")
        return r

    emit("baseline:")
    r_base = test("baseline (buy_min=65, hs=65, ss=67, safe=75)", params())

    emit("")
    emit("[buy_min_score 극단 - value_score 이 점수 이상만 매수]:")
    for bm in [90, 93, 95, 97, 99]:
        test(f"buy_min={bm}", params(buy_min=bm))

    emit("")
    emit("[hard_stop_score 극단 - value_score 이 점수 미만 강제 매도]:")
    for hs in [65, 75, 80, 85, 90]:
        test(f"hard_stop={hs}/soft={hs+2}", params(hard_stop=hs, soft_stop=hs+2))

    emit("")
    emit("[safe_score 극단 - value_score 이 점수 이상만 보호]:")
    for sc in [75, 85, 90, 95, 99]:
        test(f"safe_score={sc}", params(safe_score=sc))

    # ═══════════════════════════════════════════════
    # 2. 점수-수익 상관 분석
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit("[2] 매수 시점 value_score vs 수익률")
    emit("=" * 130)

    _, trades = run_bt("2024-04-01", "2026-04-09", fc, pc, prices, params())

    open_buys = defaultdict(list)
    pairs = []
    for t in trades:
        if t.action == TradeAction.BUY:
            open_buys[t.stock_code].append(t)
        else:
            if open_buys[t.stock_code]:
                b = open_buys[t.stock_code].pop(0)
                pairs.append((b, t))

    import bisect
    sorted_calc_dates = sorted(fc.keys())
    rows = []
    for b, s in pairs:
        buy_date_ymd = b.date.replace("-", "")
        idx = bisect.bisect_left(sorted_calc_dates, buy_date_ymd)
        if idx == 0:
            continue
        prev_calc = sorted_calc_dates[idx - 1]
        f_data = fc.get(prev_calc, {}).get(b.stock_code)
        if not f_data:
            continue
        rows.append({
            'value_score': f_data.get('total_score', 0),
            'rank': f_data.get('factor_rank', 999),
            'profit_rate': s.profit_rate,
            'win': s.profit_rate > 0,
        })

    df = pd.DataFrame(rows)
    emit("")
    emit(f"총 거래 {len(df)}건, 평균 매수 value_score = {df['value_score'].mean():.1f}")
    emit(f"전체 승률 {df['win'].mean():.1%}, 평균 수익률 {df['profit_rate'].mean()*100:+.2f}%")

    emit("")
    emit("[value_score 구간별]")
    emit(f"  {'구간':<12} | {'N':>5} | {'승률':>7} | {'평균수익':>10} | {'평균승리':>10} | {'평균손실':>10}")
    emit("  " + "-" * 75)
    for lo, hi in [(0,85), (85,90), (90,93), (93,95), (95,97), (97,100)]:
        sub = df[(df['value_score'] >= lo) & (df['value_score'] < hi)]
        if len(sub) < 1: continue
        wr = sub['win'].mean()
        avg = sub['profit_rate'].mean() * 100
        w = sub[sub['win']]['profit_rate']
        l = sub[~sub['win']]['profit_rate']
        aw = w.mean() * 100 if len(w) else 0
        al = l.mean() * 100 if len(l) else 0
        emit(f"  {lo:>3}~{hi:<3}점     | {len(sub):>5d} | {wr:>6.1%} | {avg:>+8.2f}% | {aw:>+8.2f}% | {al:>+8.2f}%")

    emit("")
    emit("[rank 구간별 (V100 순위)]")
    emit(f"  {'구간':<12} | {'N':>5} | {'승률':>7} | {'평균수익':>10}")
    emit("  " + "-" * 50)
    for lo, hi in [(1,4), (4,7), (7,11), (11,20), (20,50)]:
        sub = df[(df['rank'] >= lo) & (df['rank'] < hi)]
        if len(sub) < 1: continue
        wr = sub['win'].mean()
        avg = sub['profit_rate'].mean() * 100
        emit(f"  rank {lo:>2}~{hi-1:<2}    | {len(sub):>5d} | {wr:>6.1%} | {avg:>+8.2f}%")

    emit("")
    emit("[상관계수]")
    corr_s = df['value_score'].corr(df['profit_rate'])
    corr_r = df['rank'].corr(df['profit_rate'])
    emit(f"  value_score vs profit_rate: r = {corr_s:+.3f}")
    emit(f"  rank        vs profit_rate: r = {corr_r:+.3f}")
    emit("  (|r| < 0.1: 상관 거의 없음, |r| > 0.3: 유의)")

    out_path = Path("results/v100_score_vs_winrate.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == '__main__':
    main()
