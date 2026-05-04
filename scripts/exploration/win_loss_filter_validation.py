#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
승/패 패턴 필터 실전 검증

시나리오:
  Baseline: V100 (필터 없음)
  A:        V100 + vol_20d ≤ 하위 1/3
  B:        V100 + pct_52w_high ≥ 상위 1/3 & vol_20d ≤ 하위 1/3

필터 방식: 조건 불만족 종목은 total_score = -1 → buy_min=65에 자연 차단
(실전 백테스터 그대로, 거래수는 감소 방향)
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
import psycopg2

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import BACKTEST_DB_CONFIG


PERIODS = [
    ("2024-04~2025-06 (15개월)", "2024-04-01", "2025-06-30"),
    ("2025-07~2026-04 (9개월)",  "2025-07-01", "2026-04-09"),
    ("전체 2년",                 "2024-04-01", "2026-04-09"),
]


def common_params(**ov):
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
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )
    base.update(ov)
    return BacktestParams(**base)


# ═══════════════════════════════════════════════════════════════
# 피처 계산 (vol_20d, pct_52w_high 각 (stock, date)별)
# ═══════════════════════════════════════════════════════════════
def compute_filter_features(start='2023-01-01', end='2026-04-09'):
    """
    각 (stock_code, yyyymmdd)별 vol_20d, pct_52w_high 반환.
    둘 다 D-1 기준.
    """
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        df = pd.read_sql_query(
            """SELECT stock_code, date::text AS date, close, high, volatility_20d
               FROM daily_prices WHERE date >= %s AND date <= %s
               AND stock_code NOT IN ('KS11', 'KQ11')
               ORDER BY stock_code, date""",
            conn, params=(start, end)
        )
    out = {}
    for code, g in df.groupby('stock_code'):
        g = g.sort_values('date').reset_index(drop=True)
        closes = g['close'].values.astype(float)
        highs = g['high'].values.astype(float)
        vols = g['volatility_20d'].values
        dates = g['date'].values
        for idx in range(1, len(g)):
            prev = idx - 1
            feat = {}
            # vol_20d at D-1
            v = vols[prev]
            feat['vol_20d'] = None if pd.isna(v) else float(v)
            # pct_52w_high at D-1
            if prev >= 250:
                h52 = highs[prev - 249:prev + 1].max()
                feat['pct_52w_high'] = closes[prev] / h52 if h52 > 0 else None
            else:
                feat['pct_52w_high'] = None
            out[(code, dates[idx].replace("-", ""))] = feat
    return out


# ═══════════════════════════════════════════════════════════════
# 일별 cross-sectional 임계값 계산
# ═══════════════════════════════════════════════════════════════
def compute_daily_thresholds(filter_feats, feat_name, low_pct=33, high_pct=67):
    """
    각 calc_date별로 feat의 하위/상위 임계값 계산.
    반환: {yyyymmdd: (low_thresh, high_thresh)}
    """
    by_date = defaultdict(list)
    for (code, d), feats in filter_feats.items():
        v = feats.get(feat_name)
        if v is not None:
            by_date[d].append(v)

    out = {}
    for d, vals in by_date.items():
        if len(vals) >= 20:
            vals_arr = np.array(vals)
            out[d] = (
                float(np.percentile(vals_arr, low_pct)),
                float(np.percentile(vals_arr, high_pct)),
            )
    return out


