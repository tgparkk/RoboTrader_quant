#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
운영 DB(robotrader_quant)의 daily_prices / quant_factors 를
백테스트 DB(robotrader_backtest)로 UPSERT 동기화.

대상 기간: 2026-02-27 이후 (백테스트 DB가 손상/공백인 구간)
"""
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.db_config import BACKTEST_DB_CONFIG, DB_CONFIG  # DB_CONFIG = 운영 DB


DAILY_PRICES_COLS = [
    "stock_code", "date", "open", "high", "low", "close",
    "volume", "trading_value", "market_cap",
    "returns_1d", "returns_5d", "returns_20d", "volatility_20d",
]

QUANT_FACTORS_COLS = [
    "calc_date", "stock_code",
    "value_score", "momentum_score", "quality_score", "growth_score",
    "total_score", "factor_rank", "factor_details",
]


def sync_daily_prices(start_date: str, batch: int = 5000) -> int:
    """start_date(YYYY-MM-DD) 이후 운영 → 백테스트 UPSERT"""
    cols_sql = ", ".join(DAILY_PRICES_COLS)
    update_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in DAILY_PRICES_COLS if c not in ("stock_code", "date"))
    insert_sql = f"""
        INSERT INTO daily_prices ({cols_sql}) VALUES %s
        ON CONFLICT (stock_code, date) DO UPDATE SET {update_sql}
    """

    with psycopg2.connect(**DB_CONFIG) as src, psycopg2.connect(**BACKTEST_DB_CONFIG) as dst:
        with src.cursor() as sc:
            sc.execute(
                f"SELECT {cols_sql} FROM daily_prices WHERE date >= %s ORDER BY date, stock_code",
                (start_date,),
            )
            total = 0
            with dst.cursor() as dc:
                while True:
                    rows = sc.fetchmany(batch)
                    if not rows:
                        break
                    execute_values(dc, insert_sql, rows, page_size=batch)
                    total += len(rows)
                    print(f"  daily_prices: {total:,}건 UPSERT", flush=True)
            dst.commit()
    return total


def sync_quant_factors(start_calc_date: str, batch: int = 5000) -> int:
    """start_calc_date(YYYYMMDD) 이후 운영 → 백테스트 UPSERT"""
    cols_sql = ", ".join(QUANT_FACTORS_COLS)
    update_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in QUANT_FACTORS_COLS if c not in ("calc_date", "stock_code"))
    insert_sql = f"""
        INSERT INTO quant_factors ({cols_sql}) VALUES %s
        ON CONFLICT (calc_date, stock_code) DO UPDATE SET {update_sql}
    """

    with psycopg2.connect(**DB_CONFIG) as src, psycopg2.connect(**BACKTEST_DB_CONFIG) as dst:
        with src.cursor() as sc:
            sc.execute(
                f"SELECT {cols_sql} FROM quant_factors WHERE calc_date >= %s ORDER BY calc_date, stock_code",
                (start_calc_date,),
            )
            total = 0
            with dst.cursor() as dc:
                while True:
                    rows = sc.fetchmany(batch)
                    if not rows:
                        break
                    execute_values(dc, insert_sql, rows, page_size=batch)
                    total += len(rows)
                    print(f"  quant_factors: {total:,}건 UPSERT", flush=True)
            dst.commit()
    return total


def verify(label: str, sql_bt: str, sql_q: str):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as bt, psycopg2.connect(**DB_CONFIG) as q:
        with bt.cursor() as c:
            c.execute(sql_bt)
            bt_rows = c.fetchall()
        with q.cursor() as c:
            c.execute(sql_q)
            q_rows = c.fetchall()
    print(f"\n[{label}] 검증 (backtest vs quant)")
    bt_map = {r[0]: r[1] for r in bt_rows}
    q_map = {r[0]: r[1] for r in q_rows}
    for d in sorted(set(bt_map) | set(q_map)):
        print(f"  {d}: backtest={bt_map.get(d, 0):>6}  quant={q_map.get(d, 0):>6}")


def main():
    print("=" * 70)
    print("운영 DB → 백테스트 DB 동기화")
    print("=" * 70)

    print("\n[1/2] daily_prices 동기화 (2026-02-27~)")
    n1 = sync_daily_prices("2026-02-27")
    print(f"  완료: {n1:,}건")

    print("\n[2/2] quant_factors 동기화 (20260227~)")
    n2 = sync_quant_factors("20260227")
    print(f"  완료: {n2:,}건")

    verify(
        "daily_prices",
        """SELECT date, COUNT(DISTINCT stock_code) FROM daily_prices
           WHERE date >= '2026-02-27' AND stock_code NOT IN ('KS11','KQ11')
           GROUP BY date ORDER BY date""",
        """SELECT date, COUNT(DISTINCT stock_code) FROM daily_prices
           WHERE date >= '2026-02-27'
           GROUP BY date ORDER BY date""",
    )
    verify(
        "quant_factors",
        """SELECT calc_date, COUNT(DISTINCT stock_code) FROM quant_factors
           WHERE calc_date >= '20260227' GROUP BY calc_date ORDER BY calc_date""",
        """SELECT calc_date, COUNT(DISTINCT stock_code) FROM quant_factors
           WHERE calc_date >= '20260227' GROUP BY calc_date ORDER BY calc_date""",
    )


if __name__ == "__main__":
    main()
