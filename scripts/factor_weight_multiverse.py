#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
팩터 가중치 멀티버스 백테스트

4개 팩터(Value, Momentum, Quality, Growth) 가중치를 변경하며 최적 조합을 탐색합니다.
데이터를 한 번만 로드하고, 가중치별로 total_score를 재계산하여 포트폴리오를 재구성합니다.

백테스트 DB의 포트폴리오는 total_score 기준 순위입니다 (hybrid_score 이전 데이터).

사용법:
    python scripts/factor_weight_multiverse.py
    python scripts/factor_weight_multiverse.py --start 2023-01-01 --end 2026-04-09
    python scripts/factor_weight_multiverse.py --step 0.05
    python scripts/factor_weight_multiverse.py --output results/factor_weights.csv
"""
import sys
import time
import argparse
import pandas as pd
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


# ─────────────────────────────────────────────────────────────
# 가중치 조합 생성
# ─────────────────────────────────────────────────────────────
def generate_weight_combinations(step=0.05,
                                  v_range=(0.00, 0.40),
                                  m_range=(0.10, 0.50),
                                  q_range=(0.05, 0.40),
                                  g_range=(0.05, 0.30)):
    """합계 1.0, 각 팩터 범위 제약 하에 유효 조합 생성"""
    combos = set()
    precision = 3

    def frange(lo, hi):
        vals = []
        x = lo
        while x <= hi + 1e-9:
            vals.append(round(x, precision))
            x += step
        return vals

    for v in frange(*v_range):
        for m in frange(*m_range):
            for g in frange(*g_range):
                q = round(1.0 - v - m - g, precision)
                if q_range[0] - 1e-9 <= q <= q_range[1] + 1e-9:
                    combos.add((round(v, precision), round(m, precision),
                                round(q, precision), round(g, precision)))

    return sorted(combos)


# ─────────────────────────────────────────────────────────────
# 캐시 재구성 (가중치 적용)
# ─────────────────────────────────────────────────────────────
def rebuild_caches(saved_factors, stock_names,
                   v_w, m_w, q_w, g_w, portfolio_top_n=50):
    """
    가중치를 적용하여 factors_cache와 portfolio_cache를 재구성합니다.
    - total_score = V*val + M*mom + Q*qual + G*grow (가중치 변경)
    - 포트폴리오 + factor_rank 모두 total_score 기준 순위 (백테스트 DB 구조)
    """
    new_factors = {}
    new_portfolio = {}

    for calc_date, stocks in saved_factors.items():
        new_stocks = {}
        scored_list = []  # (stock_code, total_score)

        for stock_code, f in stocks.items():
            new_total = (
                f.get('value_score', 0) * v_w +
                f.get('momentum_score', 0) * m_w +
                f.get('quality_score', 0) * q_w +
                f.get('growth_score', 0) * g_w
            )

            new_f = {
                'calc_date': f.get('calc_date', calc_date),
                'stock_code': stock_code,
                'value_score': f.get('value_score', 0),
                'momentum_score': f.get('momentum_score', 0),
                'quality_score': f.get('quality_score', 0),
                'growth_score': f.get('growth_score', 0),
                'total_score': new_total,
                'factor_rank': 0,  # 아래에서 설정
            }
            new_stocks[stock_code] = new_f
            scored_list.append((stock_code, new_total))

        # total_score 기준 순위 (포트폴리오 + factor_rank 동일)
        scored_list.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored_list, 1):
            new_stocks[code]['factor_rank'] = rank

        new_factors[calc_date] = new_stocks

        # 포트폴리오: total_score 기준 상위 N종목
        portfolio_entries = []
        for rank, (code, tscore) in enumerate(scored_list[:portfolio_top_n], 1):
            portfolio_entries.append({
                'calc_date': calc_date,
                'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank,
                'total_score': tscore,
                'reason': f'score {tscore:.1f}',
            })
        new_portfolio[calc_date] = portfolio_entries

    return new_factors, new_portfolio


# ─────────────────────────────────────────────────────────────
# 멀티버스 실행
# ─────────────────────────────────────────────────────────────
def run_multiverse(start_date: str, end_date: str,
                   combinations: list, base_params: BacktestParams,
                   output_csv: str = None):
    total_combos = len(combinations)
    current_weights = (0.30, 0.30, 0.20, 0.20)

    print(f"\n{'=' * 80}")
    print(f"팩터 가중치 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"총 조합: {total_combos}개")
    print(f"현행: V={current_weights[0]:.0%} M={current_weights[1]:.0%} "
          f"Q={current_weights[2]:.0%} G={current_weights[3]:.0%}")
    print(f"TP/SL: {base_params.target_profit_rate:.0%}/{base_params.stop_loss_rate:.0%}, "
          f"포트폴리오: {base_params.portfolio_size}종목, "
          f"buy_min: {base_params.buy_min_score}")
    print(f"{'=' * 80}\n")

    # ── 1. 데이터 한 번만 로드 ──
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    saved_prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목, "
          f"{len(saved_factors)}일 팩터")

    # ── 2. 종목명 룩업 ──
    stock_names = {}
    for portfolio in saved_portfolio.values():
        for item in portfolio:
            stock_names[item['stock_code']] = item.get('stock_name', item['stock_code'])

    # ── 3. 멀티버스 루프 ──
    results = []
    total_start = time.time()

    for i, (v_w, m_w, q_w, g_w) in enumerate(combinations, 1):
        combo_start = time.time()

        # 캐시 재구성
        new_factors, new_portfolio = rebuild_caches(
            saved_factors, stock_names,
            v_w, m_w, q_w, g_w,
            portfolio_top_n=base_params.portfolio_size * 5,
        )

        # 백테스터 + 캐시 주입
        bt = Backtester(params=base_params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = new_portfolio
        bt.factors_cache = new_factors

        # 시뮬레이션 루프
        prev_total_value = base_params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)

            total_value = bt._calculate_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cumulative_return = (total_value - base_params.initial_capital) / base_params.initial_capital

            bt.daily_snapshots.append(DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total_value - bt.capital,
                total_value=total_value, position_count=len(bt.positions),
                daily_return=daily_return, cumulative_return=cumulative_return,
            ))
            prev_total_value = total_value

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))

        combo_elapsed = time.time() - combo_start
        is_current = (v_w, m_w, q_w, g_w) == current_weights
        marker = " ★ 현행" if is_current else ""

        results.append({
            'value_w': v_w, 'momentum_w': m_w, 'quality_w': q_w, 'growth_w': g_w,
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
        })

        print(f"  [{i:3d}/{total_combos}] V{v_w:4.0%} M{m_w:4.0%} Q{q_w:4.0%} G{g_w:4.0%} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"거래 {result.total_trades:>4d}  ({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # ── 4. 결과 정렬 및 출력 ──
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 90}")
    print(f"멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 90}")
    print(f"{'순위':>4} {'Value':>6} {'Mom':>6} {'Qual':>6} {'Grow':>6} "
          f"{'총수익률':>10} {'연환산':>8} {'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5}")
    print(f"{'-' * 90}")

    current_rank = None
    for rank, r in enumerate(results, 1):
        if (r['value_w'], r['momentum_w'], r['quality_w'], r['growth_w']) == current_weights:
            current_rank = rank

    for rank, r in enumerate(results, 1):
        is_current = (r['value_w'], r['momentum_w'], r['quality_w'], r['growth_w']) == current_weights
        marker = " ◀ 현행" if is_current else ""
        if rank <= 30 or is_current:
            print(f"{rank:4d}. {r['value_w']:5.0%} {r['momentum_w']:5.0%} "
                  f"{r['quality_w']:5.0%} {r['growth_w']:5.0%} "
                  f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
                  f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
                  f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} {r['total_trades']:>5d}{marker}")

    print(f"{'-' * 90}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    if current_rank:
        print(f"현행 V30/M30/Q20/G20 → {current_rank}위/{total_combos}")
    print(f"{'=' * 90}")

    # ── 5. 팩터별 분석 ──
    print_factor_analysis(results, current_weights)

    # ── 6. CSV 저장 ──
    if output_csv:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


# ─────────────────────────────────────────────────────────────
# 분석 출력
# ─────────────────────────────────────────────────────────────
def print_factor_analysis(results: list, current_weights: tuple):
    """팩터별 최적 가중치 분석"""
    print(f"\n{'=' * 70}")
    print(f"팩터별 분석")
    print(f"{'=' * 70}")

    factors = ['value_w', 'momentum_w', 'quality_w', 'growth_w']
    labels = ['Value', 'Momentum', 'Quality', 'Growth']

    # Top 10, Top 20 평균
    for n, label in [(10, '상위 10개'), (20, '상위 20개')]:
        top = results[:n]
        print(f"\n{label} 조합 평균 가중치:")
        for f, l, cw in zip(factors, labels, current_weights):
            avg = sum(r[f] for r in top) / len(top)
            delta = avg - cw
            arrow = "↑" if delta > 0.01 else "↓" if delta < -0.01 else "="
            print(f"  {l:10s}: {avg:5.1%}  (현행 {cw:.0%}, {arrow} {delta:+.1%}p)")

    # Value=0 vs Value>0 비교
    no_val = [r for r in results if r['value_w'] == 0]
    with_val = [r for r in results if r['value_w'] > 0]
    if no_val and with_val:
        avg_s_no = sum(r['sharpe_ratio'] for r in no_val) / len(no_val)
        avg_s_with = sum(r['sharpe_ratio'] for r in with_val) / len(with_val)
        best_no = max(no_val, key=lambda x: x['sharpe_ratio'])
        best_with = max(with_val, key=lambda x: x['sharpe_ratio'])

        print(f"\nValue=0% vs Value>0%:")
        print(f"  Value=0%  → 평균 샤프 {avg_s_no:.2f}, 최고 {best_no['sharpe_ratio']:.2f} "
              f"(M{best_no['momentum_w']:.0%}/Q{best_no['quality_w']:.0%}/G{best_no['growth_w']:.0%})")
        print(f"  Value>0%  → 평균 샤프 {avg_s_with:.2f}, 최고 {best_with['sharpe_ratio']:.2f} "
              f"(V{best_with['value_w']:.0%}/M{best_with['momentum_w']:.0%}/"
              f"Q{best_with['quality_w']:.0%}/G{best_with['growth_w']:.0%})")

    # 각 팩터별 가중치-샤프 관계
    print(f"\n팩터별 가중치-샤프 관계 (가중치별 평균 샤프):")
    for f, l in zip(factors, labels):
        weight_groups = {}
        for r in results:
            w = r[f]
            weight_groups.setdefault(w, []).append(r['sharpe_ratio'])

        print(f"\n  {l}:")
        row = "    "
        for w in sorted(weight_groups.keys()):
            avg_s = sum(weight_groups[w]) / len(weight_groups[w])
            row += f"{w:4.0%}→{avg_s:.2f}  "
        print(row)

    # Bottom 10 공통 특성
    bottom10 = results[-10:]
    print(f"\n하위 10개 조합 평균 가중치:")
    for f, l, cw in zip(factors, labels, current_weights):
        avg = sum(r[f] for r in bottom10) / len(bottom10)
        print(f"  {l:10s}: {avg:5.1%}")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description='팩터 가중치 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-04-09', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--step', type=float, default=0.05, help='가중치 스텝 (기본 5%%)')
    parser.add_argument('--output', type=str, default=None, help='CSV 저장 경로')
    parser.add_argument('--mode', type=str, default='default',
                        choices=['default', 'extended', 'fine'],
                        help='탐색 모드: default(5%%), extended(확장), fine(2.5%% 세밀)')
    parser.add_argument('--slippage', type=float, default=None, help='슬리피지 비율 (기본 0.001)')
    parser.add_argument('--regime', action='store_true', default=False,
                        help='레짐 필터 사용 (CRISIS/CAUTION 기반 매수 제한)')
    return parser.parse_args()


def main():
    args = parse_args()

    # 현행 실전 파라미터 기준
    bp_kw = dict(
        portfolio_size=args.portfolio,
        target_profit_rate=0.12,       # 현행 TP 12%
        stop_loss_rate=0.06,           # 현행 SL 6%
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        use_dynamic_targets=False,
        buy_min_score=65.0,            # 현행 매수 최소 점수
        regime_filter_enabled=args.regime,
    )
    if args.slippage is not None:
        bp_kw['slippage_rate'] = args.slippage
    base_params = BacktestParams(**bp_kw)
    print(f"  슬리피지: {base_params.slippage_rate:.4f} ({base_params.slippage_rate*100:.2f}%)")
    print(f"  레짐 필터: {'ON' if args.regime else 'OFF'}")

    if args.mode == 'fine':
        # 상위 영역 세밀 탐색 (step 2.5%)
        combos = generate_weight_combinations(
            step=0.025,
            v_range=(0.15, 0.40), m_range=(0.20, 0.50),
            q_range=(0.025, 0.30), g_range=(0.15, 0.30),
        )
        label = "세밀 탐색 (2.5% 스텝, 상위 영역)"
    elif args.mode == 'extended':
        # 확장 범위 (Quality 0%, Growth 30%, Momentum 55% 허용)
        combos = generate_weight_combinations(
            step=0.05,
            v_range=(0.00, 0.40), m_range=(0.10, 0.55),
            q_range=(0.00, 0.45), g_range=(0.05, 0.30),
        )
        label = "확장 범위 (5% 스텝)"
    else:
        combos = generate_weight_combinations(step=args.step)
        label = f"기본 ({args.step:.0%} 스텝)"

    print(f"모드: {label}")
    print(f"유효한 가중치 조합: {len(combos)}개")

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        combinations=combos,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