# ═══════════════════════════════════════════════════════════════
# V100 cache 구성 + 필터 적용
# ═══════════════════════════════════════════════════════════════
def build_v100_filtered_cache(saved_factors, saved_portfolio, filter_feats,
                                filter_fn):
    """
    filter_fn(feats_dict, thresholds_dict, calc_date) -> bool (True면 매수 후보 유지)
    thresholds_dict은 빌드 시 필요 없고 함수 내부에서 쓰도록 closure 사용.
    """
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])
    new_factors, new_portfolio = {}, {}
    filtered_count = 0
    total_count = 0

    for calc_date, stocks in saved_factors.items():
        scored = []
        new_stocks = {}
        for code, f in stocks.items():
            base_score = f.get('value_score', 0)
            total_count += 1
            feats = filter_feats.get((code, calc_date))
            passes = filter_fn(feats, calc_date)
            if not passes:
                filtered_count += 1
                final_score = -1.0
            else:
                final_score = base_score
            nf = dict(f)
            nf['total_score'] = final_score
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, final_score))
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
    return new_factors, new_portfolio, filtered_count, total_count


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


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  승/패 패턴 필터 실전 검증 (V100 + 저변동성/52주고가 필터)")
    emit("  (자본 1,000만원 기준)")
    emit("=" * 130)

    print("\n[1/3] 데이터 + 필터 피처 로드...", flush=True)
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    emit(f"  백테스트 데이터 {time.time()-t0:.1f}초")

    t1 = time.time()
    filter_feats = compute_filter_features('2023-01-01', '2026-04-09')
    emit(f"  필터 피처 {time.time()-t1:.1f}초, {len(filter_feats):,}건")

    # Daily thresholds
    t2 = time.time()
    vol_thresh = compute_daily_thresholds(filter_feats, 'vol_20d', 33, 67)
    p52h_thresh = compute_daily_thresholds(filter_feats, 'pct_52w_high', 33, 67)
    emit(f"  일별 임계값 {time.time()-t2:.1f}초, vol={len(vol_thresh)}일, 52wh={len(p52h_thresh)}일")

    k = kospi_returns_money(prices)
    emit("")
    emit("[KOSPI B&H - 천만원 기준]")
    for tag, s, e in PERIODS:
        r = k.get(tag)
        if r:
            emit(f"  {tag:<28}  1,000만 -> {r['final']/10000:,.0f}만 ({r['return']:+.1%})")

    # ═══════════════════════════════════════════════════
    # 3가지 시나리오
    # ═══════════════════════════════════════════════════
    def baseline_fn(feats, calc_date):
        return True  # 필터 없음

    def filter_A_fn(feats, calc_date):
        """vol_20d <= 하위 1/3"""
        if feats is None: return False
        v = feats.get('vol_20d')
        if v is None: return False
        th = vol_thresh.get(calc_date)
        if th is None: return False
        return v <= th[0]

    def filter_B_fn(feats, calc_date):
        """pct_52w_high >= 상위 1/3 & vol_20d <= 하위 1/3"""
        if feats is None: return False
        v = feats.get('vol_20d')
        p = feats.get('pct_52w_high')
        if v is None or p is None: return False
        vth = vol_thresh.get(calc_date)
        pth = p52h_thresh.get(calc_date)
        if vth is None or pth is None: return False
        return v <= vth[0] and p >= pth[1]

    SCENARIOS = [
        ("Baseline (V100, 필터 없음)", baseline_fn),
        ("A: V100 + 저변동성",         filter_A_fn),
        ("B: V100 + 52주고가/저변동성", filter_B_fn),
    ]

    print("\n[2/3] 시나리오별 필터 캐시 구성 + 백테스트...", flush=True)
    emit("")
    emit("=" * 130)
    emit(f"{'시나리오':<30} | {'구간':<28} | {'최종':>10} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    emit("-" * 130)

    results = []
    for label, filter_fn in SCENARIOS:
        fc, pc, filtered_n, total_n = build_v100_filtered_cache(
            saved_factors, saved_portfolio, filter_feats, filter_fn
        )
        row = {'label': label, 'filter_pct': filtered_n/total_n*100 if total_n > 0 else 0}
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params())
            row[tag] = r
            profit = r.final_total_value - 10_000_000
            k_prof = k.get(tag, {}).get('profit', 0)
            diff = profit - k_prof
            emit(f"{label:<30} | {tag:<28} | {r.final_total_value/10000:>8,.0f}만 | "
                  f"{profit/10000:>+8,.0f}만 | {r.total_return:>+7.1%} | "
                  f"{diff/10000:>+8,.0f}만 | {r.total_trades:>6d}")
        emit(f"  (필터로 제외된 종목: {row['filter_pct']:.1f}%)")
        emit("")
        results.append(row)

    # 요약
    emit("=" * 130)
    emit("전체 2년 기준 순위 및 알파 개선")
    emit("=" * 130)
    k_all = k.get("전체 2년", {}).get('profit', 0)
    baseline = next(r for r in results if '필터 없음' in r['label'])
    base_profit = baseline["전체 2년"].final_total_value - 10_000_000
    base_alpha = base_profit - k_all
    emit(f"Baseline: 수익 +{base_profit/10000:,.0f}만, KOSPI차 {base_alpha/10000:+.0f}만")
    emit("")

    for r in results:
        res = r["전체 2년"]
        profit = res.final_total_value - 10_000_000
        alpha = profit - k_all
        imp = alpha - base_alpha
        mark = " ★" if '필터 없음' in r['label'] else ""
        emit(f"{r['label']:<30} | 최종 {res.final_total_value/10000:>7,.0f}만 | "
              f"수익 {profit/10000:>+7,.0f}만 | 알파 {alpha/10000:>+7,.0f}만 | "
              f"Δ{imp/10000:>+6,.0f}만 | 거래 {res.total_trades:>4d}{mark}")

    out = Path("results/win_loss_filter_validation.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
