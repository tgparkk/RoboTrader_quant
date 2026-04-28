#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mom_006676 운영 백테스트 vs multiverse_min sim 종목 픽 비교.

각 월초 첫 거래일에서:
  1. 운영 백테스트의 top-15 (quant_portfolio 테이블)
  2. sim 방식 (multiverse_min indicators.py mom_rskip_12_1 panel) 으로 top-15 직접 재계산
  3. set diff + 일치도 출력

목적: T9 +49pp outperform 의 원인이 "픽 자체의 차이" 인지 "미세 numerical 노이즈" 인지 판별.
  - 일치도 >= 80%: 운영 백테스트의 alpha 는 sim 픽과 거의 동일 → 미세 차이
  - 일치도 <= 40%: scoring/필터 자체가 다른 결과 → 디버깅 필요
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection
from utils.trading_calendar import is_first_trading_day_of_month


SAMPLE_MONTHS = [
    (2024, 7), (2024, 9), (2024, 11),
    (2025, 1), (2025, 3), (2025, 6), (2025, 9), (2025, 12),
    (2026, 2),
]


def _first_trading_day(y: int, m: int) -> date:
    d = date(y, m, 1)
    while not is_first_trading_day_of_month(d):
        d = date(d.year, d.month, d.day + 1)
        if d.day > 28:
            raise RuntimeError(f"no trading day found in {y}-{m}")
    return d


def _our_top15(calc_date_iso: str) -> list[tuple[str, float]]:
    """운영 백테스트 top-15: quant_portfolio (rank ≤ 15) 또는 quant_factors top-15."""
    cd = calc_date_iso.replace("-", "")
    sql = """
        SELECT stock_code, total_score, factor_rank
        FROM quant_factors
        WHERE calc_date = %s
        ORDER BY total_score DESC
        LIMIT 15
    """
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cur = conn.cursor()
        cur.execute(sql, (cd,))
        rows = cur.fetchall()
    return [(r[0], float(r[1])) for r in rows]


def _sim_top15(calc_date_iso: str) -> list[tuple[str, float]]:
    """sim 방식 top-15: mom_rskip_12_1 패널을 cross-section 으로 직접 계산.

    multiverse_min indicators.py:209-219 식과 동일.
    cap_min ≥ 3e12 필터.
    """
    # 충분한 warmup (lookback 12*21 + skip 1*21 = 273 거래일 ≈ 395 달력일 + 여유) 위해 500일 로드
    end_dt = datetime.strptime(calc_date_iso, "%Y-%m-%d").date()
    start_dt = pd.Timestamp(end_dt) - pd.Timedelta(days=500)
    sql = """
        SELECT stock_code, date, close, market_cap
        FROM daily_prices
        WHERE date >= %s AND date <= %s AND stock_code NOT IN ('KS11', 'KQ11')
    """
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        df = pd.read_sql_query(
            sql, conn,
            params=(start_dt.strftime("%Y-%m-%d"), calc_date_iso),
        )

    if df.empty:
        return []

    # 와이드 panel
    close_panel = df.pivot(index="date", columns="stock_code", values="close").sort_index()
    cap_panel = df.pivot(index="date", columns="stock_code", values="market_cap").sort_index()

    # multiverse_min mom_rskip_12_1 식 (indicators.py:209-219)
    skip_days, lb_days = 1 * 21, 12 * 21
    shifted = close_panel.shift(skip_days)
    mom_12_1 = shifted / shifted.shift(lb_days) - 1
    vol_20 = close_panel.pct_change(fill_method=None).rolling(20, min_periods=20).std()
    mom_rskip_12_1 = mom_12_1 / vol_20

    # 패널 index 는 string ('YYYY-MM-DD'). 직접 slice.
    if calc_date_iso in mom_rskip_12_1.index:
        as_of = calc_date_iso
    else:
        # fallback: 가장 최근 available date
        valid = [d for d in mom_rskip_12_1.index if d <= calc_date_iso]
        if not valid:
            return []
        as_of = valid[-1]

    scores = mom_rskip_12_1.loc[as_of].dropna()
    caps = cap_panel.loc[as_of].dropna()

    # cap_min >= 3e12 필터
    eligible = caps[caps >= 3e12].index
    scores = scores.reindex(eligible).dropna()

    top15 = scores.sort_values(ascending=False).head(15)
    return [(code, float(s)) for code, s in top15.items()]


def main() -> None:
    print(f"{'date':<12} {'our_top':>3} {'sim_top':>3} {'overlap':>7} {'pct':>6}  union/missed")
    print("-" * 100)
    overlaps = []
    for y, m in SAMPLE_MONTHS:
        d = _first_trading_day(y, m)
        d_iso = d.isoformat()

        ours = _our_top15(d_iso)
        sim = _sim_top15(d_iso)
        ours_set = {c for c, _ in ours}
        sim_set = {c for c, _ in sim}
        overlap = ours_set & sim_set
        only_ours = ours_set - sim_set
        only_sim = sim_set - ours_set
        pct = (len(overlap) / 15 * 100) if (ours and sim) else 0.0
        overlaps.append(pct)

        print(f"{d_iso:<12} {len(ours):>3} {len(sim):>3} {len(overlap):>7} {pct:>5.1f}%  ours-only={sorted(only_ours)[:5]}{'...' if len(only_ours)>5 else ''}  sim-only={sorted(only_sim)[:5]}{'...' if len(only_sim)>5 else ''}")

    if overlaps:
        avg = sum(overlaps) / len(overlaps)
        print("-" * 100)
        print(f"평균 일치도: {avg:.1f}% (n={len(overlaps)} 샘플)")
        if avg >= 80:
            print("→ 픽이 거의 같음. outperform 은 미세 numerical/체결 차이 누적.")
        elif avg >= 50:
            print("→ 절반 이상 일치. 부분 점수 차이 + 부분 픽 차이 혼재.")
        else:
            print("→ 픽 자체가 갈림. scoring/필터 디버깅 필요.")


if __name__ == "__main__":
    main()
