#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TP/SL 후보 연도별 분할 분석 + 실전 슬리피지 분석

상위 후보 조합을 연도별로 분할 백테스트하여 안정성을 검증합니다.
"""
import sys
import time
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


# 분석 대상 후보
CANDIDATES = [
    (0.12, 0.05, "TP12/SL5 (1위)"),
    (0.12, 0.06, "TP12/SL6 (현재)"),
    (0.12, 0.07, "TP12/SL7"),
    (0.14, 0.05, "TP14/SL5"),
    (0.14, 0.06, "TP14/SL6"),
    (0.22, 0.05, "TP22/SL5"),
    (0.22, 0.06, "TP22/SL6"),
    (0.25, 0.05, "TP25/SL5 (2위)"),
    (0.20, 0.05, "TP20/SL5 (3위)"),
    (0.16, 0.08, "TP16/SL8 (이전)"),
]

# 연도별 구간
PERIODS = [
    ("2023-01-01", "2023-12-31", "2023"),
    ("2024-01-01", "2024-12-31", "2024"),
    ("2025-01-01", "2025-12-31", "2025"),
    ("2026-01-01", "2026-02-28", "2026Q1"),
    ("2023-01-01", "2026-02-28", "전체"),
]


def run_single(tp, sl, start, end):
    """단일 조합 백테스트 실행"""
    params = BacktestParams(
        portfolio_size=10,
        target_profit_rate=tp,
        stop_loss_rate=sl,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        use_dynamic_targets=False,
    )
    bt = Backtester(params=params)
    result = bt.backtest(start, end)
    return result


def main():
    print("=" * 100)
    print("TP/SL 후보 연도별 분할 분석")
    print("=" * 100)

    # 1. 연도별 분할 분석
    all_results = {}
    total_start = time.time()

    for tp, sl, label in CANDIDATES:
        all_results[label] = {}
        for start, end, period_name in PERIODS:
            result = run_single(tp, sl, start, end)
            all_results[label][period_name] = {
                'sharpe': result.sharpe_ratio,
                'total_return': result.total_return,
                'mdd': result.max_drawdown,
                'win_rate': result.win_rate,
                'trades': result.total_trades,
                'pf': result.profit_factor,
                'ann_return': result.annualized_return,
            }

    elapsed = time.time() - total_start
    print(f"\n총 {len(CANDIDATES) * len(PERIODS)}회 백테스트 완료 ({elapsed:.0f}초)\n")

    # 2. 결과 테이블 출력 - 샤프 비율
    print("=" * 100)
    print("[ 샤프 비율 연도별 ]")
    print("=" * 100)
    header = f"{'조합':<22}"
    for _, _, name in PERIODS:
        header += f" {name:>8}"
    header += f" {'최저':>8} {'편차':>8} {'안정성':>8}"
    print(header)
    print("-" * 100)

    stability_scores = {}
    for tp, sl, label in CANDIDATES:
        row = f"{label:<22}"
        sharpes = []
        for _, _, name in PERIODS:
            s = all_results[label][name]['sharpe']
            sharpes.append(s)
            row += f" {s:>8.2f}"

        yearly_sharpes = sharpes[:-1]  # 전체 제외
        min_s = min(yearly_sharpes)
        std_s = (sum((x - sum(yearly_sharpes)/len(yearly_sharpes))**2 for x in yearly_sharpes) / len(yearly_sharpes)) ** 0.5
        # 안정성 = 최저/전체 (1에 가까울수록 안정)
        stability = min_s / sharpes[-1] if sharpes[-1] > 0 else 0
        stability_scores[label] = stability
        row += f" {min_s:>8.2f} {std_s:>8.2f} {stability:>8.2f}"
        print(row)

    # 3. 결과 테이블 - MDD
    print(f"\n{'=' * 100}")
    print("[ MDD 연도별 ]")
    print("=" * 100)
    header = f"{'조합':<22}"
    for _, _, name in PERIODS:
        header += f" {name:>8}"
    header += f" {'최대MDD':>8}"
    print(header)
    print("-" * 100)

    for tp, sl, label in CANDIDATES:
        row = f"{label:<22}"
        mdds = []
        for _, _, name in PERIODS:
            m = all_results[label][name]['mdd']
            mdds.append(m)
            row += f" {m:>7.1%}"
        max_mdd = max(mdds)
        row += f" {max_mdd:>7.1%}"
        print(row)

    # 4. 결과 테이블 - 승률
    print(f"\n{'=' * 100}")
    print("[ 승률 연도별 ]")
    print("=" * 100)
    header = f"{'조합':<22}"
    for _, _, name in PERIODS:
        header += f" {name:>8}"
    print(header)
    print("-" * 100)

    for tp, sl, label in CANDIDATES:
        row = f"{label:<22}"
        for _, _, name in PERIODS:
            w = all_results[label][name]['win_rate']
            row += f" {w:>7.1%}"
        print(row)

    # 5. 결과 테이블 - 거래 횟수
    print(f"\n{'=' * 100}")
    print("[ 거래 횟수 연도별 ]")
    print("=" * 100)
    header = f"{'조합':<22}"
    for _, _, name in PERIODS:
        header += f" {name:>8}"
    print(header)
    print("-" * 100)

    for tp, sl, label in CANDIDATES:
        row = f"{label:<22}"
        for _, _, name in PERIODS:
            t = all_results[label][name]['trades']
            row += f" {t:>8d}"
        print(row)

    # 6. 종합 순위 (샤프×안정성)
    print(f"\n{'=' * 100}")
    print("[ 종합 순위: 전체샤프 × 안정성 ]")
    print("=" * 100)
    rankings = []
    for tp, sl, label in CANDIDATES:
        full_sharpe = all_results[label]['전체']['sharpe']
        stab = stability_scores[label]
        composite = full_sharpe * stab
        rankings.append((label, full_sharpe, stab, composite,
                         all_results[label]['전체']['mdd'],
                         all_results[label]['전체']['trades']))

    rankings.sort(key=lambda x: x[3], reverse=True)
    print(f"{'순위':>4} {'조합':<22} {'전체샤프':>8} {'안정성':>8} {'종합':>8} {'MDD':>8} {'거래수':>8}")
    print("-" * 80)
    for i, (label, sharpe, stab, comp, mdd, trades) in enumerate(rankings, 1):
        print(f"{i:>4} {label:<22} {sharpe:>8.2f} {stab:>8.2f} {comp:>8.2f} {mdd:>7.1%} {trades:>8d}")

    # 7. 연도별 1위 확인
    print(f"\n{'=' * 100}")
    print("[ 연도별 샤프 1위 ]")
    print("=" * 100)
    for _, _, period_name in PERIODS:
        best_label = max(
            [(label, all_results[label][period_name]['sharpe']) for _, _, label in CANDIDATES],
            key=lambda x: x[1]
        )
        print(f"  {period_name}: {best_label[0]} (샤프 {best_label[1]:.2f})")


if __name__ == '__main__':
    main()
