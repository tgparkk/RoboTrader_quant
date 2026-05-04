#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실전 매매 기록 기반 승/패 패턴 탐색

설계:
  1. V100 + TP12/SL6 + 10종목 실전 백테스트 실행 → 실제 거래 ~280건 획득
  2. 각 거래에 D-1 시점 피처 붙이기 (20개)
  3. 승/패 거래의 피처 분포 비교 (Cohen's d, quintile)
  4. 유의미한 패턴 찾기 (승률 차이 큰 것)
  5. 찾은 패턴을 "매수 회피 조건"으로 실전 백테스터에 적용
  6. 개선된 성과 측정
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
from backtest.models import DailySnapshot, TradeAction
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
# V100 cache 구성 (raw value_score)
# ═══════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════
# 피처 계산 (20개)
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
        if closes[i] > closes[i-1]: obv[i] = obv[i-1] + volumes[i]
        elif closes[i] < closes[i-1]: obv[i] = obv[i-1] - volumes[i]
        else: obv[i] = obv[i-1]

    def ema(vals, p):
        a = 2/(p+1); e = np.zeros_like(vals); e[0] = vals[0]
        for i in range(1, len(vals)): e[i] = a*vals[i] + (1-a)*e[i-1]
        return e
    macd_hist = ema(closes, 12) - ema(closes, 26)
    macd_hist = macd_hist - ema(macd_hist, 9)

    stoch_k = np.full(n, np.nan)
    for i in range(14, n):
        ph = np.max(highs[i-13:i+1]); pl = np.min(lows[i-13:i+1])
        if ph > pl: stoch_k[i] = (closes[i]-pl)/(ph-pl)*100

    for idx in range(1, n):
        d = str(dates[idx]); prev = idx-1
        feat = {}
        p_h, p_l, p_o, p_c = highs[prev], lows[prev], opens[prev], closes[prev]
        rng = p_h - p_l
        feat['body_ratio'] = abs(p_c-p_o)/rng if rng > 0 else None
        feat['upper_shadow'] = (p_h-max(p_o,p_c))/rng if rng > 0 else None
        feat['lower_shadow'] = (min(p_o,p_c)-p_l)/rng if rng > 0 else None
        feat['gap_up'] = (p_o-closes[prev-1])/closes[prev-1] if prev >= 1 and closes[prev-1] > 0 else None
        if prev >= 20:
            va = volumes[prev-20:prev].mean()
            feat['vol_spike'] = volumes[prev]/va if va > 0 else None
            ma20 = closes[prev-19:prev+1].mean()
            std20 = closes[prev-19:prev+1].std()
            feat['bb_position'] = (p_c-ma20)/(2*std20) if std20 > 0 else 0
        else:
            feat['vol_spike'] = None
            feat['bb_position'] = None
        feat['turnover'] = trading_values[prev]/market_caps[prev] if market_caps[prev] > 0 else None
        if prev >= 20:
            x = np.arange(20); y = obv[prev-19:prev+1]
            if y.std() > 0:
                slope, _ = np.polyfit(x, y, 1)
                feat['obv_slope'] = slope / (abs(obv[prev])+1)
            else:
                feat['obv_slope'] = 0
        else:
            feat['obv_slope'] = None
        feat['macd_hist'] = float(macd_hist[prev])/(abs(p_c)+1) if p_c > 0 else None
        v = stoch_k[prev]
        feat['stoch_k'] = None if np.isnan(v) else float(v)
        if prev >= 250:
            h52 = highs[prev-249:prev+1].max()
            l52 = lows[prev-249:prev+1].min()
            feat['pct_52w_high'] = p_c/h52 if h52 > 0 else None
            feat['pct_52w_low'] = (p_c/l52-1) if l52 > 0 else None
        else:
            feat['pct_52w_high'] = None
            feat['pct_52w_low'] = None
        r20 = returns_20d[prev] if not pd.isna(returns_20d[prev]) else None
        k1 = kospi_closes.get(str(dates[prev]))
        k21 = kospi_closes.get(str(dates[prev-20])) if prev >= 20 else None
        feat['rs_20d_kospi'] = r20 - (k1/k21-1) if (r20 is not None and k1 and k21 and k21 > 0) else None
        def s(v): return None if pd.isna(v) else float(v)
        feat['vol_20d'] = s(volatility_20d[prev])
        feat['ret_5d'] = s(returns_5d[prev])
        feat['ret_20d'] = s(returns_20d[prev])
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
                'fn_5d': float(fn[max(0,prev-4):prev+1].sum()) if prev >= 4 else None,
                'fn_20d': float(fn[max(0,prev-19):prev+1].sum()) if prev >= 19 else None,
            }
            if prev >= 20 and not pd.isna(hp[prev]) and not pd.isna(hp[prev-20]):
                feat['fh_chg_20d'] = float(hp[prev] - hp[prev-20])
            else:
                feat['fh_chg_20d'] = None
            out[(code, dates[idx])] = feat
    return out


