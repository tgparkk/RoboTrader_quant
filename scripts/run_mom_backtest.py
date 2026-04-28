#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mom_006676 운영 백테스트 + multiverse_min sim 비교 (T9 게이트).

실행 순서:
  1. quant_factors / quant_portfolio 의 [start_date, end_date] 범위 행 삭제
  2. backtest/factor_calculator.HistoricalFactorCalculator.calculate_all_factors
     를 mom 스코어링(T8.2 적용본)으로 재계산 → DB 저장
  3. backtest/backtester.Backtester.backtest 실행 → 메트릭 산출
  4. multiverse_min sim 결과 (sharpe 1.76, +78.9%, MDD -16.6%, 2024H2 -0.37) 와 ±10% 비교

⚠️ 주의:
  - robotrader_backtest DB 의 quant_factors / quant_portfolio 데이터를 덮어씀.
    V100 백테스트가 동일 DB 사용 중이라면 V100 팩터 데이터는 사라짐.
    필요 시 V100 워크트리에서 재계산.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import Backtester, BacktestParams
from backtest.factor_calculator import HistoricalFactorCalculator
from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection


SIM_TARGETS = {
    "sharpe":           {"target": 1.76,  "label": "Sharpe"},
    "total_return_pct": {"target": 78.9,  "label": "Total return %"},
    "mdd_pct":          {"target": -16.6, "label": "MDD %"},
}
TOLERANCE_PCT = 0.10


def _delete_existing_factors(start: str, end: str) -> None:
    sql_factors = "DELETE FROM quant_factors WHERE calc_date >= %s AND calc_date <= %s"
    sql_portfolio = "DELETE FROM quant_portfolio WHERE calc_date >= %s AND calc_date <= %s"
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cur = conn.cursor()
        cur.execute(sql_factors, (start_yyyymmdd, end_yyyymmdd))
        n_f = cur.rowcount
        cur.execute(sql_portfolio, (start_yyyymmdd, end_yyyymmdd))
        n_p = cur.rowcount
        conn.commit()
    print(f"[clean] deleted quant_factors={n_f}, quant_portfolio={n_p} in [{start_yyyymmdd}, {end_yyyymmdd}]")


def _recompute_factors(start: str, end: str, portfolio_size: int) -> None:
    print(f"[factors] recomputing mom factors for {start}~{end} (portfolio_size={portfolio_size})")
    calc = HistoricalFactorCalculator()
    calc.calculate_all_factors(start, end, portfolio_size=portfolio_size)


def _run_backtest(start: str, end: str) -> dict:
    params = BacktestParams(
        initial_capital=10_000_000,
    )
    print(f"[backtest] params:")
    print(f"  initial_capital   = {params.initial_capital:,}")
    print(f"  portfolio_size    = {params.portfolio_size}")
    print(f"  TP / SL           = {params.target_profit_rate} / {params.stop_loss_rate}")
    print(f"  hard/soft/safe    = {params.hard_stop_score} / {params.soft_stop_score} / {params.safe_score}")
    print(f"  buy_min_score     = {params.buy_min_score}")
    print(f"  slippage          = {params.slippage_rate}")
    print(f"  buy/sell cost     = {params.buy_cost_rate} / {params.sell_cost_rate}")

    bt = Backtester(params=params)
    t0 = time.time()
    result = bt.backtest(start, end)
    elapsed = time.time() - t0
    print(f"[backtest] done in {elapsed:.1f}s")
    return {
        "sharpe":           result.sharpe_ratio,
        "total_return_pct": result.total_return * 100.0,
        "mdd_pct":          result.max_drawdown * 100.0 * (-1.0 if result.max_drawdown > 0 else 1.0),
        "winning_trades":   result.winning_trades,
        "losing_trades":    result.losing_trades,
        "win_rate":         result.win_rate,
        "annualized":       result.annualized_return,
        "final_value":      result.final_total_value,
    }


def _compare_to_sim(metrics: dict) -> tuple[int, list[str]]:
    print("\n=== ±10% gate vs multiverse_min sim ===")
    failed = []
    for key, spec in SIM_TARGETS.items():
        actual = metrics.get(key)
        target = spec["target"]
        label = spec["label"]
        if actual is None:
            print(f"  {label:<18} actual=MISSING")
            failed.append(label)
            continue
        if abs(target) < 1e-9:
            ok = abs(actual) < TOLERANCE_PCT
        else:
            ok = abs(actual - target) / abs(target) <= TOLERANCE_PCT
        status = "OK" if ok else "FAIL"
        print(f"  {label:<18} actual={actual:>+8.3f}  target={target:>+8.3f}  [{status}]")
        if not ok:
            failed.append(label)
    n_pass = len(SIM_TARGETS) - len(failed)
    return n_pass, failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-07-01")
    parser.add_argument("--end", default="2026-03-31")
    parser.add_argument("--portfolio-size", type=int, default=15)
    parser.add_argument("--skip-recompute", action="store_true",
                        help="quant_factors 재계산 생략 (이전 mom run 결과 재사용)")
    args = parser.parse_args()

    if not args.skip_recompute:
        _delete_existing_factors(args.start, args.end)
        _recompute_factors(args.start, args.end, args.portfolio_size)
    else:
        print("[clean] --skip-recompute: 기존 quant_factors 사용")

    metrics = _run_backtest(args.start, args.end)
    print("\n=== Backtest metrics ===")
    print(json.dumps(metrics, indent=2, default=str))

    n_pass, failed = _compare_to_sim(metrics)
    print(f"\nGate: {n_pass}/{len(SIM_TARGETS)} pass")
    if n_pass >= 2:
        print("[GATE] SUCCESS - paper trading 진입 가능")
    else:
        print(f"[GATE] FAIL - sim 격차 조사 필요. failed={failed}")


if __name__ == "__main__":
    main()
