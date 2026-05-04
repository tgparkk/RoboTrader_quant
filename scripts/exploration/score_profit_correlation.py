#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
퀀트 점수 vs 실제 수익률 상관관계 분석

백테스트 1년 치 데이터로 점수(총점, 개별팩터)와 수익률의 상관관계를 측정합니다.
- 매수 시점 총점/개별팩터 점수 vs 해당 포지션 수익률
- 포트폴리오 순위 vs 수익률
- 점수 구간별 평균 수익률, 승률

사용법:
    python scripts/score_profit_correlation.py
    python scripts/score_profit_correlation.py --start 2024-03-01 --end 2026-02-26
"""
import sys
import re
import argparse
import numpy as np
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import TradeAction


def run_backtest(start_date: str, end_date: str) -> 'BacktestResult':
    """현재 라이브 설정으로 백테스트 실행"""
    params = BacktestParams(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.15,
        stop_loss_rate=0.08,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        min_hold_days=0,
        use_dynamic_targets=True,
        trading_cost_rate=0.0025,
    )
    bt = Backtester(params=params)
    return bt.backtest(start_date, end_date)


def extract_score_from_reason(reason: str):
    """매수 reason에서 순위/점수 추출: '리밸런싱 매수 (3위, 78.5점)'"""
    m = re.search(r'\((\d+)위,\s*([\d.]+)점\)', reason)
    if m:
        return int(m.group(1)), float(m.group(2))
    return None, None


def analyze_correlation(result):
    """매수-매도 쌍을 매칭하고 점수-수익률 상관관계 분석"""
    # 매수 기록 수집: (stock_code, date) -> trade
    buy_records = {}
    for t in result.trades:
        if t.action == TradeAction.BUY:
            buy_records[(t.stock_code, t.date)] = t

    # 매도에서 매수를 역추적 — 매수 시점의 점수를 사용
    # 매도 기록은 stock_code 기준으로 가장 최근 미매칭 매수와 페어링
    open_buys = defaultdict(list)  # stock_code -> [buy_trade, ...]
    pairs = []  # (buy_trade, sell_trade)

    for t in result.trades:
        if t.action == TradeAction.BUY:
            open_buys[t.stock_code].append(t)
        elif t.action == TradeAction.SELL:
            if open_buys[t.stock_code]:
                buy_t = open_buys[t.stock_code].pop(0)
                pairs.append((buy_t, t))

    print(f"\n총 매수-매도 쌍: {len(pairs)}건")
    print(f"(백테스트 종료 미매도 제외)\n")

    # 점수/순위/수익률 추출
    data = []
    for buy_t, sell_t in pairs:
        rank, score = extract_score_from_reason(buy_t.reason)
        if rank is None or score is None:
            continue
        # sell_t.profit_rate은 거래비용 포함 전 수익률
        data.append({
            'stock': buy_t.stock_name,
            'buy_date': buy_t.date,
            'sell_date': sell_t.date,
            'rank': rank,
            'score': score,
            'profit_rate': sell_t.profit_rate * 100,
            'profit_loss': sell_t.profit_loss,
            'reason': sell_t.reason,
        })

    if not data:
        print("분석 가능한 거래 없음")
        return

    scores = np.array([d['score'] for d in data])
    profits = np.array([d['profit_rate'] for d in data])
    ranks = np.array([d['rank'] for d in data])

    # ── 1. 전체 상관계수 ──
    print("=" * 70)
    print("1. 상관계수 (Pearson)")
    print("=" * 70)
    corr_score = np.corrcoef(scores, profits)[0, 1]
    corr_rank = np.corrcoef(ranks, profits)[0, 1]
    print(f"  총점 vs 수익률:     r = {corr_score:+.4f}")
    print(f"  순위 vs 수익률:     r = {corr_rank:+.4f}  (음수=점수높을수록 수익 높음)")

    # Spearman 순위 상관 (scipy 없이 직접 계산)
    def spearman_corr(x, y):
        """Spearman 순위 상관계수 + 근사 p-value"""
        n = len(x)
        rank_x = np.argsort(np.argsort(x)).astype(float)
        rank_y = np.argsort(np.argsort(y)).astype(float)
        rho = np.corrcoef(rank_x, rank_y)[0, 1]
        # t-분포 근사 p-value
        if abs(rho) < 1.0 and n > 2:
            t_stat = rho * np.sqrt((n - 2) / (1 - rho**2))
            # 양측 p-value 근사 (정규분포 근사, n>30이면 충분)
            from math import erfc, sqrt
            p_val = erfc(abs(t_stat) / sqrt(2))
        else:
            p_val = 0.0
        return rho, p_val

    spearman_score, p_score = spearman_corr(scores, profits)
    spearman_rank, p_rank = spearman_corr(ranks, profits)
    print(f"\n  [Spearman 순위 상관]")
    print(f"  총점 vs 수익률:     rho = {spearman_score:+.4f}  (p~{p_score:.4f})")
    print(f"  순위 vs 수익률:     rho = {spearman_rank:+.4f}  (p~{p_rank:.4f})")
    print(f"  -> p < 0.05면 통계적으로 유의미")

    # ── 2. 점수 구간별 성과 ──
    print(f"\n{'=' * 70}")
    print("2. 점수 구간별 성과")
    print("=" * 70)
    bins = [
        (80, 100, "80+  (최상위)"),
        (76, 80,  "76~80 (상위) "),
        (73, 76,  "73~76 (중상) "),
        (70, 73,  "70~73 (중위) "),
        (65, 70,  "65~70 (하위) "),
    ]
    print(f"  {'구간':>16} | {'건수':>5} | {'평균수익률':>9} | {'승률':>6} | {'평균+':>8} | {'평균-':>8}")
    print(f"  {'-' * 16}-+-{'-' * 5}-+-{'-' * 9}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 8}")
    for lo, hi, label in bins:
        mask = (scores >= lo) & (scores < hi) if hi < 100 else (scores >= lo)
        if mask.sum() == 0:
            continue
        p = profits[mask]
        wins = p[p > 0]
        losses = p[p <= 0]
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = losses.mean() if len(losses) > 0 else 0
        wr = len(wins) / len(p) * 100
        print(f"  {label} | {mask.sum():5d} | {p.mean():+8.2f}% | {wr:5.1f}% | {avg_win:+7.2f}% | {avg_loss:+7.2f}%")

    # ── 3. 포트폴리오 순위별 성과 ──
    print(f"\n{'=' * 70}")
    print("3. 포트폴리오 순위별 성과")
    print("=" * 70)
    print(f"  {'순위':>4} | {'건수':>5} | {'평균수익률':>9} | {'승률':>6} | {'총손익':>12}")
    print(f"  {'-' * 4}-+-{'-' * 5}-+-{'-' * 9}-+-{'-' * 6}-+-{'-' * 12}")
    for r in sorted(set(ranks)):
        mask = ranks == r
        p = profits[mask]
        pl = np.array([d['profit_loss'] for d, m in zip(data, mask) if m])
        wr = (p > 0).sum() / len(p) * 100
        print(f"  {r:4.0f} | {mask.sum():5d} | {p.mean():+8.2f}% | {wr:5.1f}% | {pl.sum():>+12,.0f}")

    # ── 4. 상위 vs 하위 비교 ──
    print(f"\n{'=' * 70}")
    print("4. 상위 5위 vs 하위 5위 비교")
    print("=" * 70)
    top5 = ranks <= 5
    bot5 = ranks > 5
    if top5.sum() > 0 and bot5.sum() > 0:
        p_top = profits[top5]
        p_bot = profits[bot5]
        print(f"  상위 1~5위:  {top5.sum():4d}건, 평균 {p_top.mean():+.2f}%, 승률 {(p_top > 0).sum() / len(p_top) * 100:.1f}%")
        print(f"  하위 6~10위: {bot5.sum():4d}건, 평균 {p_bot.mean():+.2f}%, 승률 {(p_bot > 0).sum() / len(p_bot) * 100:.1f}%")
        diff = p_top.mean() - p_bot.mean()
        print(f"  차이: {diff:+.2f}%p {'(상위 우세)' if diff > 0 else '(하위 우세)'}")

        # t-검정 (직접 계산)
        from math import erfc, sqrt
        n1, n2 = len(p_top), len(p_bot)
        if n1 > 1 and n2 > 1:
            var1, var2 = p_top.var(ddof=1), p_bot.var(ddof=1)
            se = sqrt(var1 / n1 + var2 / n2) if (var1 / n1 + var2 / n2) > 0 else 1e-10
            t_stat = (p_top.mean() - p_bot.mean()) / se
            t_pval = erfc(abs(t_stat) / sqrt(2))  # 정규 근사
            print(f"  t-검정: t={t_stat:.3f}, p~{t_pval:.4f} {'(유의미)' if t_pval < 0.05 else '(유의미하지 않음)'}")

    # ── 5. 매도 사유별 분석 ──
    print(f"\n{'=' * 70}")
    print("5. 매도 사유별 점수 분포")
    print("=" * 70)
    reason_groups = defaultdict(list)
    for d in data:
        # 매도 사유 분류
        r = d['reason']
        if '익절' in r:
            key = '익절'
        elif '손절' in r:
            key = '손절'
        elif '리밸런싱' in r:
            key = '리밸런싱'
        elif '백테스트종료' in r:
            key = '백테스트종료'
        else:
            key = '기타'
        reason_groups[key].append(d)

    print(f"  {'사유':>10} | {'건수':>5} | {'평균점수':>7} | {'평균수익률':>9} | {'승률':>6}")
    print(f"  {'-' * 10}-+-{'-' * 5}-+-{'-' * 7}-+-{'-' * 9}-+-{'-' * 6}")
    for reason_key in ['익절', '손절', '리밸런싱', '백테스트종료', '기타']:
        group = reason_groups.get(reason_key, [])
        if not group:
            continue
        s = np.array([d['score'] for d in group])
        p = np.array([d['profit_rate'] for d in group])
        wr = (p > 0).sum() / len(p) * 100
        print(f"  {reason_key:>10} | {len(group):5d} | {s.mean():6.1f} | {p.mean():+8.2f}% | {wr:5.1f}%")

    # ── 6. 결론 ──
    print(f"\n{'=' * 70}")
    print("6. 결론")
    print("=" * 70)
    print(f"  분석 건수: {len(data)}건 (최근 1년 백테스트)")
    print(f"  Pearson 상관계수:  r = {corr_score:+.4f}")
    print(f"  Spearman 순위상관: rho = {spearman_score:+.4f} (p={p_score:.4f})")
    if abs(spearman_score) < 0.1:
        print(f"  -> 점수와 수익률 사이에 의미있는 상관관계 없음")
    elif spearman_score > 0.1 and p_score < 0.05:
        print(f"  -> 점수가 높을수록 수익률이 높은 약한 양의 상관 (통계적 유의)")
    elif spearman_score < -0.1 and p_score < 0.05:
        print(f"  -> 점수가 높을수록 수익률이 낮은 역상관 (통계적 유의)")
    else:
        print(f"  -> 약한 상관이 있으나 통계적으로 유의미하지 않음")


def main():
    parser = argparse.ArgumentParser(description='퀀트 점수 vs 수익률 상관관계 분석')
    parser.add_argument('--start', type=str, default='2025-03-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-02-26', help='종료일')
    args = parser.parse_args()

    print(f"{'#' * 70}")
    print(f"퀀트 점수 vs 실제 수익률 상관관계 분석")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"{'#' * 70}")

    result = run_backtest(args.start, args.end)
    analyze_correlation(result)


if __name__ == '__main__':
    main()