# ═══════════════════════════════════════════════════════════════
# 실전 백테스트 → Trade log
# ═══════════════════════════════════════════════════════════════
def run_backtest_collect_trades(factors, portfolio, prices, params, start, end):
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
    logging.disable(logging.CRITICAL)
    try:
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)
        bt._close_all_positions(trading_days[-1])
    finally:
        logging.disable(logging.NOTSET)

    # 거래 매칭
    open_buys = defaultdict(list)
    pairs = []
    for t in bt.trades:
        if t.action == TradeAction.BUY:
            open_buys[t.stock_code].append(t)
        else:
            if open_buys[t.stock_code]:
                b = open_buys[t.stock_code].pop(0)
                pairs.append((b, t))

    log = []
    for b, s in pairs:
        log.append({
            'buy_date': b.date,
            'stock_code': b.stock_code,
            'buy_price': b.price,
            'sell_date': s.date,
            'sell_price': s.price,
            'profit_rate': s.profit_rate,
            'win': s.profit_rate > 0,
            'reason': s.reason,
        })
    return log


# ═══════════════════════════════════════════════════════════════
# 분석
# ═══════════════════════════════════════════════════════════════
def attach_features(trade_log, per_stock_feats):
    enriched = []
    for t in trade_log:
        key = (t['stock_code'], t['buy_date'].replace("-", ""))
        feats = per_stock_feats.get(key)
        if feats is None:
            continue
        row = dict(t)
        row.update({f'feat_{k}': v for k, v in feats.items()})
        enriched.append(row)
    return enriched


def univariate_analysis(df, feat_names, min_samples=20):
    results = []
    wins = df[df['win']]
    losses = df[~df['win']]
    for f in feat_names:
        col = f'feat_{f}'
        w = wins[col].dropna()
        l = losses[col].dropna()
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


