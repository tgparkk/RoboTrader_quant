#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
패턴 실전 검증: v3에서 발견한 패턴을 실제 백테스터(자본 제약, 포트폴리오 10)에 적용

비교:
  Baseline: V100 top 10 (패턴 필터 없음)
  변형 A:   V100 + rs_20d_kospi ≤ -0.08 (단변량)
  변형 B:   V100 + rs_20d_kospi ≤ B20 & stoch_k ≥ T20 (2변량, 고승률)
  변형 C:   V100 + rs_20d_kospi ≤ B20 & macd_hist ≤ B20 (최근 급등)

각 변형을 IS/OOS/ALL 기간에 돌려 KOSPI 대비 알파 측정.
"""
import sys
import time
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import psycopg2

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import BACKTEST_DB_CONFIG


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


# ─────────────────────────────────────────────────────────────
# 피처 계산 (v3와 동일, rs_20d_kospi / stoch_k / macd_hist만)
# ─────────────────────────────────────────────────────────────
def compute_features_for_stock(df, kospi_closes):
    out = {}
    n = len(df)
    if n < 60:
        return out
    closes = df['close'].values.astype(float)
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    returns_20d = df['returns_20d'].values
    dates = df['date'].values

    def ema(vals, period):
        a = 2 / (period + 1)
        e = np.zeros_like(vals); e[0] = vals[0]
        for i in range(1, len(vals)):
            e[i] = a * vals[i] + (1 - a) * e[i-1]
        return e
    macd_hist = ema(closes, 12) - ema(closes, 26)
    macd_hist = macd_hist - ema(macd_hist, 9)

    stoch_k = np.full(n, np.nan)
    for i in range(14, n):
        ph = np.max(highs[i-13:i+1]); pl = np.min(lows[i-13:i+1])
        if ph > pl:
            stoch_k[i] = (closes[i] - pl) / (ph - pl) * 100

    for idx in range(1, n):
        d = str(dates[idx])
        prev = idx - 1
        feat = {}
        p_c = closes[prev]

        feat['macd_hist'] = float(macd_hist[prev]) / (abs(p_c) + 1) if p_c > 0 else None
        val = stoch_k[prev]
        feat['stoch_k'] = None if np.isnan(val) else float(val)

        r20 = returns_20d[prev] if not pd.isna(returns_20d[prev]) else None
        k1 = kospi_closes.get(str(dates[prev]))
        k21 = kospi_closes.get(str(dates[prev - 20])) if prev >= 20 else None
        feat['rs_20d_kospi'] = r20 - (k1/k21 - 1) if (r20 is not None and k1 and k21 and k21 > 0) else None

        out[d.replace("-", "")] = feat
    return out


def compute_all_features(kospi_closes):
    """전체 종목 피처 계산"""
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        prices_df = pd.read_sql_query(
            """SELECT stock_code, date::text AS date, open, high, low, close,
                      returns_20d
               FROM daily_prices WHERE date >= %s AND date <= %s
               AND stock_code NOT IN ('KS11', 'KQ11')
               ORDER BY stock_code, date""",
            conn, params=('2023-01-01', '2026-04-09')
        )

    per_stock_feats = {}
    for code, g in prices_df.groupby('stock_code'):
        res = compute_features_for_stock(g.reset_index(drop=True), kospi_closes)
        for d, feats in res.items():
            per_stock_feats[(code, d)] = feats
    return per_stock_feats


# ─────────────────────────────────────────────────────────────
# 전역 백분위 계산 (Q1, T20, B20)
# ─────────────────────────────────────────────────────────────
def compute_percentile_thresholds(per_stock_feats, feat_name, percentile):
    """전체 표본에서 해당 피처의 percentile 값 반환"""
    vals = [f.get(feat_name) for f in per_stock_feats.values() if f.get(feat_name) is not None]
    if not vals:
        return None
    return float(np.percentile(vals, percentile))


# ─────────────────────────────────────────────────────────────
# 패턴 필터 적용: V100 점수를 유지하되, 조건 불만족 종목은 total_score=0
# ─────────────────────────────────────────────────────────────
def build_filtered_cache(saved_factors, saved_portfolio, per_stock_feats, conditions,
                          portfolio_top_n=50, base_score_fn=None):
    """
    conditions: list of (feat_name, op, value)
    각 (stock, calc_date)에 대해 조건 만족 여부 체크 → 만족 시 V100 점수, 아니면 -1 (하위 랭킹)

    base_score_fn(f) → V100(기본 value_score). 다른 가중치도 가능.
    """
    if base_score_fn is None:
        base_score_fn = lambda f: f.get('value_score', 0)

    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])

    new_factors = {}
    new_portfolio = {}
    for calc_date, stocks in saved_factors.items():
        scored = []
        new_stocks = {}
        for code, f in stocks.items():
            base_score = base_score_fn(f)
            feats = per_stock_feats.get((code, calc_date), {})

            # 조건 평가
            passes = True
            for fname, op, val in conditions:
                fv = feats.get(fname)
                if fv is None:
                    passes = False
                    break
                if op == '<=' and not (fv <= val): passes = False
                elif op == '>=' and not (fv >= val): passes = False
                elif op == '<' and not (fv < val): passes = False
                elif op == '>' and not (fv > val): passes = False
                if not passes:
                    break

            # 패턴 통과 시 V100 점수, 아니면 -1 (완전 하위)
            final_score = base_score if passes else -1.0

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
        for rank, (code, tscore) in enumerate(scored[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': tscore,
                'reason': f'filtered {tscore:.1f}',
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


def kospi_returns(prices):
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            out[tag] = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close']) - 1
    return out


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  패턴 실전 검증: V100 + 패턴 필터 → 실제 백테스터 (포트폴리오 10, 자본 제약)")
    emit("=" * 130)

    print("\n[1/4] 데이터 로딩...", flush=True)
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    emit(f"  {time.time()-t0:.1f}초, {len(days)}거래일, {len(prices)}종목")

    kospi_df = prices.get('KS11')
    kospi_closes = {}
    if kospi_df is not None:
        for d, row in kospi_df.iterrows():
            kospi_closes[str(d).replace("-", "")] = float(row['close'])
            kospi_closes[str(d)] = float(row['close'])
    k_alpha = kospi_returns(prices)
    emit(f"  KOSPI: IS {k_alpha['IS ']:+.1%}, OOS {k_alpha['OOS']:+.1%}, ALL {k_alpha['ALL']:+.1%}")

    print("\n[2/4] 피처 계산 (rs_20d_kospi, stoch_k, macd_hist)...", flush=True)
    t1 = time.time()
    per_stock_feats = compute_all_features(kospi_closes)
    emit(f"  {time.time()-t1:.1f}초, {len(per_stock_feats):,}건")

    # 백분위 임계값 계산
    rs_q1 = compute_percentile_thresholds(per_stock_feats, 'rs_20d_kospi', 20)
    rs_b20 = rs_q1  # 같은 값 (하위 20%)
    stoch_t20 = compute_percentile_thresholds(per_stock_feats, 'stoch_k', 80)
    macd_b20 = compute_percentile_thresholds(per_stock_feats, 'macd_hist', 20)
    emit(f"  임계값: rs_20d_kospi Q1={rs_q1:.3f}, stoch_k T20={stoch_t20:.2f}, macd_hist B20={macd_b20:.5f}")

    print("\n[3/4] V100 기준 점수 함수...", flush=True)
    v100_score = lambda f: f.get('value_score', 0)

    # 시나리오 정의
    SCENARIOS = [
        ("Baseline (V100, 필터 없음)", []),
        ("A: rs_20d_kospi ≤ -8%",
            [('rs_20d_kospi', '<=', rs_q1)]),
        ("B: rs≤B20 & stoch_k ≥ T20",
            [('rs_20d_kospi', '<=', rs_b20), ('stoch_k', '>=', stoch_t20)]),
        ("C: rs≤B20 & macd_hist ≤ B20",
            [('rs_20d_kospi', '<=', rs_b20), ('macd_hist', '<=', macd_b20)]),
    ]

    print("\n[4/4] 실전 백테스트 (각 시나리오 × 3기간)...", flush=True)
    t2 = time.time()

    emit("\n" + "=" * 130)
    emit(f"{'Scenario':<36}  {'IS_Ret':>8} {'IS_Shr':>6}  {'OOS_Ret':>8} {'OOS_Shr':>6}  "
          f"{'ALL_Ret':>8} {'ALL_Shr':>6} {'ALL_MDD':>7} {'ALL_Tr':>6}  "
          f"{'IS_α':>6} {'OOS_α':>7} {'ALL_α':>7}")
    emit("-" * 130)

    results = []
    for label, conds in SCENARIOS:
        fc, pc = build_filtered_cache(saved_factors, saved_portfolio,
                                       per_stock_feats, conds,
                                       base_score_fn=v100_score)
        row = {'label': label, 'conds': conds}
        for tag, s, e in PERIODS:
            # buy_min_score=65 유지: 패턴 실패 시 total_score=-1 → 자연 차단
            # V100 정상 통과 + 점수 ≥ 65인 종목만 실제 매수
            r = run_bt(s, e, fc, pc, prices, common_params(buy_min_score=65.0))
            row[tag] = r
        is_a = row['IS '].total_return - k_alpha['IS ']
        oos_a = row['OOS'].total_return - k_alpha['OOS']
        all_a = row['ALL'].total_return - k_alpha['ALL']
        row.update({'is_α': is_a, 'oos_α': oos_a, 'all_α': all_a})
        results.append(row)
        emit(f"{label:<36}  "
              f"{row['IS '].total_return:>7.1%} {row['IS '].sharpe_ratio:>6.2f}  "
              f"{row['OOS'].total_return:>7.1%} {row['OOS'].sharpe_ratio:>6.2f}  "
              f"{row['ALL'].total_return:>7.1%} {row['ALL'].sharpe_ratio:>6.2f} "
              f"{row['ALL'].max_drawdown:>6.1%} {row['ALL'].total_trades:>6d}  "
              f"{is_a:>+5.1%} {oos_a:>+6.1%} {all_a:>+6.1%}")

    emit(f"\n총 {time.time()-t2:.1f}초")

    # 요약
    emit("\n" + "=" * 130)
    emit("실전 검증 요약")
    emit("=" * 130)
    baseline = next(r for r in results if r['label'].startswith('Baseline'))
    emit(f"Baseline: ALL {baseline['ALL'].total_return:+.1%}, 알파 {baseline['all_α']:+.1%}p, "
         f"거래 {baseline['ALL'].total_trades}, 샤프 {baseline['ALL'].sharpe_ratio:.2f}")
    emit("")
    for r in results:
        if r['label'].startswith('Baseline'):
            continue
        imp_all = r['all_α'] - baseline['all_α']
        imp_oos = r['oos_α'] - baseline['oos_α']
        emit(f"{r['label']:<36}  →  ALL 알파 {r['all_α']:+6.1%}p (Δ{imp_all:+.1%}p), "
             f"OOS 알파 {r['oos_α']:+6.1%}p (Δ{imp_oos:+.1%}p), "
             f"거래 {r['ALL'].total_trades} (vs {baseline['ALL'].total_trades})")

    out = Path("results/pattern_live_validation.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
