#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
패턴 발견 v3: 방안 1 — 자본 제약 없는 독립 거래 시뮬

설계:
  각 거래일 D에 대해 V100 top 50 전부 "가상 매수"
  → 매수가 = D 시가
  → TP 12% 또는 SL 6% 터질 때까지 forward simulation (max 60일)
  → 결과 기록 (독립 거래, 포트폴리오 상호작용 없음)

예상 거래수: 2년 × 252일 × 50종목 × 필터링 ≈ 20,000건 이상
최근 2개월에도 1,000건 이상 → 통계적 의미 가능

look-ahead safe:
  - 피처: D-1 이전만 (매수 결정 시점에 알 수 있는 정보)
  - V100 순위: calc_date=D-1 기준 (_get_prev_calc_date와 동일)
  - 매수가: D 시가 (09:00 확정, 09:05 결정 시점에 알 수 있음)
  - TP/SL 시뮬: D 이후 일봉 high/low (표준 관행)
"""
import sys
import time
import logging
import bisect
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import psycopg2

from backtest import Backtester, BacktestParams
from config.db_config import BACKTEST_DB_CONFIG


VALIDATION_WINDOWS = [
    ("전체 2년", "2024-04-01", "2026-04-09"),
    ("최근 1년", "2025-04-10", "2026-04-09"),
    ("최근 2개월", "2026-02-10", "2026-04-09"),
]


def common_params(**ov):
    base = dict(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=0.0,
        soft_stop_score=0.0,
        soft_stop_rank=999,
        safe_score=999.0,
        safe_rank=999,
        buy_min_score=0.0,
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=0,
    )
    base.update(ov)
    return BacktestParams(**base)


# ═══════════════════════════════════════════════════════════════
# 피처 계산 (v2와 동일)
# ═══════════════════════════════════════════════════════════════
def compute_features_for_stock(df, kospi_closes):
    out = {}
    n = len(df)
    if n < 60:
        return out
    closes = df['close'].values.astype(float)
    opens = df['open'].values.astype(float)
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    volumes = df['volume'].values.astype(float)
    trading_values = df['trading_value'].fillna(0).values.astype(float)
    market_caps = df['market_cap'].fillna(0).values.astype(float)
    returns_5d = df['returns_5d'].values
    returns_20d = df['returns_20d'].values
    volatility_20d = df['volatility_20d'].values
    dates = df['date'].values

    obv = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i-1]:
            obv[i] = obv[i-1] + volumes[i]
        elif closes[i] < closes[i-1]:
            obv[i] = obv[i-1] - volumes[i]
        else:
            obv[i] = obv[i-1]

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
        p_h = highs[prev]; p_l = lows[prev]; p_o = opens[prev]; p_c = closes[prev]
        rng = p_h - p_l
        feat['body_ratio'] = abs(p_c - p_o) / rng if rng > 0 else None
        feat['upper_shadow'] = (p_h - max(p_o, p_c)) / rng if rng > 0 else None
        feat['lower_shadow'] = (min(p_o, p_c) - p_l) / rng if rng > 0 else None
        feat['gap_up'] = (p_o - closes[prev-1]) / closes[prev-1] if prev >= 1 and closes[prev-1] > 0 else None

        if prev >= 20:
            va = volumes[prev - 20:prev].mean()
            feat['vol_spike'] = volumes[prev] / va if va > 0 else None
        else:
            feat['vol_spike'] = None

        feat['turnover'] = trading_values[prev] / market_caps[prev] if market_caps[prev] > 0 else None

        if prev >= 20:
            x = np.arange(20); y = obv[prev - 19:prev + 1]
            if y.std() > 0:
                slope, _ = np.polyfit(x, y, 1)
                feat['obv_slope'] = slope / (abs(obv[prev]) + 1)
            else:
                feat['obv_slope'] = 0
        else:
            feat['obv_slope'] = None

        if prev >= 20:
            ma20 = closes[prev - 19:prev + 1].mean()
            std20 = closes[prev - 19:prev + 1].std()
            feat['bb_position'] = (p_c - ma20) / (2 * std20) if std20 > 0 else 0
        else:
            feat['bb_position'] = None

        feat['macd_hist'] = float(macd_hist[prev]) / (abs(p_c) + 1) if p_c > 0 else None
        val = stoch_k[prev]
        feat['stoch_k'] = None if np.isnan(val) else float(val)

        if prev >= 250:
            h52 = highs[prev - 249:prev + 1].max()
            l52 = lows[prev - 249:prev + 1].min()
            feat['pct_52w_high'] = p_c / h52 if h52 > 0 else None
            feat['pct_52w_low'] = (p_c / l52 - 1) if l52 > 0 else None
        else:
            feat['pct_52w_high'] = None
            feat['pct_52w_low'] = None

        r20 = returns_20d[prev] if not pd.isna(returns_20d[prev]) else None
        k1 = kospi_closes.get(str(dates[prev]))
        k21 = kospi_closes.get(str(dates[prev - 20])) if prev >= 20 else None
        feat['rs_20d_kospi'] = r20 - (k1/k21 - 1) if (r20 is not None and k1 and k21 and k21 > 0) else None

        def safe(v): return None if pd.isna(v) else float(v)
        feat['vol_20d'] = safe(volatility_20d[prev])
        feat['ret_5d'] = safe(returns_5d[prev])
        feat['ret_20d'] = safe(returns_20d[prev])
        out[d.replace("-", "")] = feat
    return out


def compute_investor_features(conn, start_date, end_date):
    df = pd.read_sql_query(
        """SELECT stock_code, date, foreign_net, foreign_holding_pct
           FROM investor_flow WHERE date >= %s AND date <= %s
           ORDER BY stock_code, date""",
        conn, params=(start_date.replace("-", ""), end_date.replace("-", ""))
    )
    out = {}
    for code, g in df.groupby('stock_code'):
        g = g.sort_values('date').reset_index(drop=True)
        fn = g['foreign_net'].fillna(0).values.astype(float)
        hp = g['foreign_holding_pct'].values
        dates = g['date'].values
        for idx in range(1, len(g)):
            prev = idx - 1
            feat = {
                'fn_5d': float(fn[max(0, prev-4):prev+1].sum()) if prev >= 4 else None,
                'fn_20d': float(fn[max(0, prev-19):prev+1].sum()) if prev >= 19 else None,
            }
            if prev >= 20 and not pd.isna(hp[prev]) and not pd.isna(hp[prev-20]):
                feat['fh_chg_20d'] = float(hp[prev] - hp[prev-20])
            else:
                feat['fh_chg_20d'] = None
            out[(code, dates[idx])] = feat
    return out


# ═══════════════════════════════════════════════════════════════
# Forward 시뮬: 매수일 이후 TP/SL 터질 때까지 (최대 60일)
# ═══════════════════════════════════════════════════════════════
def simulate_forward(prices_arr, buy_idx, tp_rate, sl_rate, max_hold=60):
    """
    prices_arr: numpy structured array with fields [date, open, high, low, close]
    buy_idx: 매수일 인덱스 (D)
    반환: (exit_date, exit_price, profit_rate, exit_type) or None
    """
    n = len(prices_arr)
    if buy_idx >= n:
        return None
    buy_price = prices_arr['open'][buy_idx]
    if buy_price <= 0:
        return None

    tp_price = buy_price * (1 + tp_rate)
    sl_price = buy_price * (1 - sl_rate)

    # P3: 매수 당일 TP/SL 차단 (실전과 일치)
    for i in range(buy_idx + 1, min(buy_idx + 1 + max_hold, n)):
        high = prices_arr['high'][i]
        low = prices_arr['low'][i]
        close = prices_arr['close'][i]
        d = prices_arr['date'][i]

        hit_tp = high >= tp_price
        hit_sl = low <= sl_price

        if hit_tp and hit_sl:
            # P2: 동시 히트 → 손절 우선
            return (d, sl_price, -sl_rate, 'SL')
        elif hit_tp:
            # P1: 보수적 체결가 (target과 close 중간, 슬리피지)
            realistic = (tp_price + close) / 2 * (1 - 0.0025)
            pr = (realistic - buy_price) / buy_price
            return (d, realistic, pr, 'TP')
        elif hit_sl:
            realistic = (sl_price + close) / 2 * (1 - 0.0025)
            pr = (realistic - buy_price) / buy_price
            return (d, realistic, pr, 'SL')

    # max_hold 초과 → 마지막 종가 매도
    last_idx = min(buy_idx + max_hold, n - 1)
    exit_price = prices_arr['close'][last_idx]
    pr = (exit_price - buy_price) / buy_price
    return (prices_arr['date'][last_idx], exit_price, pr, 'MAX')


# ═══════════════════════════════════════════════════════════════
# V100 기반 top 50 추출
# ═══════════════════════════════════════════════════════════════
def build_top50_per_date(saved_factors, top_n=50):
    """각 calc_date별로 V100 기준 top N 종목 코드 반환"""
    out = {}
    for calc_date, stocks in saved_factors.items():
        scored = [(code, f.get('value_score', 0)) for code, f in stocks.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        out[calc_date] = [code for code, _ in scored[:top_n]]
    return out


# ═══════════════════════════════════════════════════════════════
# 독립 거래 생성: V100 top 50 전부 가상 매수
# ═══════════════════════════════════════════════════════════════
def generate_independent_trades(top50_per_date, prices_by_stock_np,
                                  tp_rate=0.12, sl_rate=0.06, max_hold=60,
                                  start_date="2024-04-01", end_date="2026-04-09"):
    """
    각 (calc_date, 종목) 쌍에 대해 독립 거래 시뮬.
    buy_date = calc_date의 다음 거래일 (실전 D-1 스크리닝 → D 09:05 매수 일관)

    prices_by_stock_np: {code: np.structured_array with date/open/high/low/close}
    """
    trades = []
    calc_dates_sorted = sorted(top50_per_date.keys())

    s_ymd = start_date.replace("-", "")
    e_ymd = end_date.replace("-", "")

    # calc_date → 각 종목의 date 인덱스 매핑 (이분탐색)
    for cd_idx, calc_date in enumerate(calc_dates_sorted):
        # 매수일 = calc_date 다음 거래일. 다음 calc_date로 근사 (거래일이 같음).
        if cd_idx + 1 >= len(calc_dates_sorted):
            continue
        next_cd = calc_dates_sorted[cd_idx + 1]
        if not (s_ymd <= next_cd <= e_ymd):
            continue
        buy_date_str = f"{next_cd[:4]}-{next_cd[4:6]}-{next_cd[6:8]}"

        for code in top50_per_date[calc_date]:
            parr = prices_by_stock_np.get(code)
            if parr is None:
                continue
            # 매수일 인덱스 찾기 (이분탐색)
            buy_idx = np.searchsorted(parr['date'], buy_date_str)
            if buy_idx >= len(parr) or parr['date'][buy_idx] != buy_date_str:
                continue
            res = simulate_forward(parr, buy_idx, tp_rate, sl_rate, max_hold)
            if res is None:
                continue
            exit_date, exit_price, pr, exit_type = res
            trades.append({
                'calc_date': calc_date,
                'buy_date': buy_date_str,
                'stock_code': code,
                'buy_price': float(parr['open'][buy_idx]),
                'sell_date': str(exit_date),
                'sell_price': float(exit_price),
                'profit_rate': float(pr),
                'exit_type': exit_type,
                'win': pr > 0,
            })
    return trades


# ═══════════════════════════════════════════════════════════════
# 분석 함수들
# ═══════════════════════════════════════════════════════════════
def attach_features_to_trades(trade_log, per_stock_feats):
    enriched = []
    for t in trade_log:
        # 피처는 buy_date 기준 (D의 의사결정 시점, D-1 데이터 반영)
        key = (t['stock_code'], t['buy_date'].replace("-", ""))
        feats = per_stock_feats.get(key)
        if feats is None:
            continue
        row = dict(t)
        row.update({f'feat_{k}': v for k, v in feats.items()})
        enriched.append(row)
    return enriched


def univariate_analysis(df, feat_names, min_samples=100):
    results = []
    wins = df[df['win']]; losses = df[~df['win']]
    for f in feat_names:
        col = f'feat_{f}'
        w = wins[col].dropna(); l = losses[col].dropna()
        if len(w) < min_samples or len(l) < min_samples:
            continue
        wm, lm = w.mean(), l.mean()
        ws, ls = w.std(), l.std()
        ps = ((ws**2 + ls**2)/2)**0.5
        d = (wm - lm) / ps if ps > 0 else 0
        results.append({
            'feature': f, 'win_mean': wm, 'loss_mean': lm,
            'd_effect': d, 'n_wins': len(w), 'n_losses': len(l),
        })
    results.sort(key=lambda r: abs(r['d_effect']), reverse=True)
    return results


def quintile_winrate(df, feat):
    col = f'feat_{feat}'
    valid = df.dropna(subset=[col]).copy()
    if len(valid) < 100:
        return None
    try:
        valid['q'] = pd.qcut(valid[col], 5, labels=[1,2,3,4,5], duplicates='drop')
    except Exception:
        return None
    return valid.groupby('q').agg(
        n=('win', 'count'),
        wr=('win', 'mean'),
        avg_pr=('profit_rate', 'mean'),
    )


def apply_pattern_filter(df, conditions):
    mask = pd.Series(True, index=df.index)
    for feat, op, val in conditions:
        col = f'feat_{feat}'
        if op == '>=': mask &= (df[col] >= val)
        elif op == '<=': mask &= (df[col] <= val)
        elif op == '>': mask &= (df[col] > val)
        elif op == '<': mask &= (df[col] < val)
    return df[mask]


def evaluate_pattern(df, conditions, ws, we):
    f = apply_pattern_filter(df, conditions)
    f = f[(f['buy_date'] >= ws) & (f['buy_date'] <= we)]
    n = len(f)
    if n == 0:
        return {'n': 0, 'wr': 0, 'pf': 0, 'total_pr': 0, 'avg_pr': 0}
    w = f['win'].sum()
    wr = w / n
    win_sum = f[f['win']]['profit_rate'].sum()
    loss_sum = abs(f[~f['win']]['profit_rate'].sum())
    pf = win_sum / loss_sum if loss_sum > 0 else 99
    return {'n': n, 'wr': wr, 'pf': pf,
            'total_pr': f['profit_rate'].sum(),
            'avg_pr': f['profit_rate'].mean()}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  패턴 발견 v3: 독립 거래 시뮬 (V100 top 50 × 모든 거래일, 자본 제약 없음)")
    emit("=" * 130)

    print("\n[1/5] 데이터 로딩...", flush=True)
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    emit(f"  {time.time()-t0:.1f}초, {len(days)}거래일, {len(prices)}종목, {len(saved_factors)}일 팩터")

    # KOSPI
    kospi_df = prices.get('KS11')
    kospi_closes = {}
    if kospi_df is not None:
        for d, row in kospi_df.iterrows():
            kospi_closes[str(d).replace("-", "")] = float(row['close'])
            kospi_closes[str(d)] = float(row['close'])

    # 피처
    print("\n[2/5] 피처 계산...", flush=True)
    t1 = time.time()
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        investor_feats = compute_investor_features(conn, "2024-04-01", "2026-04-09")
        prices_df = pd.read_sql_query(
            """SELECT stock_code, date::text AS date, open, high, low, close, volume,
                      trading_value, market_cap, returns_5d, returns_20d, volatility_20d
               FROM daily_prices WHERE date >= %s AND date <= %s
               AND stock_code NOT IN ('KS11', 'KQ11')
               ORDER BY stock_code, date""",
            conn, params=('2023-01-01', '2026-04-09')
        )

    per_stock_feats = {}
    for code, g in prices_df.groupby('stock_code'):
        res = compute_features_for_stock(g.reset_index(drop=True), kospi_closes)
        for d, feats in res.items():
            key = (code, d)
            inv = investor_feats.get(key)
            if inv:
                feats.update(inv)
            else:
                for k in ['fn_5d', 'fn_20d', 'fh_chg_20d']:
                    feats.setdefault(k, None)
            per_stock_feats[key] = feats
    emit(f"  {time.time()-t1:.1f}초, {len(per_stock_feats):,}건")

    # 종목별 numpy 구조체 (forward sim용, 2024-04-01부터 여유 포함)
    print("\n[3/5] 가격 데이터 구조 준비...", flush=True)
    t2 = time.time()
    prices_np = {}
    sim_df = prices_df[prices_df['date'] >= '2024-03-01'].copy()
    for code, g in sim_df.groupby('stock_code'):
        g = g.sort_values('date').reset_index(drop=True)
        arr = np.empty(len(g), dtype=[
            ('date', 'U10'), ('open', 'f8'), ('high', 'f8'),
            ('low', 'f8'), ('close', 'f8'),
        ])
        arr['date'] = g['date'].values
        arr['open'] = g['open'].values
        arr['high'] = g['high'].values
        arr['low'] = g['low'].values
        arr['close'] = g['close'].values
        prices_np[code] = arr
    emit(f"  {time.time()-t2:.1f}초, {len(prices_np)}종목")

    # 독립 거래 시뮬
    print("\n[4/5] 독립 거래 시뮬 (V100 top 50 × 매일)...", flush=True)
    t3 = time.time()
    top50 = build_top50_per_date(saved_factors, top_n=50)
    trades = generate_independent_trades(
        top50, prices_np, tp_rate=0.12, sl_rate=0.06, max_hold=60,
        start_date="2024-04-01", end_date="2026-04-09",
    )
    emit(f"  {time.time()-t3:.1f}초, 총 거래: {len(trades):,}건")

    enriched = attach_features_to_trades(trades, per_stock_feats)
    df = pd.DataFrame(enriched)
    emit(f"  피처 붙인 거래: {len(df):,}건 (승률 {df['win'].mean():.1%})")

    # Exit type 분포
    exit_counts = df['exit_type'].value_counts()
    emit(f"  Exit 분포: TP {exit_counts.get('TP', 0):,}, SL {exit_counts.get('SL', 0):,}, MAX {exit_counts.get('MAX', 0):,}")

    # 기간별 거래수
    for tag, s, e in VALIDATION_WINDOWS:
        cnt = len(df[(df['buy_date'] >= s) & (df['buy_date'] <= e)])
        emit(f"    {tag}: {cnt:,}건")

    FEATURES = ['body_ratio','upper_shadow','lower_shadow','gap_up','vol_spike','turnover',
                'obv_slope','bb_position','macd_hist','stoch_k','pct_52w_high','pct_52w_low',
                'rs_20d_kospi','vol_20d','ret_5d','ret_20d','fn_5d','fn_20d','fh_chg_20d']

    print("\n[5/5] 분석...", flush=True)

    # 단변량
    emit("\n" + "=" * 120)
    emit("단변량 승/패 분포 (|Cohen's d| 큰 순)")
    emit("=" * 120)
    uni = univariate_analysis(df, FEATURES, min_samples=500)
    emit(f"{'Feature':<18} {'Win μ':>12} {'Loss μ':>12} {'d':>6} {'Win N':>7} {'Loss N':>7}")
    emit("-" * 80)
    for r in uni:
        emit(f"{r['feature']:<18} {r['win_mean']:>12.4f} {r['loss_mean']:>12.4f} "
             f"{r['d_effect']:>+6.2f} {r['n_wins']:>7,} {r['n_losses']:>7,}")

    # Top 8 Quintile
    emit("\n" + "=" * 120)
    emit("Top 8 피처 Quintile 승률")
    emit("=" * 120)
    top_feats = [r['feature'] for r in uni[:8]]
    for f in top_feats:
        qr = quintile_winrate(df, f)
        if qr is None:
            continue
        emit(f"\n[{f}]")
        emit(qr.to_string())

    # 패턴 후보 생성
    emit("\n" + "=" * 120)
    emit("패턴 후보 (quintile 극단 + 2변량 조합)")
    emit("=" * 120)
    pattern_candidates = []
    for f in top_feats:
        qr = quintile_winrate(df, f)
        if qr is None: continue
        col = f'feat_{f}'
        valid = df[col].dropna()
        if len(valid) < 100: continue
        qs = valid.quantile([0.2, 0.4, 0.6, 0.8]).values
        top_wr = qr.loc[5, 'wr']; bot_wr = qr.loc[1, 'wr']
        baseline_wr = df['win'].mean()
        if top_wr > bot_wr and top_wr > baseline_wr + 0.02:
            pattern_candidates.append({
                'name': f"{f} >= Q4 ({qs[3]:.3f})",
                'conditions': [(f, '>=', qs[3])],
            })
        elif bot_wr > top_wr and bot_wr > baseline_wr + 0.02:
            pattern_candidates.append({
                'name': f"{f} <= Q1 ({qs[0]:.3f})",
                'conditions': [(f, '<=', qs[0])],
            })

    # 2변량 조합 (top 5 × top 5 = 10 pairs)
    top5 = top_feats[:5]
    for i in range(len(top5)):
        for j in range(i+1, len(top5)):
            f1, f2 = top5[i], top5[j]
            c1, c2 = f'feat_{f1}', f'feat_{f2}'
            v1 = df[c1].dropna(); v2 = df[c2].dropna()
            if len(v1) < 200 or len(v2) < 200: continue
            q1 = v1.quantile([0.2, 0.8]).values
            q2 = v2.quantile([0.2, 0.8]).values
            for op1, val1, lbl1 in [('>=', q1[1], f"{f1}>=T20"), ('<=', q1[0], f"{f1}<=B20")]:
                for op2, val2, lbl2 in [('>=', q2[1], f"{f2}>=T20"), ('<=', q2[0], f"{f2}<=B20")]:
                    conds = [(f1, op1, val1), (f2, op2, val2)]
                    res = evaluate_pattern(df, conds, "2024-04-01", "2026-04-09")
                    if res['n'] >= 100 and res['wr'] >= df['win'].mean() + 0.03:
                        pattern_candidates.append({
                            'name': f"{lbl1} & {lbl2}",
                            'conditions': conds,
                        })

    emit(f"\n총 패턴 후보: {len(pattern_candidates)}개")

    # 3기간 검증
    emit("\n" + "=" * 130)
    emit("3기간 일관성 검증")
    emit("=" * 130)
    emit(f"{'Pattern':<40} | {'전체 2년':>33} | {'최근 1년':>33} | {'최근 2개월':>33}")
    emit(f"{'':<40} | {'N':>5} {'승률':>6} {'PF':>5} {'평균':>6} {'∑수익':>6} | "
         f"{'N':>5} {'승률':>6} {'PF':>5} {'평균':>6} {'∑수익':>6} | "
         f"{'N':>5} {'승률':>6} {'PF':>5} {'평균':>6} {'∑수익':>6}")
    emit("-" * 150)

    baseline_wr = df['win'].mean()
    survivors = []
    for p in pattern_candidates:
        stats = {}
        all_ok = True
        row_parts = [f"{p['name']:<40}"]
        for tag, s, e in VALIDATION_WINDOWS:
            res = evaluate_pattern(df, p['conditions'], s, e)
            stats[tag] = res
            row_parts.append(
                f"{res['n']:>5} {res['wr']:>5.1%} {res['pf']:>5.2f} "
                f"{res['avg_pr']*100:>+5.1f}% {res['total_pr']*100:>+5.0f}%"
            )
            # 기간별 최소 기준
            min_n = {"전체 2년": 100, "최근 1년": 50, "최근 2개월": 20}[tag]
            min_wr = baseline_wr + 0.02
            if res['n'] < min_n or res['wr'] < min_wr:
                all_ok = False
        mark = " ★" if all_ok else ""
        emit(" | ".join(row_parts) + mark)
        if all_ok:
            survivors.append((p, stats))

    emit("\n" + "=" * 130)
    emit(f"생존 패턴: {len(survivors)}개")
    emit(f"  기준: 각 기간 N 충분(전체≥100/최근1년≥50/최근2개월≥20) & 승률 ≥ baseline({baseline_wr:.1%}) + 2%p")
    emit("=" * 130)

    if survivors:
        emit("\n★ 생존 패턴 상세:")
        for p, stats in survivors:
            emit(f"\n  [{p['name']}]")
            for tag in ["전체 2년", "최근 1년", "최근 2개월"]:
                s = stats[tag]
                emit(f"    {tag}: N={s['n']}, 승률 {s['wr']:.1%}, PF {s['pf']:.2f}, "
                     f"평균수익 {s['avg_pr']*100:+.2f}%, 총 {s['total_pr']*100:+.1f}%")

    out = Path("results/pattern_discovery_v3.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
