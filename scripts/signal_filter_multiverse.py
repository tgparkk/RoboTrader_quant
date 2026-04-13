#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
신호 필터 멀티버스: blind_pattern_discovery에서 발견한 신호를 백테스트로 검증

발견된 핵심 신호 (미래 정보 없음, 전일까지 데이터만 사용):
  1. score_momentum  : 전일 대비 점수 변화량 (승리 +1.4 vs 패배 +0.5, d=0.37)
  2. ma60_dist       : 60일선 대비 괴리율 (승리 33% vs 패배 41%, d=-0.35)
  3. vol_20d         : 20일 변동성 (승리 4.5% vs 패배 5.3%, d=-0.32)
  4. rank_change     : 전일 대비 순위 변화 (승리 -7.4 vs 패배 -2.6, d=-0.45)
  5. ret_20d         : 20일 수익률 과열 필터 (승리 31% vs 패배 38%, d=-0.26)

사용법:
    python scripts/signal_filter_multiverse.py
    python scripts/signal_filter_multiverse.py --start 2023-01-01 --end 2026-03-31
"""
import sys
import time
import argparse
import numpy as np
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import TradeAction


class FilteredBacktester(Backtester):
    """신호 필터가 추가된 백테스터 서브클래스"""

    def __init__(self, params=None,
                 score_momentum_min=None,   # 점수 모멘텀 최소값
                 ma60_dist_max=None,        # MA60 괴리율 상한 (%)
                 vol_20d_max=None,          # 20일 변동성 상한 (%)
                 rank_change_min=None,      # 순위 변화 최소값 (음수 = 상승)
                 ret_20d_max=None,          # 20일 수익률 상한 (%)
                 ):
        super().__init__(params=params)
        self.filter_score_momentum_min = score_momentum_min
        self.filter_ma60_dist_max = ma60_dist_max
        self.filter_vol_20d_max = vol_20d_max
        self.filter_rank_change_min = rank_change_min
        self.filter_ret_20d_max = ret_20d_max

    def _execute_rebalancing(self, date):
        """리밸런싱에 신호 필터 추가"""
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}

        # === 매도 로직 (원본과 동일) ===
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
                sell_list.append((stock_code, f"[리밸런싱] 긴급 매도 (점수 {total_score:.1f} < {self.params.hard_stop_score})"))
                continue

            if self.params.hard_stop_score <= total_score < self.params.soft_stop_score:
                if factor_rank > self.params.soft_stop_rank:
                    sell_list.append((stock_code, f"[리밸런싱] 조건부 매도 (점수 {total_score:.1f}, {factor_rank}위)"))
                    continue

            if stock_code not in target_codes:
                if total_score >= self.params.safe_score:
                    continue
                elif factor_rank <= self.params.safe_rank:
                    continue
                else:
                    sell_list.append((stock_code, f"[리밸런싱] 포트폴리오 조정 ({factor_rank}위, {total_score:.1f}점)"))

        for stock_code, reason in sell_list:
            self._execute_sell(stock_code, date, reason)
            if self.params.rebalancing_sell_cooldown_days > 0:
                self._rebalancing_sold_dates[stock_code] = date

        # === 매수 로직 (신호 필터 추가) ===
        current_codes = set(self.positions.keys())
        buy_candidates = []
        kospi_change = self._get_kospi_change(date)
        calc_date = date.replace("-", "")

        # 전일 팩터 데이터 (score_momentum, rank_change 계산용)
        sorted_dates = sorted(self.factors_cache.keys())
        prev_calc = None
        for i, d in enumerate(sorted_dates):
            if d == calc_date and i > 0:
                prev_calc = sorted_dates[i - 1]
                break

        for item in target_portfolio:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue
            if stock_code in self._today_stop_profit_sold:
                continue
            # 쿨다운 필터
            if self.params.rebalancing_sell_cooldown_days > 0:
                sell_date = self._rebalancing_sold_dates.get(stock_code)
                if sell_date is not None:
                    days_since_sell = self._calc_holding_days(sell_date, date)
                    if days_since_sell <= self.params.rebalancing_sell_cooldown_days:
                        continue
            # 매수 최소 점수
            if self.params.buy_min_score > 0 and item['total_score'] < self.params.buy_min_score:
                continue
            # 5일 수익률 하드게이트
            if self.params.buy_ret5d_min is not None:
                price_hist = self.daily_prices_cache.get(stock_code)
                if price_hist is not None and date in price_hist.index:
                    idx = price_hist.index.get_loc(date)
                    if idx >= 5:
                        close_now = float(price_hist.iloc[idx]['close'])
                        close_5d = float(price_hist.iloc[idx - 5]['close'])
                        if close_5d > 0:
                            ret_5d = (close_now / close_5d - 1) * 100
                            if ret_5d < self.params.buy_ret5d_min:
                                continue

            # ═══ 신규 신호 필터 (전일 데이터만 사용) ═══

            # 1. score_momentum: 전일 대비 점수 변화
            if self.filter_score_momentum_min is not None and prev_calc:
                curr_factors = self.factors_cache.get(calc_date, {}).get(stock_code, {})
                prev_factors = self.factors_cache.get(prev_calc, {}).get(stock_code, {})
                if curr_factors and prev_factors:
                    curr_score = curr_factors.get('total_score', 0)
                    prev_score = prev_factors.get('total_score', 0)
                    score_mom = curr_score - prev_score
                    if score_mom < self.filter_score_momentum_min:
                        continue

            # 2. rank_change: 전일 대비 순위 변화 (음수 = 상승)
            if self.filter_rank_change_min is not None and prev_calc:
                curr_factors = self.factors_cache.get(calc_date, {}).get(stock_code, {})
                prev_factors = self.factors_cache.get(prev_calc, {}).get(stock_code, {})
                if curr_factors and prev_factors:
                    curr_rank = curr_factors.get('factor_rank', 999)
                    prev_rank = prev_factors.get('factor_rank', 999)
                    rank_chg = curr_rank - prev_rank
                    if rank_chg > self.filter_rank_change_min:  # 양수면 순위 하락
                        continue

            # 가격 기반 필터는 전일 종가 사용
            price_hist = self.daily_prices_cache.get(stock_code)
            if price_hist is not None and date in price_hist.index:
                idx = price_hist.index.get_loc(date)

                # 3. ma60_dist: 60일선 대비 괴리율
                if self.filter_ma60_dist_max is not None and idx > 60:
                    prev_close = float(price_hist.iloc[idx - 1]['close'])
                    ma60 = float(price_hist.iloc[idx - 61:idx - 1]['close'].mean())
                    if ma60 > 0:
                        dist = (prev_close / ma60 - 1) * 100
                        if dist > self.filter_ma60_dist_max:
                            continue

                # 4. vol_20d: 20일 변동성
                if self.filter_vol_20d_max is not None and idx > 20:
                    closes = price_hist.iloc[idx - 20:idx]['close'].values.astype(float)
                    daily_rets = np.diff(closes) / closes[:-1]
                    vol = np.std(daily_rets) * 100
                    if vol > self.filter_vol_20d_max:
                        continue

                # 5. ret_20d: 20일 수익률 과열 필터
                if self.filter_ret_20d_max is not None and idx > 20:
                    prev_close = float(price_hist.iloc[idx - 1]['close'])
                    close_20d = float(price_hist.iloc[idx - 21]['close'])
                    if close_20d > 0:
                        ret_20d = (prev_close / close_20d - 1) * 100
                        if ret_20d > self.filter_ret_20d_max:
                            continue

            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue
            buy_candidates.append(item)

        # === 매수 실행 (원본과 동일) ===
        if buy_candidates:
            available_slots = self.params.portfolio_size - len(self.positions)
            if self._today_regime == 'CRISIS':
                available_slots = 0
            elif self._today_regime == 'CAUTION':
                caution_limit = max(0, self.params.caution_max_buy - len(self.positions))
                available_slots = min(available_slots, caution_limit)
            if available_slots <= 0:
                return
            buy_candidates = buy_candidates[:available_slots]
            per_stock_capital = self.capital / len(buy_candidates) if buy_candidates else 0

            for item in buy_candidates:
                stock_code = item['stock_code']
                price_data = self._get_daily_price(stock_code, date)
                if not price_data:
                    continue
                buy_price = price_data['open']
                if buy_price <= 0:
                    continue
                quantity = int(per_stock_capital / buy_price)
                if quantity <= 0:
                    continue
                factors = self._get_factors(date, stock_code)
                momentum_score = factors.get('momentum_score', 50) if factors else 50
                if self.params.use_dynamic_targets:
                    target_profit, stop_loss = self._calculate_dynamic_targets(
                        item['rank'], item['total_score'], momentum_score)
                else:
                    target_profit = self.params.target_profit_rate
                    stop_loss = self.params.stop_loss_rate
                self._execute_buy(
                    stock_code=stock_code, stock_name=item.get('stock_name', stock_code),
                    date=date, buy_price=buy_price, quantity=quantity,
                    target_profit_rate=target_profit, stop_loss_rate=stop_loss,
                    total_score=item['total_score'], factor_rank=item['rank'])
                self._today_rebalancing_bought.add(stock_code)


def run_multiverse(start_date, end_date, slippage=None):
    """다차원 멀티버스 실행"""

    bp_kw = dict(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        min_hold_days=0,
        use_dynamic_targets=True,
        rebalancing_sell_cooldown_days=3,
    )
    if slippage is not None:
        bp_kw['slippage_rate'] = slippage
    base_params = BacktestParams(**bp_kw)
    print(f"  슬리피지: {base_params.slippage_rate:.4f} ({base_params.slippage_rate*100:.2f}%)")

    # 데이터 1회 로드
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

    # ═══════════════════════════════════════════════════════
    # 탐색 축 정의
    # ═══════════════════════════════════════════════════════

    # Phase A: 개별 필터 효과 (각각 단독)
    individual_tests = {
        'score_momentum_min': [None, -1.0, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0],
        'ma60_dist_max':      [None, 20, 30, 40, 50, 60, 80],
        'vol_20d_max':        [None, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        'rank_change_min':    [None, -15, -10, -8, -5, -3, 0],
        'ret_20d_max':        [None, 20, 30, 40, 50, 60, 80],
    }

    # Phase B: 상위 조합 (Phase A 결과 기반으로 좁히기)
    # Phase A 완료 후 동적으로 결정

    all_results = []

    # ═══════════════════════════════════════════════════════
    # Phase A: 개별 필터
    # ═══════════════════════════════════════════════════════
    print("=" * 100)
    print("Phase A: 개별 필터 효과 측정")
    print("=" * 100)

    for filter_name, values in individual_tests.items():
        print(f"\n--- {filter_name} ---")
        print(f"  {'값':>8} | {'샤프':>7} | {'수익률':>10} | {'MDD':>7} | {'승률':>6} | {'거래수':>5} | {'PF':>5}")
        print(f"  {'-' * 8}-+-{'-' * 7}-+-{'-' * 10}-+-{'-' * 7}-+-{'-' * 6}-+-{'-' * 5}-+-{'-' * 5}")

        for val in values:
            kwargs = {filter_name: val}
            bt = FilteredBacktester(params=base_params, **kwargs)
            bt.daily_prices_cache = saved_prices
            bt.portfolio_cache = saved_portfolio
            bt.factors_cache = saved_factors
            bt._reset_state()
            bt.capital = base_params.initial_capital

            # 조용히 실행
            import logging
            logging.disable(logging.CRITICAL)
            try:
                result = bt.backtest(start_norm, end_norm)
            finally:
                logging.disable(logging.NOTSET)

            val_str = f"{val}" if val is not None else "OFF"
            print(f"  {val_str:>8} | {result.sharpe_ratio:>7.2f} | {result.total_return:>9.1%} | "
                  f"{result.max_drawdown:>6.1%} | {result.win_rate:>5.1%} | {result.total_trades:>5} | "
                  f"{result.profit_factor:>5.2f}")

            all_results.append({
                'filter': filter_name, 'value': val,
                'sharpe': result.sharpe_ratio, 'return': result.total_return,
                'mdd': result.max_drawdown, 'win_rate': result.win_rate,
                'trades': result.total_trades, 'pf': result.profit_factor,
                'combo': f"{filter_name}={val}",
            })

    # ═══════════════════════════════════════════════════════
    # Phase B: 상위 조합 (개별 최적값 기반)
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("Phase B: 유망 조합 탐색")
    print("=" * 100)

    # 각 필터별 최적값 찾기 (baseline=None 대비 샤프 개선)
    baseline_sharpe = None
    best_per_filter = {}
    for r in all_results:
        if r['value'] is None:
            if baseline_sharpe is None:
                baseline_sharpe = r['sharpe']
            continue
        fname = r['filter']
        if fname not in best_per_filter or r['sharpe'] > best_per_filter[fname]['sharpe']:
            best_per_filter[fname] = r

    print(f"\n  베이스라인 샤프: {baseline_sharpe:.2f}")
    print(f"\n  개별 필터 최적값:")
    for fname, r in best_per_filter.items():
        diff = r['sharpe'] - baseline_sharpe
        arrow = "+" if diff > 0 else ""
        print(f"    {fname:>22} = {str(r['value']):>5} -> 샤프 {r['sharpe']:.2f} ({arrow}{diff:.2f})")

    # 개선된 필터만 조합 테스트
    improved = {k: v for k, v in best_per_filter.items() if v['sharpe'] > baseline_sharpe}

    if len(improved) < 2:
        print("\n  개선된 필터가 2개 미만 -> 조합 탐색 건너뜀")
    else:
        # 2-필터 조합
        filter_names = list(improved.keys())
        print(f"\n  2-필터 조합 ({len(filter_names)}C2 = {len(filter_names) * (len(filter_names) - 1) // 2}개)")
        print(f"  {'조합':>50} | {'샤프':>7} | {'수익률':>10} | {'MDD':>7} | {'승률':>6} | {'거래수':>5}")
        print(f"  {'-' * 50}-+-{'-' * 7}-+-{'-' * 10}-+-{'-' * 7}-+-{'-' * 6}-+-{'-' * 5}")

        combo_results = []
        for i, f1 in enumerate(filter_names):
            for f2 in filter_names[i + 1:]:
                kwargs = {f1: improved[f1]['value'], f2: improved[f2]['value']}
                bt = FilteredBacktester(params=base_params, **kwargs)
                bt.daily_prices_cache = saved_prices
                bt.portfolio_cache = saved_portfolio
                bt.factors_cache = saved_factors
                bt._reset_state()
                bt.capital = base_params.initial_capital

                import logging
                logging.disable(logging.CRITICAL)
                try:
                    result = bt.backtest(start_norm, end_norm)
                finally:
                    logging.disable(logging.NOTSET)

                combo_label = f"{f1}={improved[f1]['value']} + {f2}={improved[f2]['value']}"
                print(f"  {combo_label:>50} | {result.sharpe_ratio:>7.2f} | {result.total_return:>9.1%} | "
                      f"{result.max_drawdown:>6.1%} | {result.win_rate:>5.1%} | {result.total_trades:>5}")
                combo_results.append({
                    'combo': combo_label, 'sharpe': result.sharpe_ratio,
                    'return': result.total_return, 'mdd': result.max_drawdown,
                    'win_rate': result.win_rate, 'trades': result.total_trades,
                    'pf': result.profit_factor,
                })

        # 3-필터 이상 조합 (개선 필터가 3개 이상이면)
        if len(filter_names) >= 3:
            print(f"\n  3-필터 조합")
            print(f"  {'조합':>70} | {'샤프':>7} | {'수익률':>10} | {'MDD':>7} | {'승률':>6}")
            print(f"  {'-' * 70}-+-{'-' * 7}-+-{'-' * 10}-+-{'-' * 7}-+-{'-' * 6}")

            from itertools import combinations
            for combo_filters in combinations(filter_names, 3):
                kwargs = {f: improved[f]['value'] for f in combo_filters}
                bt = FilteredBacktester(params=base_params, **kwargs)
                bt.daily_prices_cache = saved_prices
                bt.portfolio_cache = saved_portfolio
                bt.factors_cache = saved_factors
                bt._reset_state()
                bt.capital = base_params.initial_capital

                import logging
                logging.disable(logging.CRITICAL)
                try:
                    result = bt.backtest(start_norm, end_norm)
                finally:
                    logging.disable(logging.NOTSET)

                combo_label = " + ".join(f"{f}={improved[f]['value']}" for f in combo_filters)
                print(f"  {combo_label:>70} | {result.sharpe_ratio:>7.2f} | {result.total_return:>9.1%} | "
                      f"{result.max_drawdown:>6.1%} | {result.win_rate:>5.1%}")
                combo_results.append({
                    'combo': combo_label, 'sharpe': result.sharpe_ratio,
                    'return': result.total_return, 'mdd': result.max_drawdown,
                    'win_rate': result.win_rate, 'trades': result.total_trades,
                    'pf': result.profit_factor,
                })

        # 전체 필터 조합
        if len(filter_names) >= 4:
            print(f"\n  전체 {len(filter_names)}-필터 조합")
            kwargs = {f: improved[f]['value'] for f in filter_names}
            bt = FilteredBacktester(params=base_params, **kwargs)
            bt.daily_prices_cache = saved_prices
            bt.portfolio_cache = saved_portfolio
            bt.factors_cache = saved_factors
            bt._reset_state()
            bt.capital = base_params.initial_capital

            import logging
            logging.disable(logging.CRITICAL)
            try:
                result = bt.backtest(start_norm, end_norm)
            finally:
                logging.disable(logging.NOTSET)

            combo_label = " + ".join(f"{f}={improved[f]['value']}" for f in filter_names)
            print(f"  {combo_label}")
            print(f"  -> 샤프 {result.sharpe_ratio:.2f} | 수익률 {result.total_return:.1%} | "
                  f"MDD {result.max_drawdown:.1%} | 승률 {result.win_rate:.1%} | {result.total_trades}건")
            combo_results.append({
                'combo': combo_label, 'sharpe': result.sharpe_ratio,
                'return': result.total_return, 'mdd': result.max_drawdown,
                'win_rate': result.win_rate, 'trades': result.total_trades,
                'pf': result.profit_factor,
            })

    # ═══════════════════════════════════════════════════════
    # Phase C: 최종 순위
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("Phase C: 최종 순위 (샤프 기준)")
    print("=" * 100)

    # 전체 결과 합치기
    all_ranked = []
    for r in all_results:
        all_ranked.append(r)
    if 'combo_results' in dir() and combo_results:
        for r in combo_results:
            all_ranked.append({**r, 'filter': 'combo', 'value': '-'})

    all_ranked.sort(key=lambda x: x['sharpe'], reverse=True)

    print(f"\n  {'순위':>4} | {'조합':>55} | {'샤프':>7} | {'수익률':>10} | {'MDD':>7} | {'승률':>6} | {'거래수':>5} | {'PF':>5}")
    print(f"  {'-' * 4}-+-{'-' * 55}-+-{'-' * 7}-+-{'-' * 10}-+-{'-' * 7}-+-{'-' * 6}-+-{'-' * 5}-+-{'-' * 5}")

    for i, r in enumerate(all_ranked[:25], 1):
        label = r.get('combo', f"{r['filter']}={r['value']}")
        is_baseline = r.get('value') is None
        marker = " <-- 현재" if is_baseline else ""
        print(f"  {i:>4} | {label:>55} | {r['sharpe']:>7.2f} | {r['return']:>9.1%} | "
              f"{r['mdd']:>6.1%} | {r['win_rate']:>5.1%} | {r['trades']:>5} | {r['pf']:>5.2f}{marker}")

    # 베이스라인 위치
    baseline_rank = next((i for i, r in enumerate(all_ranked, 1) if r.get('value') is None), None)
    if baseline_rank:
        print(f"\n  현재 설정(필터 없음) 순위: {baseline_rank}위 / {len(all_ranked)}개")

    best = all_ranked[0]
    print(f"\n  최고 조합: {best.get('combo', '')} -> 샤프 {best['sharpe']:.2f}")
    if baseline_sharpe:
        print(f"  베이스라인 대비: 샤프 {baseline_sharpe:.2f} -> {best['sharpe']:.2f} ({best['sharpe'] - baseline_sharpe:+.2f})")


def main():
    parser = argparse.ArgumentParser(description='신호 필터 멀티버스')
    parser.add_argument('--start', type=str, default='2023-01-01')
    parser.add_argument('--end', type=str, default='2026-03-31')
    parser.add_argument('--slippage', type=float, default=None, help='슬리피지 비율 (기본 0.001)')
    args = parser.parse_args()

    print(f"{'#' * 100}")
    print(f"  신호 필터 멀티버스: blind_pattern_discovery 발견 검증")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"{'#' * 100}")

    total_start = time.time()
    run_multiverse(args.start, args.end, slippage=args.slippage)
    elapsed = time.time() - total_start
    print(f"\n  총 소요 시간: {elapsed:.0f}초")


if __name__ == '__main__':
    main()
