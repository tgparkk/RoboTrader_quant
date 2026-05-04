#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
재무 공시 지연 반영 + 가중치 V25/M30/Q22.5/G22.5로 팩터 재생성

기존 quant_factors/quant_portfolio(look-ahead 버전)를 지정 구간에서 삭제 후,
HistoricalFactorCalculator를 호출해 재생성한다.
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from config.db_config import BACKTEST_DB_CONFIG
from backtest.factor_calculator import HistoricalFactorCalculator


def delete_range(start_yyyymmdd: str, end_yyyymmdd: str):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM quant_portfolio WHERE calc_date >= %s AND calc_date <= %s",
            (start_yyyymmdd, end_yyyymmdd),
        )
        n_p = c.rowcount
        c.execute(
            "DELETE FROM quant_factors WHERE calc_date >= %s AND calc_date <= %s",
            (start_yyyymmdd, end_yyyymmdd),
        )
        n_f = c.rowcount
        conn.commit()
    return n_f, n_p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-04-01")
    ap.add_argument("--end", default="2026-04-09")
    ap.add_argument("--quarterly-lag", type=int, default=45)
    ap.add_argument("--annual-lag", type=int, default=90)
    ap.add_argument("--portfolio-size", type=int, default=50,
                    help="저장할 포트폴리오 상위 N (백테스터가 자체적으로 상위 10만 사용)")
    args = ap.parse_args()

    start_ymd = args.start.replace("-", "")
    end_ymd = args.end.replace("-", "")

    print("=" * 70)
    print("팩터 재생성 (look-ahead 제거 + 공시 지연 반영)")
    print("=" * 70)
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  공시 지연: 분기 {args.quarterly_lag}일 / 연간 {args.annual_lag}일")
    print(f"  포트폴리오 저장: 상위 {args.portfolio_size}")
    print("=" * 70)

    print(f"\n[1/2] 기존 데이터 삭제 ({start_ymd} ~ {end_ymd})...")
    n_f, n_p = delete_range(start_ymd, end_ymd)
    print(f"  quant_factors: {n_f:,}건, quant_portfolio: {n_p:,}건 삭제")

    print(f"\n[2/2] 팩터 재계산 시작...")
    t0 = time.time()
    calc = HistoricalFactorCalculator(
        quarterly_lag=args.quarterly_lag,
        annual_lag=args.annual_lag,
    )
    calc.calculate_all_factors(args.start, args.end, portfolio_size=args.portfolio_size)
    elapsed = time.time() - t0
    print(f"\n완료 (소요 {elapsed/60:.1f}분)")


if __name__ == "__main__":
    main()
