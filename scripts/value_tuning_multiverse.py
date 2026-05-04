#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Value 중심 튜닝 멀티버스

Phase 1: 팩터 블렌드 (Value 비중 50~100% + Q/G/M 보조)
Phase 2: V100 고정 + TP/SL 그리드
Phase 3: Phase 2 최적 + 포트폴리오 크기

기간: IS (2024-04~2025-06) / OOS (2025-07~2026-04) / ALL (2년)
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
    ("IS ", "2024-04-01", "2025-06-30"),
    ("OOS", "2025-07-01", "2026-04-09"),
    ("ALL", "2024-04-01", "2026-04-09"),
]


def common_params(**ov):
    base = dict(
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
    )
    base.update(ov)
    return BacktestParams(**base)


def rebuild_caches(saved_factors, saved_portfolio, weights, portfolio_top_n=50):
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])

    v_w, m_w, q_w, g_w = weights
    new_factors = {}
    new_portfolio = {}
    for calc_date, stocks in saved_factors.items():
        new_stocks = {}
        scored = []
        for code, f in stocks.items():
            new_total = (
                f.get('value_score', 50) * v_w +
                f.get('momentum_score', 50) * m_w +
                f.get('quality_score', 50) * q_w +
                f.get('growth_score', 50) * g_w
            )
            nf = dict(f)
            nf['total_score'] = new_total
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, new_total))
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks

        port = []
        for rank, (code, tscore) in enumerate(scored[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': tscore,
                'reason': f'w{weights} score {tscore:.1f}',
            })
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
    trading_days = []
    for ymd in sorted(factors.keys()):
        if s_ymd <= ymd <= e_ymd:
            trading_days.append(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")
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


def kospi_returns(prices):
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            ret = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close']) - 1
            out[tag] = ret
    return out


# Phase 1 조합: Value 비중 50~100% + 보조
PHASE1_WEIGHTS = [
    ("V100",            (1.00, 0.00, 0.00, 0.00)),
    ("V90/Q10",         (0.90, 0.00, 0.10, 0.00)),
    ("V80/Q20",         (0.80, 0.00, 0.20, 0.00)),
    ("V70/Q30",         (0.70, 0.00, 0.30, 0.00)),
    ("V60/Q40",         (0.60, 0.00, 0.40, 0.00)),
    ("V50/Q50",         (0.50, 0.00, 0.50, 0.00)),
    ("V80/Q10/G10",     (0.80, 0.00, 0.10, 0.10)),
    ("V70/Q20/G10",     (0.70, 0.00, 0.20, 0.10)),
    ("V70/Q15/G15",     (0.70, 0.00, 0.15, 0.15)),
    ("V80/M10/Q10",     (0.80, 0.10, 0.10, 0.00)),
    ("V60/M10/Q20/G10", (0.60, 0.10, 0.20, 0.10)),
    ("V50/M20/Q20/G10", (0.50, 0.20, 0.20, 0.10)),
]

PHASE2_TP_SL = [
    (tp, sl)
    for tp in [0.08, 0.12, 0.15, 0.20, 0.25]
    for sl in [0.05, 0.06, 0.08, 0.10]
]

PHASE3_PORT = [5, 8, 10, 15, 20]


def main():
    log_lines = []
    def emit(s=""):
        print(s)
        log_lines.append(s)

    emit("=" * 120)
    emit("  Value 중심 튜닝 멀티버스 (clean 팩터, IS/OOS/ALL)")
    emit("=" * 120)

    print("\n데이터 로딩...")
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    emit(f"로드 {time.time()-t0:.1f}초, {len(days)}거래일, {len(saved_factors)}일 팩터\n")

    kospi = kospi_returns(prices)
    emit(f"[KOSPI B&H]  IS {kospi.get('IS ', 0):+.1%}  OOS {kospi.get('OOS', 0):+.1%}  ALL {kospi.get('ALL', 0):+.1%}")
    emit("")

    # ─────────────────────────────────────────────────
    # Phase 1: 팩터 블렌드
    # ─────────────────────────────────────────────────
    emit("=" * 120)
    emit("Phase 1: Value 중심 팩터 블렌드")
    emit("=" * 120)
    hdr = f"{'Weights':<20}  {'IS_Ret':>8} {'IS_Shr':>6}  {'OOS_Ret':>8} {'OOS_Shr':>6}  {'ALL_Ret':>8} {'ALL_Shr':>6} {'ALL_MDD':>7} {'ALL_Tr':>6} {'ALL_Win':>6}  {'OOS_α':>7}"
    emit(hdr)
    emit("-" * 120)

    phase1_results = []
    for label, w in PHASE1_WEIGHTS:
        fc, pc = rebuild_caches(saved_factors, saved_portfolio, w)
        row = {'label': label, 'w': w}
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params())
            row[tag] = r
        alpha = row['OOS'].total_return - kospi.get('OOS', 0)
        row['alpha_oos'] = alpha
        phase1_results.append(row)
        emit(f"{label:<20}  "
              f"{row['IS '].total_return:>7.1%} {row['IS '].sharpe_ratio:>6.2f}  "
              f"{row['OOS'].total_return:>7.1%} {row['OOS'].sharpe_ratio:>6.2f}  "
              f"{row['ALL'].total_return:>7.1%} {row['ALL'].sharpe_ratio:>6.2f} "
              f"{row['ALL'].max_drawdown:>6.1%} {row['ALL'].total_trades:>6d} {row['ALL'].win_rate:>5.1%}  "
              f"{alpha:>+6.1%}")

    # 최고 OOS 알파 조합
    best_p1 = max(phase1_results, key=lambda r: r['alpha_oos'])
    emit(f"\nPhase 1 Best (OOS α 기준): {best_p1['label']}  OOS α {best_p1['alpha_oos']:+.1%}")
    emit("")

    # ─────────────────────────────────────────────────
    # Phase 2: V100 고정 + TP/SL
    # ─────────────────────────────────────────────────
    emit("=" * 120)
    emit("Phase 2: V100 고정 + TP/SL 그리드")
    emit("=" * 120)
    emit(f"{'TP':>4} {'SL':>4}  {'IS_Ret':>8} {'IS_Shr':>6}  {'OOS_Ret':>8} {'OOS_Shr':>6}  {'ALL_Ret':>8} {'ALL_Shr':>6} {'ALL_MDD':>7} {'ALL_Tr':>6}  {'OOS_α':>7}")
    emit("-" * 120)

    fc_v100, pc_v100 = rebuild_caches(saved_factors, saved_portfolio, (1.0, 0, 0, 0))
    phase2_results = []
    for tp, sl in PHASE2_TP_SL:
        row = {'tp': tp, 'sl': sl}
        for tag, s, e in PERIODS:
            params = common_params(target_profit_rate=tp, stop_loss_rate=sl)
            r = run_bt(s, e, fc_v100, pc_v100, prices, params)
            row[tag] = r
        alpha = row['OOS'].total_return - kospi.get('OOS', 0)
        row['alpha_oos'] = alpha
        phase2_results.append(row)
        emit(f"{tp*100:>4.0f}% {sl*100:>3.0f}%  "
              f"{row['IS '].total_return:>7.1%} {row['IS '].sharpe_ratio:>6.2f}  "
              f"{row['OOS'].total_return:>7.1%} {row['OOS'].sharpe_ratio:>6.2f}  "
              f"{row['ALL'].total_return:>7.1%} {row['ALL'].sharpe_ratio:>6.2f} "
              f"{row['ALL'].max_drawdown:>6.1%} {row['ALL'].total_trades:>6d}  "
              f"{alpha:>+6.1%}")

    best_p2 = max(phase2_results, key=lambda r: r['alpha_oos'])
    emit(f"\nPhase 2 Best (OOS α 기준): TP{best_p2['tp']*100:.0f}/SL{best_p2['sl']*100:.0f}  OOS α {best_p2['alpha_oos']:+.1%}")
    emit("")

    # ─────────────────────────────────────────────────
    # Phase 3: Best TP/SL + 포트폴리오 크기
    # ─────────────────────────────────────────────────
    emit("=" * 120)
    emit(f"Phase 3: V100 + TP{best_p2['tp']*100:.0f}/SL{best_p2['sl']*100:.0f} + 포트폴리오 크기")
    emit("=" * 120)
    emit(f"{'Port':>5}  {'IS_Ret':>8} {'IS_Shr':>6}  {'OOS_Ret':>8} {'OOS_Shr':>6}  {'ALL_Ret':>8} {'ALL_Shr':>6} {'ALL_MDD':>7} {'ALL_Tr':>6}  {'OOS_α':>7}")
    emit("-" * 120)

    phase3_results = []
    for port in PHASE3_PORT:
        row = {'port': port}
        for tag, s, e in PERIODS:
            params = common_params(
                portfolio_size=port,
                target_profit_rate=best_p2['tp'],
                stop_loss_rate=best_p2['sl'],
            )
            r = run_bt(s, e, fc_v100, pc_v100, prices, params)
            row[tag] = r
        alpha = row['OOS'].total_return - kospi.get('OOS', 0)
        row['alpha_oos'] = alpha
        phase3_results.append(row)
        emit(f"{port:>5}  "
              f"{row['IS '].total_return:>7.1%} {row['IS '].sharpe_ratio:>6.2f}  "
              f"{row['OOS'].total_return:>7.1%} {row['OOS'].sharpe_ratio:>6.2f}  "
              f"{row['ALL'].total_return:>7.1%} {row['ALL'].sharpe_ratio:>6.2f} "
              f"{row['ALL'].max_drawdown:>6.1%} {row['ALL'].total_trades:>6d}  "
              f"{alpha:>+6.1%}")

    best_p3 = max(phase3_results, key=lambda r: r['alpha_oos'])
    emit(f"\nPhase 3 Best: Portfolio {best_p3['port']}  OOS α {best_p3['alpha_oos']:+.1%}")
    emit("")

    # 최종 요약
    emit("=" * 120)
    emit("최종 추천")
    emit("=" * 120)
    emit(f"  팩터 가중치: {best_p1['label']} (OOS α {best_p1['alpha_oos']:+.1%})")
    emit(f"  TP/SL:      {best_p2['tp']*100:.0f}%/{best_p2['sl']*100:.0f}% (OOS α {best_p2['alpha_oos']:+.1%})")
    emit(f"  포트폴리오: {best_p3['port']}종목 (OOS α {best_p3['alpha_oos']:+.1%})")
    emit("=" * 120)

    out = Path("results/value_tuning.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
