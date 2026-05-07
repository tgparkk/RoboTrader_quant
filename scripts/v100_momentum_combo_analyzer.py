#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V100 + Momentum 조합 멀티버스 결과 분석기

입력: scripts/v100_momentum_combo_multiverse.py 가 생성한 parquet
출력: 콘솔 — Top robust 조합, baseline 비교, perturbation 안정성, Pareto front

Robust 정의 (4조건 모두 충족):
  1. 4개 연도(2023~2026) 모두 sharpe > 0
  2. overall sharpe ≥ baseline overall sharpe
  3. min(연도별 sharpe) ≥ baseline min(연도별)
  4. trades ≥ baseline × 0.7 (필터 과도 차단 방지)

Perturbation 안정성: Top 조합의 ±1 step 이웃에서 sharpe 하락 ≤ 10% 비율.

사용법:
    python scripts/v100_momentum_combo_analyzer.py
    python scripts/v100_momentum_combo_analyzer.py --input results/v100_momentum_combo.parquet
    python scripts/v100_momentum_combo_analyzer.py --top 20
"""
import sys
import io
import argparse
import math
from pathlib import Path

import pandas as pd
import numpy as np

# Windows cp949 콘솔에서 em-dash 등 유니코드 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

YEARS = ["2023", "2024", "2025", "2026"]

GRID = {
    'buy_momentum_score_min': [None, 30.0, 40.0, 50.0, 60.0, 70.0],
    'buy_ret20d_max':         [None, 30.0, 50.0, 80.0, 120.0],
    'buy_vol20d_max':         [None, 3.0, 4.0, 5.0, 6.0],
    'momentum_boost_alpha':   [0.0, 0.05, 0.1, 0.2, 0.3],
}


def fmt_param(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "OFF"
    if isinstance(v, float) and v == int(v):
        return f"{int(v)}"
    return f"{v}"


def is_baseline(row):
    return (
        (row['buy_momentum_score_min'] is None or pd.isna(row['buy_momentum_score_min']))
        and (row['buy_ret20d_max'] is None or pd.isna(row['buy_ret20d_max']))
        and (row['buy_vol20d_max'] is None or pd.isna(row['buy_vol20d_max']))
        and row['momentum_boost_alpha'] == 0.0
    )


def min_yearly_sharpe(row):
    vals = [row[f'sharpe_{y}'] for y in YEARS]
    vals = [v for v in vals if v == v]  # NaN 제외
    return min(vals) if vals else float('-inf')


def all_years_positive(row):
    for y in YEARS:
        v = row[f'sharpe_{y}']
        if v != v or v <= 0:
            return False
    return True


def perturbation_neighbors(row):
    """
    이웃 정의: 4개 축 각각에서 ±1 step (총 최대 8개 이웃)
    """
    neighbors = []
    for axis, values in GRID.items():
        cur = row[axis]
        # NaN/None을 인덱스로 변환
        try:
            if cur is None or (isinstance(cur, float) and pd.isna(cur)):
                idx = values.index(None)
            else:
                idx = next(i for i, v in enumerate(values) if v == cur)
        except (ValueError, StopIteration):
            continue
        for delta in (-1, +1):
            ni = idx + delta
            if 0 <= ni < len(values):
                nb = dict(row)
                nb[axis] = values[ni]
                neighbors.append(nb)
    return neighbors


def find_in_df(df, combo):
    mask = pd.Series([True] * len(df), index=df.index)
    for k, v in combo.items():
        if k not in GRID:
            continue
        if v is None or (isinstance(v, float) and pd.isna(v)):
            mask &= df[k].isna()
        else:
            mask &= df[k] == v
    rows = df[mask]
    return rows.iloc[0] if len(rows) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='results/v100_momentum_combo.parquet')
    ap.add_argument('--top', type=int, default=15)
    args = ap.parse_args()

    p = Path(args.input)
    if not p.exists():
        print(f"[ERROR] 결과 파일 없음: {p}")
        return 1

    df = pd.read_parquet(p)
    print("=" * 110)
    print(f"  V100 + Momentum 조합 멀티버스 분석 — {len(df)}개 조합")
    print(f"  입력: {p}")
    print("=" * 110)

    # 1. baseline 식별
    base_rows = df[df.apply(is_baseline, axis=1)]
    if len(base_rows) == 0:
        print("[ERROR] baseline (모두 None/0) 행 없음")
        return 1
    base = base_rows.iloc[0]
    base_min_year = min_yearly_sharpe(base)
    base_yearly = [round(base[f'sharpe_{y}'], 3) for y in YEARS]

    print(f"\nBASELINE (V100 buy_min_score=95, ret5d ∈ [-3, 17], 모멘텀 게이트/부스트 OFF)")
    print(f"  sharpe={base['sharpe']:.3f}  return={base['total_return']:+.1%}  "
          f"mdd={base['mdd']:.1%}  wr={base['win_rate']:.0%}  trades={int(base['trades'])}")
    print(f"  yearly={base_yearly}  min(yearly)={base_min_year:.3f}")

    # 2. Robust 4조건
    df['min_year_sharpe'] = df.apply(min_yearly_sharpe, axis=1)
    df['all_years_pos'] = df.apply(all_years_positive, axis=1)
    df['robust'] = (
        df['all_years_pos']
        & (df['sharpe'] >= base['sharpe'])
        & (df['min_year_sharpe'] >= base_min_year)
        & (df['trades'] >= base['trades'] * 0.7)
    )

    n_robust = int(df['robust'].sum())
    print(f"\nROBUST 정의: 4년 모두 sharpe>0, sharpe ≥ baseline, min(yearly) ≥ baseline min, trades ≥ base × 0.7")
    print(f"Robust 조합: {n_robust} / {len(df)}")

    if n_robust == 0:
        print("\n[기각 후보] Robust 조합 없음 — 운영 채택 게이트 미통과")
        # 그래도 상위 sharpe top 5 보여줌
        top = df.sort_values('sharpe', ascending=False).head(5)
        print("\nTop 5 by overall sharpe (robust 아님):")
        for _, r in top.iterrows():
            yearly = [round(r[f'sharpe_{y}'], 2) for y in YEARS]
            print(f"  M={fmt_param(r['buy_momentum_score_min']):>4} "
                  f"R={fmt_param(r['buy_ret20d_max']):>4} "
                  f"V={fmt_param(r['buy_vol20d_max']):>4} "
                  f"α={r['momentum_boost_alpha']:>4.2f} → "
                  f"sh {r['sharpe']:>+5.2f} ret {r['total_return']:>+6.1%} "
                  f"trd {int(r['trades']):>4} yearly={yearly}")
        return 0

    # 3. Top robust 출력
    print(f"\nTop {min(args.top, n_robust)} ROBUST (overall sharpe 순)")
    print("-" * 110)
    print(f"  {'M':>4} {'R':>4} {'V':>4} {'α':>5} │ "
          f"{'sharpe':>7} {'Δsh':>+6} {'return':>8} {'mdd':>6} {'wr':>4} "
          f"{'trd':>5} │ {'2023':>5} {'2024':>5} {'2025':>5} {'2026':>5} │ {'min_y':>6}")
    print("-" * 110)
    robust_top = df[df['robust']].sort_values('sharpe', ascending=False).head(args.top)
    for _, r in robust_top.iterrows():
        delta_sh = r['sharpe'] - base['sharpe']
        yearly = [r[f'sharpe_{y}'] for y in YEARS]
        print(f"  {fmt_param(r['buy_momentum_score_min']):>4} "
              f"{fmt_param(r['buy_ret20d_max']):>4} "
              f"{fmt_param(r['buy_vol20d_max']):>4} "
              f"{r['momentum_boost_alpha']:>5.2f} │ "
              f"{r['sharpe']:>+7.2f} {delta_sh:>+6.2f} {r['total_return']:>+8.1%} "
              f"{r['mdd']:>6.1%} {r['win_rate']:>4.0%} "
              f"{int(r['trades']):>5} │ "
              + " ".join(f"{v:>+5.2f}" if v == v else "  n/a" for v in yearly)
              + f" │ {r['min_year_sharpe']:>+6.2f}")

    # 4. Pareto front (sharpe vs min_year_sharpe)
    print(f"\nPareto Front (overall sharpe vs min_year_sharpe)")
    pf = df[df['robust']].copy().sort_values('sharpe', ascending=False)
    pareto_rows = []
    best_min_y = float('-inf')
    for _, r in pf.iterrows():
        if r['min_year_sharpe'] > best_min_y:
            pareto_rows.append(r)
            best_min_y = r['min_year_sharpe']
    print(f"  Pareto-optimal robust: {len(pareto_rows)}개")
    for r in pareto_rows[:10]:
        print(f"    M={fmt_param(r['buy_momentum_score_min']):>4} "
              f"R={fmt_param(r['buy_ret20d_max']):>4} "
              f"V={fmt_param(r['buy_vol20d_max']):>4} "
              f"α={r['momentum_boost_alpha']:>4.2f} → "
              f"sh {r['sharpe']:>+5.2f} min_y {r['min_year_sharpe']:>+5.2f} "
              f"trd {int(r['trades']):>4}")

    # 5. Perturbation 안정성 (Top 3 robust)
    print(f"\nPerturbation 안정성 (Top 3 robust, ±1 step 이웃 sharpe 하락폭)")
    for rank, (_, r) in enumerate(robust_top.head(3).iterrows(), 1):
        combo = {k: r[k] for k in GRID}
        nbrs = perturbation_neighbors(combo)
        drops = []
        for nb in nbrs:
            nb_row = find_in_df(df, nb)
            if nb_row is None:
                continue
            drop_pct = (r['sharpe'] - nb_row['sharpe']) / abs(r['sharpe']) * 100 if r['sharpe'] else 0
            drops.append((nb, nb_row['sharpe'], drop_pct))
        stable = sum(1 for _, _, d in drops if d <= 10)
        label = (f"M={fmt_param(r['buy_momentum_score_min'])} "
                 f"R={fmt_param(r['buy_ret20d_max'])} "
                 f"V={fmt_param(r['buy_vol20d_max'])} "
                 f"α={r['momentum_boost_alpha']:.2f}")
        print(f"  #{rank} {label}: sharpe {r['sharpe']:+.2f}, 이웃 {len(drops)}개 중 {stable}개 안정 (drop ≤ 10%)")
        for nb, nb_sh, d in drops[:6]:
            changed_axis = next((k for k in GRID if nb[k] != combo[k]), '?')
            print(f"      Δ{changed_axis}: {fmt_param(combo[changed_axis])}→{fmt_param(nb[changed_axis])} "
                  f"sharpe {nb_sh:+.2f} ({d:+.1f}%)")

    # 6. 운영 채택 게이트 평가
    print(f"\n{'=' * 110}")
    print("운영 채택 게이트 평가")
    print(f"{'=' * 110}")
    top1 = robust_top.iloc[0]
    top1_delta = top1['sharpe'] - base['sharpe']
    gate1 = n_robust >= 5
    gate2 = top1_delta >= 0.1
    print(f"  ① Robust 조합 ≥ 5     : {n_robust} → {'PASS' if gate1 else 'FAIL'}")
    print(f"  ② Top robust Δsharpe ≥ +0.1: {top1_delta:+.3f} → {'PASS' if gate2 else 'FAIL'}")
    print(f"  ③ Top perturbation ≥ 5/8 안정: 위 #1 결과 참조")
    print(f"  ④ 058430 5/7 시나리오: 별도 백테스트 필요 (multiverse 기간 2026-02-28까지)")

    if gate1 and gate2:
        print(f"\n  → 운영 채택 후보 #1: M={fmt_param(top1['buy_momentum_score_min'])} "
              f"R={fmt_param(top1['buy_ret20d_max'])} "
              f"V={fmt_param(top1['buy_vol20d_max'])} α={top1['momentum_boost_alpha']:.2f}")
    else:
        print(f"\n  → 게이트 미통과: 채택 보류, V100 단독 유지")

    return 0


if __name__ == "__main__":
    sys.exit(main())
