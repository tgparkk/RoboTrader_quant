#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실전 quant_portfolio (live) vs 시뮬 Two-stage 후보 비교

실전 DB의 `quant_portfolio` 테이블에 저장된 일자별 10종목 후보와
시뮬(Two-stage hybrid_score 정렬) 결과를 일자별로 비교한다.
"""
import sys
from pathlib import Path

import psycopg2
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.db_config import DB_CONFIG, BACKTEST_DB_CONFIG
from backtest.factor_calculator import calc_timing_score


START = "2026-02-12"
END = "2026-03-26"


def load_live_portfolio() -> dict:
    """live DB quant_portfolio → {yyyymmdd: [stock_code...]}"""
    with psycopg2.connect(**DB_CONFIG) as conn:
        df = pd.read_sql_query(
            """SELECT calc_date, stock_code, rank
               FROM quant_portfolio
               WHERE calc_date >= %s AND calc_date <= %s
               ORDER BY calc_date, rank""",
            conn, params=(START.replace('-', ''), END.replace('-', ''))
        )
    return {d: grp.sort_values('rank')['stock_code'].tolist()
            for d, grp in df.groupby('calc_date')}


def build_sim_baseline(dates: list[str]) -> dict:
    """backtest DB로 Baseline(total_score 정렬) 후보 재계산 → {yyyymmdd: [stock_code top10]}"""
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        factors = pd.read_sql_query(
            """SELECT calc_date, stock_code, total_score, factor_rank
               FROM quant_factors
               WHERE calc_date >= %s AND calc_date <= %s""",
            conn, params=(dates[0], dates[-1])
        )

    result = {}
    for yyyymmdd in dates:
        day = factors[factors['calc_date'] == yyyymmdd]
        if day.empty:
            continue
        eligible = day[day['total_score'] >= 65.0]
        top = eligible.sort_values(['total_score', 'factor_rank'], ascending=[False, True]).head(10)
        result[yyyymmdd] = top['stock_code'].tolist()
    return result


def main():
    print("실전 quant_portfolio 로드 중...")
    live = load_live_portfolio()
    dates = sorted(live.keys())
    print(f"  실전 후보 커버: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

    print("\n시뮬 Baseline(total_score) 재계산 중...")
    sim = build_sim_baseline(dates)
    print(f"  시뮬 후보 커버: {len(sim)}일")

    print(f"\n{'날짜':<10} {'공통':>4}  {'실전만':<55}  {'시뮬만':<55}")
    print("-" * 135)
    overlaps = []
    for d in dates:
        lv = set(live[d])
        sm = set(sim.get(d, []))
        common = lv & sm
        only_live = sorted(lv - sm)
        only_sim = sorted(sm - lv)
        overlaps.append(len(common))
        ol_str = ','.join(only_live)[:55]
        os_str = ','.join(only_sim)[:55]
        print(f"{d:<10} {len(common):>3}/10  {ol_str:<55}  {os_str:<55}")

    avg = sum(overlaps) / len(overlaps)
    print(f"\n평균 겹침: {avg:.1f}/10 ({avg*10:.0f}%)")
    print(f"완전 일치일: {sum(1 for o in overlaps if o == 10)}/{len(overlaps)}")


if __name__ == "__main__":
    main()
