#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
공정 시뮬 vs 실전 비교 (2026-02-27 ~ 2026-03-26)

조건:
- 후보 규칙 일치 구간(2/27~3/26, Baseline=실전 100%)
- 시뮬 TP=16%, SL=8% (실전 당시 설정)
- 실전 손익에서 수동개입 제외
    * 3/9 "전종목 긴급 시장가 매도 (전쟁 리스크)" 10건
    * 3/4 "[수동매도] 앱 일괄매도" 3건
"""
import sys
import time
from pathlib import Path

import psycopg2
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import DB_CONFIG
from scripts.signal_filter_multiverse import FilteredBacktester


START_DATE = "2026-02-27"
END_DATE = "2026-03-26"


def live_stats(exclude_manual: bool) -> dict:
    where = [
        "action='SELL'",
        "timestamp >= '2026-02-27'",
        "timestamp < '2026-03-27'",
    ]
    if exclude_manual:
        where.append("reason NOT LIKE '%수동매도%'")
        where.append("reason NOT LIKE '%전쟁 리스크%'")

    sql = f"""
        SELECT
          COUNT(*) sells,
          COUNT(*) FILTER (WHERE profit_loss > 0) wins,
          COUNT(*) FILTER (WHERE profit_loss <= 0) losses,
          COALESCE(SUM(profit_loss),0)::bigint pnl,
          ROUND(AVG(profit_rate)::numeric, 3) avg_rate
        FROM real_trading_records
        WHERE {' AND '.join(where)}
    """
    with psycopg2.connect(**DB_CONFIG) as c:
        with c.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    return {
        'sells': row[0], 'wins': row[1], 'losses': row[2],
        'pnl': row[3], 'avg_rate': float(row[4]) if row[4] is not None else 0.0,
        'win_rate': row[1] / row[0] if row[0] else 0.0,
    }


def run_sim_baseline(tp: float, sl: float, score_momentum_min=None) -> dict:
    """시뮬 Baseline(total_score 정렬) + TP/SL + 선택 필터, 2/27~3/26"""
    params = BacktestParams(
        initial_capital=10_000_000,
        portfolio_size=10,
        target_profit_rate=tp,
        stop_loss_rate=sl,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        use_dynamic_targets=False,
        buy_cost_rate=0.00015,
        sell_cost_rate=0.00245,
        slippage_rate=0.001,
        regime_filter_enabled=False,
    )

    if score_momentum_min is not None:
        bt = FilteredBacktester(params=params, score_momentum_min=score_momentum_min)
    else:
        bt = Backtester(params=params)
    result = bt.backtest(START_DATE, END_DATE)
    wins = result.winning_trades
    losses = result.losing_trades
    return {
        'sells': wins + losses,
        'wins': wins, 'losses': losses,
        'pnl': int(result.final_total_value - params.initial_capital),
        'total_return': result.total_return,
        'sharpe': result.sharpe_ratio,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'profit_factor': result.profit_factor,
    }


def main():
    print("=" * 75)
    print("공정 시뮬 vs 실전 비교 (2026-02-27 ~ 2026-03-26)")
    print("  - 후보 규칙 일치 구간, Baseline(total_score)")
    print("  - 시뮬 TP=12% / SL=6% (현행 설정), 초기자본 1,000만원")
    print("=" * 75)

    print("\n[1/3] 실전 손익 (수동개입 포함, 전체) ...")
    live_all = live_stats(exclude_manual=False)

    print("\n[2/3] 실전 손익 (수동개입 제외: 3/9 전쟁, 3/4 앱) ...")
    live_adj = live_stats(exclude_manual=True)

    print("\n[3/3] 시뮬 실행 ...")
    t0 = time.time()
    sim_base = run_sim_baseline(tp=0.12, sl=0.06)
    sim_sm = run_sim_baseline(tp=0.12, sl=0.06, score_momentum_min=0.5)
    print(f"  시뮬 2종 완료 ({time.time()-t0:.1f}s)")

    print("\n" + "=" * 100)
    print(f"{'지표':<18} {'실전 전체':>14} {'실전 수동제외':>16} {'시뮬 기본':>18} {'시뮬+sm≥0.5':>18}")
    print("-" * 100)
    def row(label, va, vb, vc, vd, fmt='d'):
        print(f"{label:<18} {va:>14{fmt}} {vb:>16{fmt}} {vc:>18{fmt}} {vd:>18{fmt}}")
    row('매도 건수', live_all['sells'], live_adj['sells'], sim_base['sells'], sim_sm['sells'])
    row('승', live_all['wins'], live_adj['wins'], sim_base['wins'], sim_sm['wins'])
    row('패', live_all['losses'], live_adj['losses'], sim_base['losses'], sim_sm['losses'])
    print(f"{'승률':<18} {live_all['win_rate']*100:>13.1f}% {live_adj['win_rate']*100:>15.1f}% {sim_base['win_rate']*100:>17.1f}% {sim_sm['win_rate']*100:>17.1f}%")
    print(f"{'실현손익 (원)':<18} {live_all['pnl']:>+14,d} {live_adj['pnl']:>+16,d} {sim_base['pnl']:>+18,d} {sim_sm['pnl']:>+18,d}")
    print(f"{'평균 수익률':<18} {live_all['avg_rate']*100:>13.2f}% {live_adj['avg_rate']*100:>15.2f}% {'':>18} {'':>18}")
    print(f"{'샤프':<18} {'':>14} {'':>16} {sim_base['sharpe']:>18.2f} {sim_sm['sharpe']:>18.2f}")
    print(f"{'MDD':<18} {'':>14} {'':>16} {sim_base['mdd']*100:>17.2f}% {sim_sm['mdd']*100:>17.2f}%")
    print(f"{'PF':<18} {'':>14} {'':>16} {sim_base['profit_factor']:>18.2f} {sim_sm['profit_factor']:>18.2f}")
    print(f"{'총수익률':<18} {'':>14} {'':>16} {sim_base['total_return']*100:>17.2f}% {sim_sm['total_return']*100:>17.2f}%")
    print("=" * 100)
    sim = sim_sm  # for 해석 블럭 호환

    # 비교 해석
    print("\n[해석]")
    print(f"  실전 수동개입 비용: {live_all['pnl'] - live_adj['pnl']:+,d}원")
    print(f"     (3/9 전쟁 리스크 + 3/4 앱 일괄매도)")

    # 시뮬 대비 실전 수익률 (실전은 계좌규모 모르므로 건당 손익 비교)
    if live_adj['sells'] > 0 and sim['sells'] > 0:
        live_per_trade = live_adj['pnl'] / live_adj['sells']
        sim_per_trade = sim['pnl'] / sim['sells']
        print(f"  건당 실현손익: 실전 {live_per_trade:+,.0f}원 / 시뮬 {sim_per_trade:+,.0f}원")
        print(f"     (시뮬은 초기자본 5천만 기준, 실전은 실계좌)")


if __name__ == "__main__":
    main()
