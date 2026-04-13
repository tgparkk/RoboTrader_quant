#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
현재 운영 세팅 기준 전체 기간 시뮬 (실측 슬리피지 반영)

구성:
- TP 12% / SL 6%, portfolio 10
- buy_min_score 65, hard 65, soft 67, safe 75
- buy_ret5d_min = -3.0 (5일 급락 필터)
- score_momentum_min = 0.5 (점수 모멘텀 필터)
- slippage 0.25% (2026-04-13 실측 반영, models.py 기본값)

기간: 백테스트 DB에 있는 모든 기간 (quant_factors 기준 2023-01-02 ~ 2026-04-09)
연도별 breakdown 출력.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import BacktestParams
from scripts.signal_filter_multiverse import FilteredBacktester


def make_current_params():
    """현재 운영 세팅 그대로"""
    return BacktestParams(
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
        buy_ret5d_min=-3.0,
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
        regime_filter_enabled=False,
    )


def run_period(label: str, start: str, end: str):
    params = make_current_params()
    bt = FilteredBacktester(params=params, score_momentum_min=0.5)
    t0 = time.time()
    result = bt.backtest(start, end)
    elapsed = time.time() - t0
    wins = result.winning_trades
    losses = result.losing_trades
    total = wins + losses
    return {
        'label': label,
        'start': start, 'end': end,
        'total_return': result.total_return,
        'annualized': result.annualized_return,
        'sharpe': result.sharpe_ratio,
        'mdd': result.max_drawdown,
        'volatility': result.volatility,
        'wins': wins, 'losses': losses, 'total': total,
        'win_rate': result.win_rate,
        'profit_factor': result.profit_factor,
        'final_value': result.final_total_value,
        'elapsed': elapsed,
    }


def print_row(r):
    print(f"{r['label']:<10} {r['start']:<12}~{r['end']:<12} "
          f"총수익 {r['total_return']*100:>7.1f}%  "
          f"연환산 {r['annualized']*100:>6.1f}%  "
          f"샤프 {r['sharpe']:>5.2f}  "
          f"MDD {r['mdd']*100:>5.1f}%  "
          f"승률 {r['win_rate']*100:>5.1f}%  "
          f"PF {r['profit_factor']:>4.2f}  "
          f"거래 {r['total']:>4d}")


def main():
    print("=" * 110)
    print("현재 운영 세팅 전체 기간 시뮬 (슬리피지 0.25% 실측)")
    print("  TP 12% / SL 6% | portfolio 10 | buy_min_score 65 | ret5d≥-3% | sm≥0.5 | cooldown 3d")
    print("=" * 110)

    periods = [
        ('2023', '2023-01-01', '2023-12-31'),
        ('2024', '2024-01-01', '2024-12-31'),
        ('2025', '2025-01-01', '2025-12-31'),
        ('2026Q1+', '2026-01-01', '2026-04-09'),
        ('전체', '2023-01-02', '2026-04-09'),
    ]

    results = []
    for label, s, e in periods:
        print(f"\n[{label}] 실행 중...")
        r = run_period(label, s, e)
        results.append(r)
        print_row(r)
        print(f"  (소요 {r['elapsed']:.1f}s)")

    print("\n" + "=" * 110)
    print("요약")
    print("=" * 110)
    print(f"{'기간':<10} {'시작':<12}~{'종료':<12} {'총수익':>9} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5}")
    for r in results:
        print_row(r)

    print("\n[연환산 분포]")
    yearly = [r for r in results if r['label'] not in ('전체',)]
    ann_rets = [r['annualized']*100 for r in yearly]
    if ann_rets:
        print(f"  최소 {min(ann_rets):.1f}% / 중위 {sorted(ann_rets)[len(ann_rets)//2]:.1f}% / 최대 {max(ann_rets):.1f}%")

    print("\n[경고]")
    print("  - 이 수치는 생존자편향(상폐 미포함), 호가창 시장충격 미반영 등 추가 편향이 남아있음")
    print("  - 실전 동일 기간(2/12~4/13) 대비 수치 격차는 '엔진 편향'이 아니라 '분봉체결·수동개입' 차이")


if __name__ == "__main__":
    main()
