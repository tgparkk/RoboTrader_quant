#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CRISIS 전량매도 멀티버스 백테스트
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""

KOSPI 예상체결지수(시가 갭 프록시) + S&P500 + VIX 조건별
"보유 전량 시가 매도" 효과를 검증합니다.

기존 regime_multiverse.py와 다른 점:
- 기존: CRISIS 시 "매수 차단"만
- 이번: CRISIS 시 "보유 전량 시가 매도" + 매수 차단

사용법:
    python scripts/crisis_sell_multiverse.py
"""
import sys
import time
import argparse
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


def run_crisis_sell_multiverse(start_date: str, end_date: str,
                               output_csv: str = None):
    """CRISIS 전량매도 멀티버스 실행"""

    base_params = BacktestParams(
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        buy_min_score=65.0,
        use_dynamic_targets=False,
    )

    # 탐색 범위
    # Stage 2: KOSPI 시가 갭 (예상체결지수 프록시)
    gap_thresholds = [-0.02, -0.03, -0.04, -0.05, -0.07]

    # Stage 1: S&P500 전일 등락률
    sp500_thresholds = [-0.03, -0.05, -0.07, -999.0]  # -999.0 = 비활성화 (절대 트리거 안 됨)

    # Stage 1: VIX 수준
    vix_thresholds = [30.0, 40.0, 50.0, 999.0]  # 999.0 = 비활성화 (VIX는 >= 비교라 999면 안 걸림)

    total_combos = len(gap_thresholds) * len(sp500_thresholds) * len(vix_thresholds)

    print(f"\n{'=' * 80}")
    print(f"CRISIS 전량매도 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"KOSPI 갭 임계: {gap_thresholds}")
    print(f"S&P500 임계: {[x for x in sp500_thresholds if x != -999.0]} (+ 비활성화)")
    print(f"VIX 임계: {[x for x in vix_thresholds if x != 999.0]} (+ 비활성화)")
    print(f"총 조합: {total_combos}개 + 기준선(매도 없음)")
    print(f"{'=' * 80}\n")

    # 1. 데이터 한 번만 로드
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    print("US 마켓 데이터(S&P500, VIX) 로딩 중...")
    loader._preload_us_market_data(trading_days[0], trading_days[-1])

    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    saved_us_market = loader.us_market_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목\n")

    def run_single(params: BacktestParams) -> dict:
        """단일 조합 시뮬레이션"""
        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors
        bt.us_market_cache = saved_us_market
        bt._crisis_sell_count = 0

        prev_total_value = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._today_regime = bt._determine_regime(date)
            bt._regime_stats[bt._today_regime] = bt._regime_stats.get(bt._today_regime, 0) + 1

            # CRISIS 전량매도 체크
            crisis_sold = False
            if params.crisis_sell_all and bt.positions:
                crisis_sold = bt._check_crisis_sell_all(date)

            # TP/SL을 리밸런싱보다 먼저 체크 (실전과 동일)
            bt._check_stop_profit_loss(date)
            if not crisis_sold:
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
        result = bt._create_result(start_norm, end_norm, len(trading_days))
        return {
            'result': result,
            'crisis_sell_count': bt._crisis_sell_count,
        }

    # 2. 기준선 (전량매도 없음)
    print("기준선 (CRISIS 전량매도 없음) 실행 중...")
    baseline_start = time.time()
    baseline_params = BacktestParams(
        initial_capital=base_params.initial_capital,
        portfolio_size=base_params.portfolio_size,
        target_profit_rate=base_params.target_profit_rate,
        stop_loss_rate=base_params.stop_loss_rate,
        hard_stop_score=base_params.hard_stop_score,
        soft_stop_score=base_params.soft_stop_score,
        soft_stop_rank=base_params.soft_stop_rank,
        safe_score=base_params.safe_score,
        safe_rank=base_params.safe_rank,
        buy_min_score=base_params.buy_min_score,
        use_dynamic_targets=base_params.use_dynamic_targets,
        trading_cost_rate=base_params.trading_cost_rate,
        crisis_sell_all=False,
    )
    baseline = run_single(baseline_params)
    br = baseline['result']
    baseline_elapsed = time.time() - baseline_start
    print(f"  기준선: 수익 {br.total_return:>8.0%}  샤프 {br.sharpe_ratio:>5.2f}  "
          f"MDD {br.max_drawdown:>5.1%}  거래 {br.total_trades}건 ({baseline_elapsed:.1f}s)\n")

    # 3. 멀티버스 실행
    results = []
    total_start = time.time()

    for i, (gap, sp, vix) in enumerate(
        product(gap_thresholds, sp500_thresholds, vix_thresholds), 1
    ):
        params = BacktestParams(
            initial_capital=base_params.initial_capital,
            portfolio_size=base_params.portfolio_size,
            target_profit_rate=base_params.target_profit_rate,
            stop_loss_rate=base_params.stop_loss_rate,
            hard_stop_score=base_params.hard_stop_score,
            soft_stop_score=base_params.soft_stop_score,
            soft_stop_rank=base_params.soft_stop_rank,
            safe_score=base_params.safe_score,
            safe_rank=base_params.safe_rank,
            buy_min_score=base_params.buy_min_score,
            use_dynamic_targets=base_params.use_dynamic_targets,
            trading_cost_rate=base_params.trading_cost_rate,
            # CRISIS 전량매도 파라미터
            crisis_sell_all=True,
            crisis_sell_gap_pct=gap,
            crisis_sell_sp500_pct=sp,
            crisis_sell_vix=vix,
        )

        out = run_single(params)
        r = out['result']
        crisis_count = out['crisis_sell_count']

        # 기준선 대비 변화
        sharpe_diff = r.sharpe_ratio - br.sharpe_ratio
        mdd_diff = r.max_drawdown - br.max_drawdown  # 음수면 MDD 개선
        return_diff = r.total_return - br.total_return

        sp_label = f"{sp:.0%}" if sp != -999.0 else "OFF"
        vix_label = f"{vix:.0f}" if vix != 999.0 else "OFF"

        results.append({
            'gap': gap, 'sp500': sp, 'vix': vix,
            'sp_label': sp_label, 'vix_label': vix_label,
            'total_return': r.total_return,
            'sharpe': r.sharpe_ratio,
            'mdd': r.max_drawdown,
            'trades': r.total_trades,
            'crisis_count': crisis_count,
            'sharpe_diff': sharpe_diff,
            'mdd_diff': mdd_diff,
            'return_diff': return_diff,
        })

        # 주요 조합만 출력
        marker = ""
        if sharpe_diff > 0 and mdd_diff < 0:
            marker = " ★ 개선"
        elif sharpe_diff > 0:
            marker = " ↑ 샤프↑"
        elif mdd_diff < -0.01:
            marker = " ↓ MDD↓"

        if i <= 10 or marker or i % 20 == 0:
            print(f"  [{i:>3}/{total_combos}] 갭{gap:>5.0%} S&P{sp_label:>4} VIX{vix_label:>4} "
                  f"→ 수익 {r.total_return:>8.0%} 샤프 {r.sharpe_ratio:>5.2f} "
                  f"MDD {r.max_drawdown:>5.1%} 거래 {r.total_trades:>3} "
                  f"위기매도 {crisis_count}회{marker}")

    total_elapsed = time.time() - total_start

    # 4. 결과 분석
    print(f"\n{'=' * 80}")
    print(f"결과 분석 (총 {total_elapsed:.1f}초)")
    print(f"{'=' * 80}\n")

    # 기준선 대비 개선된 조합
    improved = [r for r in results if r['sharpe_diff'] > 0 and r['mdd_diff'] < 0]
    sharpe_improved = [r for r in results if r['sharpe_diff'] > 0]
    mdd_improved = [r for r in results if r['mdd_diff'] < -0.005]

    print(f"기준선: 수익 {br.total_return:.0%}  샤프 {br.sharpe_ratio:.2f}  "
          f"MDD {br.max_drawdown:.1%}  거래 {br.total_trades}건\n")

    if improved:
        print(f"샤프↑ + MDD↓ 동시 개선: {len(improved)}개 조합")
        improved.sort(key=lambda x: x['sharpe'], reverse=True)
        for r in improved[:10]:
            print(f"  갭{r['gap']:>5.0%} S&P{r['sp_label']:>4} VIX{r['vix_label']:>4} "
                  f"→ 샤프 {r['sharpe']:.2f}({r['sharpe_diff']:+.2f}) "
                  f"MDD {r['mdd']:.1%}({r['mdd_diff']:+.1%}) "
                  f"거래 {r['trades']} 위기매도 {r['crisis_count']}회")
    else:
        print("샤프↑ + MDD↓ 동시 개선 조합 없음")

    print()
    if sharpe_improved:
        print(f"샤프만 개선: {len(sharpe_improved)}개 조합")
        sharpe_improved.sort(key=lambda x: x['sharpe'], reverse=True)
        for r in sharpe_improved[:5]:
            print(f"  갭{r['gap']:>5.0%} S&P{r['sp_label']:>4} VIX{r['vix_label']:>4} "
                  f"→ 샤프 {r['sharpe']:.2f}({r['sharpe_diff']:+.2f}) "
                  f"MDD {r['mdd']:.1%} 위기매도 {r['crisis_count']}회")

    print()
    if mdd_improved:
        print(f"MDD만 개선: {len(mdd_improved)}개 조합")
        mdd_improved.sort(key=lambda x: x['mdd'])
        for r in mdd_improved[:5]:
            print(f"  갭{r['gap']:>5.0%} S&P{r['sp_label']:>4} VIX{r['vix_label']:>4} "
                  f"→ MDD {r['mdd']:.1%}({r['mdd_diff']:+.1%}) "
                  f"샤프 {r['sharpe']:.2f} 위기매도 {r['crisis_count']}회")

    # 위기매도 발동 횟수 분포
    print(f"\n위기매도 발동 횟수 분포:")
    crisis_counts = {}
    for r in results:
        c = r['crisis_count']
        if c not in crisis_counts:
            crisis_counts[c] = 0
        crisis_counts[c] += 1
    for c in sorted(crisis_counts.keys()):
        print(f"  {c}회: {crisis_counts[c]}개 조합")

    # KOSPI 갭만 사용 (S&P/VIX OFF) — 가장 단순한 설정
    print(f"\n{'─' * 60}")
    print(f"KOSPI 갭만 사용 (S&P/VIX 비활성화) — 단순 설정:")
    gap_only = [r for r in results if r['sp500'] == -999.0 and r['vix'] == 999.0]
    for r in gap_only:
        marker = " ★" if r['sharpe_diff'] > 0 and r['mdd_diff'] < 0 else ""
        print(f"  갭 {r['gap']:>5.0%} → 샤프 {r['sharpe']:.2f}({r['sharpe_diff']:+.2f}) "
              f"MDD {r['mdd']:.1%}({r['mdd_diff']:+.1%}) "
              f"위기매도 {r['crisis_count']}회{marker}")

    # CSV 출력
    if output_csv:
        import csv
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'gap', 'sp500', 'vix', 'total_return', 'sharpe', 'mdd',
                'trades', 'crisis_count', 'sharpe_diff', 'mdd_diff', 'return_diff'
            ])
            writer.writeheader()
            for r in results:
                row = {k: v for k, v in r.items() if k in writer.fieldnames}
                writer.writerow(row)
        print(f"\n결과 저장: {output_csv}")

    # 최종 결론
    print(f"\n{'=' * 80}")
    if improved:
        best = improved[0]
        print(f"최적 조합: 갭 {best['gap']:.0%} / S&P {best['sp_label']} / VIX {best['vix_label']}")
        print(f"  샤프 {best['sharpe']:.2f} (기준 {br.sharpe_ratio:.2f}, {best['sharpe_diff']:+.2f})")
        print(f"  MDD {best['mdd']:.1%} (기준 {br.max_drawdown:.1%}, {best['mdd_diff']:+.1%})")
        print(f"  위기매도 {best['crisis_count']}회 / 거래 {best['trades']}건")
    else:
        print("결론: CRISIS 전량매도는 백테스트 기간에서 기준선 대비 개선 효과 없음")
        print("(블랙스완 보험으로서의 가치는 백테스트 밖에 있음)")
    print(f"{'=' * 80}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CRISIS 전량매도 멀티버스 백테스트')
    parser.add_argument('--start', default='2023-01-01', help='시작일')
    parser.add_argument('--end', default='2026-03-07', help='종료일')
    parser.add_argument('--output', default=None, help='CSV 출력 경로')
    args = parser.parse_args()

    run_crisis_sell_multiverse(args.start, args.end, args.output)
