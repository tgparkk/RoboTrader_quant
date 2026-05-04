#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
복합 최적화 멀티버스 — 모든 개선 후보의 조합 효과 검증

개선 후보:
  A. min_hold_days: 0 vs 3
  B. portfolio_size: 10 vs 12
  C. safe_score: 75 vs 70
  D. stop_loss_rate: 0.06 vs 0.05
  E. ret5d_min: None vs -0.03
  + buy_min_score=65 (고정, 현재 운영값)

총 2^5 = 32조합 × 전체기간 + 상위 후보 연도별 분할
"""
import sys
import time
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot

START_DATE = "2023-01-01"
END_DATE = "2026-02-28"

YEARLY_PERIODS = [
    ("2023-01-01", "2023-12-31", "2023"),
    ("2024-01-01", "2024-12-31", "2024"),
    ("2025-01-01", "2025-12-31", "2025"),
    ("2026-01-01", "2026-02-28", "2026Q1"),
]

# 고정값 (현재 운영 + 이번 분석에서 확인된 최적)
FIXED = dict(
    initial_capital=50_000_000,
    target_profit_rate=0.12,
    hard_stop_score=65.0,
    soft_stop_score=67.0,
    soft_stop_rank=30,
    safe_rank=25,
    max_hold_days=0,
    buy_min_score=65.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015,
    sell_cost_rate=0.00245,
    slippage_rate=0.001,
    regime_filter_enabled=False,
)

# 탐색 축 (현재값 vs 개선 후보)
AXES = {
    'min_hold_days':    [0, 3],
    'portfolio_size':   [10, 12],
    'safe_score':       [75.0, 70.0],
    'stop_loss_rate':   [0.06, 0.05],
    'buy_ret5d_min':    [None, -0.03],
}

AXIS_LABELS = {
    'min_hold_days':    {0: 'hold0', 3: 'hold3'},
    'portfolio_size':   {10: '10종', 12: '12종'},
    'safe_score':       {75.0: 'safe75', 70.0: 'safe70'},
    'stop_loss_rate':   {0.06: 'SL6', 0.05: 'SL5'},
    'buy_ret5d_min':    {None: 'ret5dOFF', -0.03: 'ret5d-3%'},
}

CURRENT_VALUES = {
    'min_hold_days': 0,
    'portfolio_size': 10,
    'safe_score': 75.0,
    'stop_loss_rate': 0.06,
    'buy_ret5d_min': None,
}


def load_data():
    params = BacktestParams(**{**FIXED, **CURRENT_VALUES})
    loader = Backtester(params=params)
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    return loader, trading_days


def run_fast(loader, trading_days, overrides: dict) -> dict:
    merged = {**FIXED, **CURRENT_VALUES, **overrides}
    params = BacktestParams(**merged)

    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = loader.daily_prices_cache
    bt.portfolio_cache = loader.portfolio_cache
    bt.factors_cache = loader.factors_cache

    prev_total_value = params.initial_capital
    for date in trading_days:
        bt._today_stop_profit_sold = set()
        bt._today_rebalancing_bought = set()
        bt._check_stop_profit_loss(date)
        bt._execute_rebalancing(date)

        total_value = bt._calculate_total_value(date)
        daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
        cumulative_return = (total_value - params.initial_capital) / params.initial_capital

        snapshot = DailySnapshot(
            date=date, capital=bt.capital,
            positions_value=total_value - bt.capital,
            total_value=total_value, position_count=len(bt.positions),
            daily_return=daily_return, cumulative_return=cumulative_return
        )
        bt.daily_snapshots.append(snapshot)
        prev_total_value = total_value

    bt._close_all_positions(trading_days[-1])
    result = bt._create_result(
        loader._normalize_date(START_DATE),
        loader._normalize_date(END_DATE),
        len(trading_days)
    )
    return {
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
    }


def run_full_backtest(overrides: dict, start: str, end: str) -> dict:
    """독립 백테스트 (연도별 분할용)"""
    merged = {**FIXED, **CURRENT_VALUES, **overrides}
    params = BacktestParams(**merged)
    bt = Backtester(params=params)
    result = bt.backtest(start, end)
    return {
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
    }


def make_label(combo: dict) -> str:
    parts = []
    for key in ['stop_loss_rate', 'portfolio_size', 'min_hold_days', 'safe_score', 'buy_ret5d_min']:
        val = combo[key]
        parts.append(AXIS_LABELS[key][val])
    return '/'.join(parts)


def count_changes(combo: dict) -> int:
    return sum(1 for k, v in combo.items() if v != CURRENT_VALUES[k])


def main():
    print("=" * 100)
    print("  복합 최적화 멀티버스 — 5축 × 2값 = 32조합")
    print(f"  기간: {START_DATE} ~ {END_DATE}")
    print(f"  고정: TP12%, hard_stop=65, buy_min_score=65")
    print("=" * 100)

    print("\n데이터 로딩 중...")
    loader, trading_days = load_data()
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    total_start = time.time()

    # ──────────────────────────────────────────────
    # Phase 1: 전체 32조합 백테스트
    # ──────────────────────────────────────────────
    print("=" * 100)
    print("  Phase 1: 전체 32조합 (전체기간)")
    print("=" * 100)

    axis_keys = list(AXES.keys())
    axis_values = [AXES[k] for k in axis_keys]

    all_results = []
    for combo_values in product(*axis_values):
        combo = dict(zip(axis_keys, combo_values))
        label = make_label(combo)
        r = run_fast(loader, trading_days, combo)
        changes = count_changes(combo)
        is_current = changes == 0
        all_results.append((label, combo, r, changes, is_current))

    # 샤프 순 정렬
    all_results.sort(key=lambda x: x[2]['sharpe'], reverse=True)

    print(f"\n{'순위':>4} {'변경':>2} {'조합':<45} {'샤프':>7} {'수익률':>9} {'MDD':>7} {'승률':>7} {'PF':>6} {'거래':>6}")
    print("-" * 100)
    best_sharpe = all_results[0][2]['sharpe']
    for i, (label, combo, r, changes, is_current) in enumerate(all_results, 1):
        marker = " ★현재" if is_current else ""
        if i <= 15 or is_current:
            print(f"{i:>4} {changes:>2}개  {label:<45} {r['sharpe']:>7.2f} {r['total_return']:>8.0%} "
                  f"{r['mdd']:>6.1%} {r['win_rate']:>6.1%} {r['pf']:>6.2f} {r['trades']:>6d}{marker}")

    # ──────────────────────────────────────────────
    # Phase 2: 개별 축 기여도 분석
    # ──────────────────────────────────────────────
    print(f"\n{'=' * 100}")
    print("  Phase 2: 개별 축 기여도 (다른 축 고정, 해당 축만 변경 시 평균 효과)")
    print(f"{'=' * 100}")

    for key in axis_keys:
        vals = AXES[key]
        current_val = CURRENT_VALUES[key]
        new_val = [v for v in vals if v != current_val][0]

        # 해당 축만 다른 조합들의 샤프 차이 평균
        diffs = []
        for combo_values in product(*axis_values):
            combo = dict(zip(axis_keys, combo_values))
            if combo[key] != current_val:
                continue
            # 현재값 조합
            r_current = [r for (_, c, r, _, _) in all_results if c == combo][0]
            # 변경값 조합
            combo_new = {**combo, key: new_val}
            r_new = [r for (_, c, r, _, _) in all_results if c == combo_new][0]
            diffs.append({
                'sharpe_diff': r_new['sharpe'] - r_current['sharpe'],
                'mdd_diff': r_new['mdd'] - r_current['mdd'],
                'return_diff': r_new['total_return'] - r_current['total_return'],
            })

        avg_sharpe = sum(d['sharpe_diff'] for d in diffs) / len(diffs)
        avg_mdd = sum(d['mdd_diff'] for d in diffs) / len(diffs)
        avg_return = sum(d['return_diff'] for d in diffs) / len(diffs)
        label_cur = AXIS_LABELS[key][current_val]
        label_new = AXIS_LABELS[key][new_val]

        direction = "+" if avg_sharpe > 0 else ""
        mdd_dir = "+" if avg_mdd > 0 else ""
        print(f"  {label_cur} → {label_new:<12}  샤프 {direction}{avg_sharpe:>6.2f}  "
              f"MDD {mdd_dir}{avg_mdd:>6.1%}  수익률 {avg_return:>+8.0%}  (16조합 평균)")

    # ──────────────────────────────────────────────
    # Phase 3: 상위 5개 + 현재 연도별 분할
    # ──────────────────────────────────────────────
    print(f"\n{'=' * 100}")
    print("  Phase 3: 상위 5개 + 현재 설정 — 연도별 분할 검증")
    print(f"{'=' * 100}")

    # 상위 5개 + 현재 설정
    top5 = all_results[:5]
    current = [x for x in all_results if x[4]][0]
    if current not in top5:
        top5.append(current)

    yearly_data = {}
    for label, combo, r_full, changes, is_current in top5:
        yearly_data[label] = {'전체': r_full}
        for start, end, period in YEARLY_PERIODS:
            r_year = run_full_backtest(combo, start, end)
            yearly_data[label][period] = r_year

    # 샤프 테이블
    print(f"\n{'[샤프 비율]'}")
    header = f"{'조합':<45}"
    periods = ['2023', '2024', '2025', '2026Q1', '전체']
    for p in periods:
        header += f" {p:>8}"
    header += f" {'최저':>8} {'안정성':>8}"
    print(header)
    print("-" * 110)

    for label, combo, _, changes, is_current in top5:
        row = f"{label:<45}"
        sharpes = []
        for p in periods:
            s = yearly_data[label][p]['sharpe']
            sharpes.append(s)
            row += f" {s:>8.2f}"
        yearly = sharpes[:-1]
        min_s = min(yearly)
        stability = min_s / sharpes[-1] if sharpes[-1] > 0 else 0
        marker = " ★" if is_current else ""
        row += f" {min_s:>8.2f} {stability:>8.2f}{marker}"
        print(row)

    # MDD 테이블
    print(f"\n{'[MDD]'}")
    header = f"{'조합':<45}"
    for p in periods:
        header += f" {p:>8}"
    print(header)
    print("-" * 110)

    for label, combo, _, changes, is_current in top5:
        row = f"{label:<45}"
        for p in periods:
            m = yearly_data[label][p]['mdd']
            row += f" {m:>7.1%}"
        marker = " ★" if is_current else ""
        row += marker
        print(row)

    # 거래수 테이블
    print(f"\n{'[거래수]'}")
    header = f"{'조합':<45}"
    for p in periods:
        header += f" {p:>8}"
    print(header)
    print("-" * 110)

    for label, combo, _, changes, is_current in top5:
        row = f"{label:<45}"
        for p in periods:
            t = yearly_data[label][p]['trades']
            row += f" {t:>8d}"
        marker = " ★" if is_current else ""
        row += marker
        print(row)

    # ──────────────────────────────────────────────
    # Phase 4: 슬리피지 스트레스 테스트 (상위 3개)
    # ──────────────────────────────────────────────
    print(f"\n{'=' * 100}")
    print("  Phase 4: 슬리피지 스트레스 테스트 (실전 괴리 대비)")
    print(f"{'=' * 100}")

    slippages = [0.001, 0.0015, 0.002, 0.003]
    top3_for_stress = all_results[:3] + [current] if current not in all_results[:3] else all_results[:3]

    header = f"{'조합':<45}"
    for s in slippages:
        header += f" {s:.2%}".rjust(10)
    print(header)
    print("-" * 100)

    for label, combo, _, _, is_current in top3_for_stress:
        row = f"{label:<45}"
        for slip in slippages:
            overrides = {**combo, 'slippage_rate': slip}
            r = run_fast(loader, trading_days, overrides)
            row += f" {r['sharpe']:>8.2f}"
            if slip == 0.001:
                row += "★" if is_current else " "
        print(row)

    # ──────────────────────────────────────────────
    # 요약
    # ──────────────────────────────────────────────
    total_elapsed = time.time() - total_start

    print(f"\n{'=' * 100}")
    print(f"  최종 요약")
    print(f"{'=' * 100}")

    current_r = [r for (_, _, r, _, is_c) in all_results if is_c][0]
    best_label, best_combo, best_r, best_changes, _ = all_results[0]

    print(f"\n  현재 설정: 샤프 {current_r['sharpe']:.2f}, MDD {current_r['mdd']:.1%}, 거래 {current_r['trades']}")
    print(f"  최적 조합: {best_label}")
    print(f"             샤프 {best_r['sharpe']:.2f} ({best_r['sharpe']-current_r['sharpe']:+.2f}), "
          f"MDD {best_r['mdd']:.1%} ({best_r['mdd']-current_r['mdd']:+.1%}), "
          f"거래 {best_r['trades']} ({best_changes}개 변경)")

    print(f"\n  총 소요: {total_elapsed:.0f}초")
    print(f"{'=' * 100}")


if __name__ == '__main__':
    main()