def tercile_winrate(df, feat):
    """3분할 승률 (적은 표본이라 quintile 대신 tercile)"""
    col = f'feat_{feat}'
    valid = df.dropna(subset=[col]).copy()
    if len(valid) < 30:
        return None
    try:
        valid['t'] = pd.qcut(valid[col], 3, labels=['저', '중', '고'], duplicates='drop')
    except Exception:
        return None
    return valid.groupby('t').agg(
        n=('win', 'count'), wr=('win', 'mean'),
        avg_pr=('profit_rate', 'mean'),
    )


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  실전 매매 기록 기반 승/패 패턴 탐색 (자본 1,000만원 기준)")
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
    emit(f"  {time.time()-t0:.1f}초, {len(days)}거래일")

    # KOSPI
    kospi_df = prices.get('KS11')
    kospi_closes = {}
    if kospi_df is not None:
        for d, row in kospi_df.iterrows():
            kospi_closes[str(d).replace("-", "")] = float(row['close'])
            kospi_closes[str(d)] = float(row['close'])

    fc, pc = build_v100_cache(saved_factors, saved_portfolio)

    print("\n[2/4] V100 실전 백테스트 (거래 수집)...", flush=True)
    t1 = time.time()
    trade_log = run_backtest_collect_trades(
        fc, pc, prices, common_params(), "2024-04-01", "2026-04-09"
    )
    emit(f"  {time.time()-t1:.1f}초, 총 거래: {len(trade_log)}건")
    wins = sum(1 for t in trade_log if t['win'])
    emit(f"  승: {wins} ({wins/len(trade_log)*100:.1f}%), 패: {len(trade_log)-wins}")

    print("\n[3/4] 피처 계산 + 붙이기...", flush=True)
    t2 = time.time()
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

    # 거래에 등장한 종목만 피처 계산 (시간 절약)
    traded_codes = set(t['stock_code'] for t in trade_log)
    per_stock_feats = {}
    for code in traded_codes:
        g = prices_df[prices_df['stock_code'] == code].reset_index(drop=True)
        if len(g) < 60:
            continue
        res = compute_features_for_stock(g, kospi_closes)
        for d, feats in res.items():
            key = (code, d)
            inv = investor_feats.get(key)
            if inv:
                feats.update(inv)
            else:
                for k in ['fn_5d', 'fn_20d', 'fh_chg_20d']:
                    feats.setdefault(k, None)
            per_stock_feats[key] = feats
    emit(f"  {time.time()-t2:.1f}초, 피처 계산 종목 {len(traded_codes)}")

    enriched = attach_features(trade_log, per_stock_feats)
    df = pd.DataFrame(enriched)
    emit(f"  피처 붙인 거래: {len(df)}건 (승률 {df['win'].mean():.1%})")

    FEATURES = ['body_ratio','upper_shadow','lower_shadow','gap_up','vol_spike','turnover',
                'obv_slope','bb_position','macd_hist','stoch_k','pct_52w_high','pct_52w_low',
                'rs_20d_kospi','vol_20d','ret_5d','ret_20d','fn_5d','fn_20d','fh_chg_20d']

    print("\n[4/4] 분석...", flush=True)

    # 단변량
    emit("")
    emit("=" * 120)
    emit("단변량 승/패 분포 (|Cohen's d| 큰 순)")
    emit("=" * 120)
    uni = univariate_analysis(df, FEATURES, min_samples=20)
    emit(f"{'Feature':<18} {'승 평균':>12} {'패 평균':>12} {'d':>6} {'승 N':>5} {'패 N':>5}")
    emit("-" * 70)
    for r in uni:
        emit(f"{r['feature']:<18} {r['win_mean']:>12.4f} {r['loss_mean']:>12.4f} "
             f"{r['d_effect']:>+6.2f} {r['n_wins']:>5} {r['n_losses']:>5}")

    # Top 피처 Tercile
    emit("")
    emit("=" * 120)
    emit("Top 8 피처 3분할 승률")
    emit("=" * 120)
    for r in uni[:8]:
        f = r['feature']
        tr = tercile_winrate(df, f)
        if tr is None: continue
        emit(f"\n[{f}]")
        emit(tr.to_string())

    # 구체적 필터 후보 (tercile 극단에서 승률 높은 것)
    emit("")
    emit("=" * 120)
    emit("유망 필터 후보 (극단 tercile 승률 vs 전체)")
    emit("=" * 120)
    baseline_wr = df['win'].mean()
    emit(f"전체 승률: {baseline_wr:.1%}\n")

    candidates = []
    for r in uni[:10]:
        f = r['feature']
        tr = tercile_winrate(df, f)
        if tr is None: continue
        col = f'feat_{f}'
        valid = df[col].dropna()
        if len(valid) < 30: continue
        q = valid.quantile([1/3, 2/3]).values
        lo_th, hi_th = q[0], q[1]

        # 저 tercile 승률이 높으면 <= 조건 좋음 (즉 값이 낮은 것만 매수)
        lo_wr = tr.loc['저', 'wr']
        hi_wr = tr.loc['고', 'wr']
        if lo_wr > baseline_wr + 0.05 and tr.loc['저', 'n'] >= 20:
            # 매수 회피 조건: feature > lo_th (즉 저 tercile만 매수)
            candidates.append({
                'label': f"{f} <= {lo_th:.3f} (저tercile만 매수)",
                'feat': f, 'op': '<=', 'val': lo_th,
                'expected_wr': lo_wr, 'n_in_lo': int(tr.loc['저', 'n']),
            })
        if hi_wr > baseline_wr + 0.05 and tr.loc['고', 'n'] >= 20:
            candidates.append({
                'label': f"{f} >= {hi_th:.3f} (고tercile만 매수)",
                'feat': f, 'op': '>=', 'val': hi_th,
                'expected_wr': hi_wr, 'n_in_lo': int(tr.loc['고', 'n']),
            })

    for c in candidates:
        emit(f"  {c['label']:<45}  기대 승률 {c['expected_wr']:.1%}, 해당 거래 N={c['n_in_lo']}")

    if not candidates:
        emit("  (유의미한 필터 후보 없음)")

    # 2변량 승률 분석 (Top 5 피처 쌍)
    emit("")
    emit("=" * 120)
    emit("2변량 교집합 승률 (Top 5 피처 쌍, 각 tercile)")
    emit("=" * 120)
    top5 = [r['feature'] for r in uni[:5]]
    biv_candidates = []
    for i in range(len(top5)):
        for j in range(i+1, len(top5)):
            f1, f2 = top5[i], top5[j]
            c1, c2 = f'feat_{f1}', f'feat_{f2}'
            valid = df.dropna(subset=[c1, c2]).copy()
            if len(valid) < 50: continue
            try:
                valid[f'{f1}_t'] = pd.qcut(valid[c1], 3, labels=['저','중','고'], duplicates='drop')
                valid[f'{f2}_t'] = pd.qcut(valid[c2], 3, labels=['저','중','고'], duplicates='drop')
            except Exception:
                continue
            group = valid.groupby([f'{f1}_t', f'{f2}_t']).agg(
                n=('win', 'count'), wr=('win', 'mean')
            )
            for idx, row in group.iterrows():
                if row['n'] >= 15 and row['wr'] >= baseline_wr + 0.10:
                    biv_candidates.append({
                        'f1': f1, 'f1_t': idx[0], 'f2': f2, 'f2_t': idx[1],
                        'n': int(row['n']), 'wr': row['wr'],
                    })

    biv_candidates.sort(key=lambda x: x['wr'], reverse=True)
    for b in biv_candidates[:10]:
        emit(f"  {b['f1']}={b['f1_t']} & {b['f2']}={b['f2_t']}  N={b['n']}, 승률 {b['wr']:.1%}")
    if not biv_candidates:
        emit("  (2변량 조합 N>=15 승률+10%p 이상 없음)")

    out = Path("results/win_loss_patterns.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
