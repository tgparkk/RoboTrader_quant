#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 전환 후 임계값 재보정 멀티버스

V100 + TP12/SL6 + 10종목 + min_hold_days=0 고정.
buy_min_score / hard_stop_score / safe_score 조합 탐색.

순차 최적화:
  Phase 1: buy_min_score 단축 (65/70/75/80/85)  - 다른 값은 현행
  Phase 2: Phase 1 최적 + hard_stop_score 단축 (45/50/55/60/65)
  Phase 3: 위 최적 + safe_score 단축 (75/80/85/90)
  Phase 4: 최적 조합 확인

자본 1,000만원 기준.
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


def params(buy_min, hard_stop, soft_stop, safe_score, safe_rank=25):
    return BacktestParams(
        initial_capital=10_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=hard_stop,
        soft_stop_score=soft_stop,
        soft_stop_rank=30,
        safe_score=safe_score,
        safe_rank=safe_rank,
        buy_min_score=buy_min,
        min_hold_days=0,
        use_dynamic_targets=False,
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
    if not trading_days:
        return None
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
        return bt._create_result(start, end, len(trading_days))
    finally:
        logging.disable(logging.NOTSET)


def kospi_money(prices, initial=10_000_000):
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


def test_config(fc, pc, prices, buy_min, hard_stop, soft_stop, safe_score, k_all):
    """해당 설정으로 3기간 백테스트 결과 반환"""
    p = params(buy_min, hard_stop, soft_stop, safe_score)
    outputs = {}
    for tag, s, e in PERIODS:
        r = run_bt(s, e, fc, pc, prices, p)
        outputs[tag] = r
    all_profit = outputs["전체 2년"].final_total_value - 10_000_000
    alpha = all_profit - k_all
    return outputs, alpha


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  V100 임계값 재보정 멀티버스 (자본 1,000만원)")
    emit("=" * 130)

    print("\n[로드]", flush=True)
    t0 = time.time()
    loader = Backtester(params=params(65, 65, 67, 75))
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    fc, pc = build_v100_cache(saved_factors, saved_portfolio)
    emit(f"  {time.time()-t0:.1f}초")

    k = kospi_money(prices)
    k_all = k["전체 2년"]['profit']
    emit("")
    emit(f"KOSPI 2년: 1,000만 -> {k['전체 2년']['final']/10000:,.0f}만 (+{k_all/10000:,.0f}만)")
    emit("")

    def report_row(label, outputs, alpha):
        parts = [f"{label:<32}"]
        for tag, _, _ in PERIODS:
            r = outputs[tag]
            profit = r.final_total_value - 10_000_000
            parts.append(f"{r.final_total_value/10000:>5,.0f}만 ({r.total_return:>+6.1%}, N={r.total_trades})")
        parts.append(f"알파 {alpha/10000:>+6,.0f}만")
        emit(" | ".join(parts))

    # ═══════════════════════════════════════════════
    # Baseline (현행)
    # ═══════════════════════════════════════════════
    emit("=" * 130)
    emit("Baseline (buy_min=65, hard_stop=65, soft_stop=67, safe_score=75)")
    emit("=" * 130)
    base_out, base_alpha = test_config(fc, pc, prices, 65, 65, 67, 75, k_all)
    report_row("Baseline", base_out, base_alpha)

    # ═══════════════════════════════════════════════
    # Phase 1: buy_min_score
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit("Phase 1: buy_min_score 탐색 (hard_stop=65, safe=75 고정)")
    emit("=" * 130)
    p1_results = []
    for bm in [65, 70, 75, 80, 85]:
        out, a = test_config(fc, pc, prices, bm, 65, 67, 75, k_all)
        p1_results.append((bm, out, a))
        report_row(f"buy_min={bm}", out, a)
    best_bm = max(p1_results, key=lambda x: x[2])[0]
    emit(f"→ Phase 1 최적 buy_min_score = {best_bm} (알파 {max(r[2] for r in p1_results)/10000:+.0f}만)")

    # ═══════════════════════════════════════════════
    # Phase 2: hard_stop_score
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit(f"Phase 2: hard_stop_score 탐색 (buy_min={best_bm}, safe=75 고정)")
    emit("=" * 130)
    p2_results = []
    for hs in [45, 50, 55, 60, 65]:
        ss = hs + 2   # soft_stop = hard + 2
        out, a = test_config(fc, pc, prices, best_bm, hs, ss, 75, k_all)
        p2_results.append((hs, out, a))
        report_row(f"hard_stop={hs}/soft={ss}", out, a)
    best_hs = max(p2_results, key=lambda x: x[2])[0]
    emit(f"→ Phase 2 최적 hard_stop_score = {best_hs} (알파 {max(r[2] for r in p2_results)/10000:+.0f}만)")

    # ═══════════════════════════════════════════════
    # Phase 3: safe_score
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit(f"Phase 3: safe_score 탐색 (buy_min={best_bm}, hard_stop={best_hs})")
    emit("=" * 130)
    p3_results = []
    for sc in [70, 75, 80, 85, 90]:
        out, a = test_config(fc, pc, prices, best_bm, best_hs, best_hs+2, sc, k_all)
        p3_results.append((sc, out, a))
        report_row(f"safe_score={sc}", out, a)
    best_sc = max(p3_results, key=lambda x: x[2])[0]
    emit(f"→ Phase 3 최적 safe_score = {best_sc}")

    # ═══════════════════════════════════════════════
    # 최종
    # ═══════════════════════════════════════════════
    emit("")
    emit("=" * 130)
    emit(f"최종 최적: buy_min={best_bm}, hard_stop={best_hs}, soft_stop={best_hs+2}, safe_score={best_sc}")
    emit("=" * 130)
    final_out, final_alpha = test_config(fc, pc, prices, best_bm, best_hs, best_hs+2, best_sc, k_all)
    report_row("최적 조합", final_out, final_alpha)
    emit("")
    emit(f"개선: 알파 {base_alpha/10000:+.0f}만 (baseline) → {final_alpha/10000:+.0f}만 (최적)")
    emit(f"       Δ {(final_alpha - base_alpha)/10000:+.0f}만")

    out_path = Path("results/v100_threshold.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == '__main__':
    main()
