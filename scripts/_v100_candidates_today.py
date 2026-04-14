"""
오늘(2026-04-14) V100 매수후보 리스트업 (읽기 전용, DB 무변경)

- calc_date=20260413의 value_score + daily_prices로 timing_score 계산
- hybrid_score = value_score * 0.50 + timing_score * 0.50
- buy_min_score=95 / buy_min_score=65 두 기준으로 top 출력
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from config.pg_helper import pg_connection


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def calc_timing_score(closes):
    if closes is None or len(closes) < 61:
        return 50.0
    vals = np.asarray(closes, dtype=float)
    latest = vals[-1]

    ma60 = np.mean(vals[-60:])
    ma60_dist = (latest - ma60) / ma60 * 100 if ma60 > 0 else 0
    if ma60_dist <= -10:
        ma60_score = 100.0
    elif ma60_dist <= 0:
        ma60_score = 70.0 + (-ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 10:
        ma60_score = 40.0 + (10.0 - ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 20:
        ma60_score = 10.0 + (20.0 - ma60_dist) / 10.0 * 30.0
    else:
        ma60_score = 10.0

    ref_20d = vals[-21]
    ret_20d = (latest - ref_20d) / ref_20d * 100.0 if ref_20d > 0 else 0.0
    ret_score = clamp(60.0 - ret_20d * 2.0, 0.0, 100.0)

    daily_returns = np.diff(vals[-21:]) / vals[-21:-1]
    vol = float(np.std(daily_returns)) * (252 ** 0.5) * 100.0
    vol_score = clamp(100.0 - vol * 1.25, 0.0, 100.0)

    ma20 = np.mean(vals[-20:])
    ma20_dist = (latest - ma20) / ma20 * 100.0 if ma20 > 0 else 0.0
    ma20_score = clamp(60.0 - ma20_dist * 3.0, 0.0, 100.0)

    return clamp(ma60_score * 0.40 + ret_score * 0.30 + vol_score * 0.20 + ma20_score * 0.10, 0.0, 100.0)


def main():
    calc_date = '20260413'
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT stock_code, value_score, momentum_score, quality_score, growth_score, factor_rank
            FROM quant_factors WHERE calc_date=%s
        """, (calc_date,))
        rows = cur.fetchall()

        results = []
        for stock_code, v, m, q, g, rk in rows:
            cur.execute("""
                SELECT close FROM daily_prices
                WHERE stock_code=%s AND date <= %s
                ORDER BY date DESC LIMIT 80
            """, (stock_code, calc_date))
            closes = [r[0] for r in cur.fetchall()]
            if len(closes) < 61:
                continue
            closes.reverse()
            ts = calc_timing_score(closes)
            hybrid = v * 0.50 + ts * 0.50
            results.append((stock_code, v, m, q, g, rk, ts, hybrid))

        cur.execute("""
            SELECT DISTINCT ON (stock_code) stock_code, stock_name
            FROM candidate_stocks WHERE stock_name IS NOT NULL
            ORDER BY stock_code, selection_date DESC
        """)
        names = dict(cur.fetchall())
        cur.execute("""
            SELECT DISTINCT ON (stock_code) stock_code, stock_name
            FROM quant_portfolio WHERE stock_name IS NOT NULL
            ORDER BY stock_code, calc_date DESC
        """)
        for code, nm in cur.fetchall():
            names.setdefault(code, nm)

    df = pd.DataFrame(results, columns=['code','V','M','Q','G','rk','timing','hybrid'])
    df['name'] = df['code'].map(lambda c: names.get(c, ''))

    print(f"\n=== V100 기준 (value_score >= 95) — {len(df[df.V>=95])}종목 ===")
    top = df[df.V >= 95].sort_values('hybrid', ascending=False).head(20)
    print(top[['code','name','V','timing','hybrid','M','Q','G']].to_string(index=False,
          formatters={'V':'{:.1f}'.format,'timing':'{:.1f}'.format,'hybrid':'{:.1f}'.format,
                      'M':'{:.1f}'.format,'Q':'{:.1f}'.format,'G':'{:.1f}'.format}))

    print(f"\n=== hybrid_score top 10 (value_score>=65 조건, 저녁 스크리닝 예상 top 10) ===")
    top10 = df[df.V >= 65].sort_values('hybrid', ascending=False).head(10)
    print(top10[['code','name','V','timing','hybrid','M','Q','G']].to_string(index=False,
          formatters={'V':'{:.1f}'.format,'timing':'{:.1f}'.format,'hybrid':'{:.1f}'.format,
                      'M':'{:.1f}'.format,'Q':'{:.1f}'.format,'G':'{:.1f}'.format}))


if __name__ == '__main__':
    main()
