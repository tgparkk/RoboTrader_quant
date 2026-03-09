#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
시장 하락 시 매수 중단 멀티버스 백테스트

코스피 변동률 기준으로 매수를 중단하는 전략의 효과를 검증합니다.
- 리밸런싱 매도는 항상 실행 (하락장에서도 기준 미달 종목 정리)
- 매수만 조건부 중단 (시장이 안 좋으면 현금 보유)

사용법:
    python scripts/market_halt_multiverse.py
    python scripts/market_halt_multiverse.py --start 2023-01-01 --end 2026-02-28
    python scripts/market_halt_multiverse.py --output results/market_halt.csv
"""
import sys
import time
import argparse
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot


class MarketFilterBacktester(Backtester):
    """시장 하락 시 매수 중단 기능이 추가된 백테스터"""

    def __init__(self, params: BacktestParams = None,
                 market_halt_threshold: float = None):
        """
        Args:
            params: 백테스트 파라미터
            market_halt_threshold: 매수 중단 기준 (예: -0.02 = 코스피 -2% 이하 시 매수 중단)
                                   None이면 필터 없음 (항상 매수)
        """
        super().__init__(params=params)
        self.market_halt_threshold = market_halt_threshold
        self.halt_count = 0  # 매수 중단된 날 수
        self.total_rebalancing_days = 0  # 리밸런싱 시도 날 수
        self.daily_position_counts = []  # 일별 포지션 수 추적

    def _reset_state(self):
        super()._reset_state()
        self.halt_count = 0
        self.total_rebalancing_days = 0
        self.daily_position_counts = []

    def _execute_rebalancing(self, date: str):
        """시장 필터 적용된 리밸런싱"""
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        self.total_rebalancing_days += 1

        # 시장 상태 확인
        kospi_change = self._get_kospi_change(date)

        if (self.market_halt_threshold is not None
                and kospi_change is not None
                and kospi_change < self.market_halt_threshold):
            # 매수 중단: 매도만 실행
            self.halt_count += 1
            self._execute_rebalancing_sells_only(date, portfolio)
            return

        # 정상 리밸런싱 (매도 + 매수)
        super()._execute_rebalancing(date)

    def _execute_rebalancing_sells_only(self, date: str, portfolio: list):
        """리밸런싱 매도만 실행 (매수 스킵)"""
        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}

        sell_list = []
        for stock_code, position in list(self.positions.items()):
            if self.params.min_hold_days > 0:
                days_held = self._calc_holding_days(position.buy_date, date)
                if days_held < self.params.min_hold_days:
                    continue

            factors = self._get_factors(date, stock_code)
            if not factors:
                if stock_code not in target_codes:
                    sell_list.append((stock_code, "[리밸런싱] 팩터 데이터 없음"))
                continue

            total_score = factors.get('total_score', 0)
            factor_rank = factors.get('factor_rank', 999)

            if total_score < self.params.hard_stop_score:
                sell_list.append((stock_code,
                    f"[리밸런싱] 긴급 매도 (점수 {total_score:.1f} < {self.params.hard_stop_score})"))
                continue

            if self.params.hard_stop_score <= total_score < self.params.soft_stop_score:
                if factor_rank > self.params.soft_stop_rank:
                    sell_list.append((stock_code,
                        f"[리밸런싱] 조건부 매도 (점수 {total_score:.1f}, {factor_rank}위)"))
                    continue

            if stock_code not in target_codes:
                if total_score >= self.params.safe_score:
                    continue
                elif factor_rank <= self.params.safe_rank:
                    continue
                else:
                    sell_list.append((stock_code,
                        f"[리밸런싱] 포트폴리오 조정 ({factor_rank}위, {total_score:.1f}점)"))

        for stock_code, reason in sell_list:
            self._execute_sell(stock_code, date, reason)


def run_multiverse(start_date: str, end_date: str,
                   thresholds: list,
                   base_params: BacktestParams = None,
                   output_csv: str = None):
    """
    시장 하락 매수 중단 멀티버스 실행 (데이터 1회 로드)

    Args:
        thresholds: 매수 중단 기준 리스트 (None = 필터 없음)
                    예: [None, -0.03, -0.02, -0.01, 0.0, 0.005]
    """
    if base_params is None:
        base_params = BacktestParams()

    total_combos = len(thresholds)
    print(f"\n{'=' * 80}")
    print(f"시장 하락 매수 중단 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"TP/SL: {base_params.target_profit_rate:.0%}/{base_params.stop_loss_rate:.0%} (고정)")
    print(f"포트폴리오: {base_params.portfolio_size}종목")
    print(f"테스트 조합: {total_combos}개")
    print()
    print(f"매수 중단 기준값:")
    for t in thresholds:
        if t is None:
            print(f"  - 없음 (항상 매수) ◀ 현행")
        else:
            print(f"  - 코스피 < {t:+.1%} 시 매수 중단")
    print(f"{'=' * 80}\n")

    # 1. 데이터 한 번만 로드
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    print(f"데이터 로드 완료: {len(trading_days)}거래일, {len(saved_prices)}종목\n")

    # KOSPI 데이터 존재 확인
    if 'KS11' not in saved_prices:
        print("⚠️ KOSPI(KS11) 데이터 없음! 시장 필터 테스트 불가.")
        return []

    # 2. 멀티버스 실행
    results = []
    total_start = time.time()

    for i, threshold in enumerate(thresholds, 1):
        combo_start = time.time()

        bt = MarketFilterBacktester(
            params=base_params,
            market_halt_threshold=threshold,
        )
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

        # 시뮬레이션 루프
        prev_total_value = base_params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._execute_rebalancing(date)
            bt._check_stop_profit_loss(date)

            total_value = bt._calculate_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cumulative_return = (total_value - base_params.initial_capital) / base_params.initial_capital

            snapshot = DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total_value - bt.capital,
                total_value=total_value, position_count=len(bt.positions),
                daily_return=daily_return, cumulative_return=cumulative_return
            )
            bt.daily_snapshots.append(snapshot)
            bt.daily_position_counts.append(len(bt.positions))
            prev_total_value = total_value

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))

        combo_elapsed = time.time() - combo_start

        # 평균 포지션 수
        avg_positions = (sum(bt.daily_position_counts) / len(bt.daily_position_counts)
                         if bt.daily_position_counts else 0)
        halt_pct = (bt.halt_count / bt.total_rebalancing_days * 100
                    if bt.total_rebalancing_days > 0 else 0)

        results.append({
            'threshold': threshold,
            'threshold_label': '없음(현행)' if threshold is None else f'{threshold:+.1%}',
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
            'trading_cost': result.total_trading_cost,
            'halt_days': bt.halt_count,
            'rebalancing_days': bt.total_rebalancing_days,
            'halt_pct': halt_pct,
            'avg_positions': avg_positions,
        })

        marker = " ◀ 현행" if threshold is None else ""
        label = '없음' if threshold is None else f'{threshold:+.1%}'
        print(f"  [{i:2d}/{total_combos}] 기준 {label:>6s} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"중단 {bt.halt_count:>3d}일({halt_pct:4.1f}%)  "
              f"평균포지션 {avg_positions:>4.1f}  "
              f"({combo_elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 3. 결과 출력
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    print(f"\n{'=' * 95}")
    print(f"멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 95}")
    print(f"{'순위':>4} {'기준':>8} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} "
          f"{'거래':>5} {'중단일':>6} {'평균포지션':>8}")
    print(f"{'-' * 95}")

    baseline = next((r for r in results if r['threshold'] is None), None)

    for rank, r in enumerate(results, 1):
        is_current = r['threshold'] is None
        marker = " ◀ 현행" if is_current else ""

        # 베이스라인 대비 변화
        if baseline and not is_current:
            sharpe_diff = r['sharpe_ratio'] - baseline['sharpe_ratio']
            return_diff = r['total_return'] - baseline['total_return']
            diff_str = f"  (샤프 {sharpe_diff:+.2f}, 수익 {return_diff:+.0%})"
        else:
            diff_str = ""

        print(f"{rank:4d}. {r['threshold_label']:>8s} "
              f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} "
              f"{r['total_trades']:>5d} {r['halt_days']:>4d}일 "
              f"{r['avg_positions']:>6.1f}개{marker}{diff_str}")

    print(f"{'-' * 95}")
    print(f"총 {total_combos}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    print(f"{'=' * 95}")

    # 해석 출력
    print_interpretation(results, baseline)

    # CSV 저장
    if output_csv:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def print_interpretation(results, baseline):
    """결과 해석 출력"""
    if not baseline:
        return

    print(f"\n{'=' * 80}")
    print(f"결과 해석")
    print(f"{'=' * 80}")

    best = results[0]
    print(f"\n  최고 샤프: {best['threshold_label']} "
          f"(샤프 {best['sharpe_ratio']:.2f}, 수익 {best['total_return']:.0%})")
    print(f"  현행(필터없음): 샤프 {baseline['sharpe_ratio']:.2f}, 수익 {baseline['total_return']:.0%}")

    if best['threshold'] is None:
        print(f"\n  → 시장 필터 없이 항상 매수하는 것이 최적")
        print(f"    (하락장에서도 퀀트 상위 종목 매수가 유리)")
    else:
        diff_sharpe = best['sharpe_ratio'] - baseline['sharpe_ratio']
        diff_mdd = best['max_drawdown'] - baseline['max_drawdown']
        print(f"\n  → 코스피 {best['threshold']:+.1%} 이하 시 매수 중단이 최적")
        print(f"    샤프 {diff_sharpe:+.2f}, MDD {diff_mdd:+.1%}")
        print(f"    매수 중단 빈도: {best['halt_days']}일/{best['rebalancing_days']}일 "
              f"({best['halt_pct']:.1f}%)")

    # MDD 최소 조합
    min_mdd = min(results, key=lambda x: abs(x['max_drawdown']))
    if min_mdd['threshold'] != best['threshold']:
        print(f"\n  MDD 최소: {min_mdd['threshold_label']} "
              f"(MDD {min_mdd['max_drawdown']:.1%}, 샤프 {min_mdd['sharpe_ratio']:.2f})")

    print(f"{'=' * 80}")


def parse_args():
    parser = argparse.ArgumentParser(description='시장 하락 매수 중단 멀티버스 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-02-28', help='종료일')
    parser.add_argument('--portfolio', type=int, default=10, help='포트폴리오 종목 수')
    parser.add_argument('--output', type=str, default=None, help='CSV 저장 경로')
    return parser.parse_args()


def main():
    args = parse_args()

    # 매수 중단 기준 탐색 범위
    thresholds = [
        None,       # 현행: 필터 없음 (항상 매수)
        -0.030,     # 코스피 -3% 이하 시 매수 중단
        -0.025,     # 코스피 -2.5% 이하 시 매수 중단
        -0.020,     # 코스피 -2% 이하 시 매수 중단
        -0.015,     # 코스피 -1.5% 이하 시 매수 중단
        -0.010,     # 코스피 -1% 이하 시 매수 중단
        -0.005,     # 코스피 -0.5% 이하 시 매수 중단
        0.000,      # 코스피 하락 시 매수 중단 (양수일 때만 매수)
        0.005,      # 코스피 +0.5% 이상일 때만 매수
        0.010,      # 코스피 +1% 이상일 때만 매수
    ]

    base_params = BacktestParams(
        portfolio_size=args.portfolio,
        target_profit_rate=0.15,
        stop_loss_rate=0.08,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        use_dynamic_targets=False,
    )

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        thresholds=thresholds,
        base_params=base_params,
        output_csv=args.output,
    )


if __name__ == '__main__':
    main()
