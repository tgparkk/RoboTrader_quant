#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
자금 배분 방식 멀티버스 (V100 + TP12/SL6 + 10종목 고정, 배분 방식만 변경)

테스트 방식:
  1. Equal (1/N 균등, 현행)
  2. Score proportional (V100 점수 비례)
  3. Rank-inverse (랭크 역비례: 1위 더 많이)
  4. Inverse volatility (저변동성 우대)
  5. Score × Inverse Vol (결합)
  6. Top-heavy (상위 3종목 50%, 나머지 50%)

거래수는 모두 동일할 것 (종목 선정은 V100 동일, 비중만 다름).
성과 차이는 "어느 비중이 나은가"를 측정.
"""
import sys
import time
import logging
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot, TradeRecord, TradeAction, Position


PERIODS = [
    ("2024-04~2025-06 (15개월)", "2024-04-01", "2025-06-30"),
    ("2025-07~2026-04 (9개월)",  "2025-07-01", "2026-04-09"),
    ("전체 2년",                 "2024-04-01", "2026-04-09"),
]


def common_params(**ov):
    base = dict(
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
        min_hold_days=0,
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )
    base.update(ov)
    return BacktestParams(**base)


# ═══════════════════════════════════════════════════════════════
# 커스텀 백테스터 — 배분 방식 지원
# ═══════════════════════════════════════════════════════════════
class PositionSizedBacktester(Backtester):
    """_execute_rebalancing를 오버라이드해 배분 방식 지원"""

    def __init__(self, params=None, allocation='equal'):
        super().__init__(params=params)
        self.allocation_method = allocation

    def _get_volatility(self, stock_code, date):
        """특정 날짜의 20일 변동성 조회 (daily_prices에서)"""
        df = self.daily_prices_cache.get(stock_code)
        if df is None or date not in df.index:
            return None
        # volatility_20d 컬럼은 없으므로 직접 계산
        dates = df.index.tolist()
        try:
            idx = dates.index(date)
            if idx < 20:
                return None
            closes = df.iloc[idx - 20:idx]['close'].values.astype(float)
            if len(closes) < 2 or np.any(closes <= 0):
                return None
            daily_rets = np.diff(closes) / closes[:-1]
            if daily_rets.std() == 0:
                return None
            return float(np.std(daily_rets) * np.sqrt(252))
        except (ValueError, KeyError):
            return None

    def _compute_weights(self, buy_candidates, date):
        """배분 방식별 가중치 (합=1.0)"""
        n = len(buy_candidates)
        if n == 0:
            return {}

        method = self.allocation_method
        weights = {}

        if method == 'equal':
            w = 1.0 / n
            for item in buy_candidates:
                weights[item['stock_code']] = w

        elif method == 'score_prop':
            total_score = sum(item['total_score'] for item in buy_candidates)
            if total_score <= 0:
                return self._compute_weights_equal(buy_candidates)
            for item in buy_candidates:
                weights[item['stock_code']] = item['total_score'] / total_score

        elif method == 'rank_inv':
            # 랭크가 낮을수록(1위에 가까울수록) 비중 커짐
            # weight_i = (N+1 - rank_within_candidates)
            sorted_items = sorted(buy_candidates, key=lambda x: x['rank'])
            weight_sum = 0
            for i, item in enumerate(sorted_items):
                w = n - i  # N, N-1, N-2, ... 1
                weights[item['stock_code']] = w
                weight_sum += w
            for code in weights:
                weights[code] /= weight_sum

        elif method == 'inv_vol':
            inv_vols = {}
            total = 0
            for item in buy_candidates:
                vol = self._get_volatility(item['stock_code'], date)
                if vol is None or vol <= 0:
                    vol = 0.30  # 기본 30%
                iv = 1.0 / vol
                inv_vols[item['stock_code']] = iv
                total += iv
            if total <= 0:
                return self._compute_weights_equal(buy_candidates)
            for code, iv in inv_vols.items():
                weights[code] = iv / total

        elif method == 'score_inv_vol':
            # 점수 × 역변동성
            combined = {}
            total = 0
            for item in buy_candidates:
                vol = self._get_volatility(item['stock_code'], date)
                if vol is None or vol <= 0:
                    vol = 0.30
                c = item['total_score'] / vol
                combined[item['stock_code']] = c
                total += c
            if total <= 0:
                return self._compute_weights_equal(buy_candidates)
            for code, c in combined.items():
                weights[code] = c / total

        elif method == 'top_heavy':
            # 상위 3종목 50%, 나머지 N-3종목 50%
            sorted_items = sorted(buy_candidates, key=lambda x: x['rank'])
            top_n = min(3, len(sorted_items))
            rest = len(sorted_items) - top_n
            top_w = 0.50 / top_n if top_n > 0 else 0
            rest_w = 0.50 / rest if rest > 0 else 0
            for i, item in enumerate(sorted_items):
                if i < top_n:
                    weights[item['stock_code']] = top_w
                else:
                    weights[item['stock_code']] = rest_w

        else:
            return self._compute_weights_equal(buy_candidates)

        return weights

    def _compute_weights_equal(self, buy_candidates):
        n = len(buy_candidates)
        if n == 0:
            return {}
        w = 1.0 / n
        return {item['stock_code']: w for item in buy_candidates}

    def _execute_rebalancing(self, date: str):
        """원본 로직 복사 + 매수 부분에서 배분 방식 적용"""
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}
        buy_candidate_pool = target_portfolio

        # 매도 로직 (원본과 동일)
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
                sell_list.append((stock_code, f"[리밸런싱] 긴급 매도"))
                continue

            if self.params.hard_stop_score <= total_score < self.params.soft_stop_score:
                if factor_rank > self.params.soft_stop_rank:
                    sell_list.append((stock_code, f"[리밸런싱] 조건부 매도"))
                    continue

            if stock_code not in target_codes:
                if total_score >= self.params.safe_score:
                    continue
                elif factor_rank <= self.params.safe_rank:
                    continue
                else:
                    sell_list.append((stock_code, f"[리밸런싱] 포트폴리오 조정"))

        for stock_code, reason in sell_list:
            self._execute_sell(stock_code, date, reason)
            if self.params.rebalancing_sell_cooldown_days > 0:
                self._rebalancing_sold_dates[stock_code] = date

        # 매수 후보 선정
        current_codes = set(self.positions.keys())
        buy_candidates = []
        kospi_change = self._get_kospi_change(date)

        for item in buy_candidate_pool:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue
            if stock_code in self._today_stop_profit_sold:
                continue
            if self.params.rebalancing_sell_cooldown_days > 0:
                sell_date = self._rebalancing_sold_dates.get(stock_code)
                if sell_date is not None:
                    days_since_sell = self._calc_holding_days(sell_date, date)
                    if days_since_sell <= self.params.rebalancing_sell_cooldown_days:
                        continue
            if self.params.buy_min_score > 0 and item['total_score'] < self.params.buy_min_score:
                continue
            if self.params.buy_ret5d_min is not None:
                price_hist = self.daily_prices_cache.get(stock_code)
                if price_hist is not None and date in price_hist.index:
                    idx = price_hist.index.get_loc(date)
                    if idx >= 6:
                        close_prev = float(price_hist.iloc[idx - 1]['close'])
                        close_6d = float(price_hist.iloc[idx - 6]['close'])
                        if close_6d > 0:
                            ret_5d = (close_prev / close_6d - 1) * 100
                            if ret_5d < self.params.buy_ret5d_min:
                                continue
            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue
            buy_candidates.append(item)

        # 매수 실행 (배분 방식 적용)
        if buy_candidates:
            max_holdings = self.params.portfolio_size

            available_slots = max_holdings - len(self.positions)
            if self._today_regime == 'CRISIS':
                available_slots = 0
            elif self._today_regime == 'CAUTION':
                caution_limit = max(0, self.params.caution_max_buy - len(self.positions))
                available_slots = min(available_slots, caution_limit)
            if available_slots <= 0:
                return
            buy_candidates = buy_candidates[:available_slots]

            # 배분 가중치 계산
            weights = self._compute_weights(buy_candidates, date)

            for item in buy_candidates:
                stock_code = item['stock_code']
                price_data = self._get_daily_price(stock_code, date)
                if not price_data:
                    continue
                buy_price = price_data['open']
                if buy_price <= 0:
                    continue

                # 가중치 × 가용 자본
                w = weights.get(stock_code, 0)
                per_stock_capital = self.capital * w
                quantity = int(per_stock_capital / buy_price)
                if quantity <= 0:
                    continue

                factors = self._get_factors(date, stock_code)
                momentum_score = factors.get('momentum_score', 50) if factors else 50
                target_profit = self.params.target_profit_rate
                stop_loss = self.params.stop_loss_rate

                self._execute_buy(
                    stock_code=stock_code, stock_name=item.get('stock_name', stock_code),
                    date=date, buy_price=buy_price, quantity=quantity,
                    target_profit_rate=target_profit, stop_loss_rate=stop_loss,
                    total_score=item['total_score'], factor_rank=item['rank'])
                self._today_rebalancing_bought.add(stock_code)


# ═══════════════════════════════════════════════════════════════
# V100 factor cache 재구성 (raw score)
# ═══════════════════════════════════════════════════════════════
def build_v100_cache(saved_factors, saved_portfolio, portfolio_top_n=50):
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])

    new_factors = {}
    new_portfolio = {}
    for calc_date, stocks in saved_factors.items():
        scored = []
        new_stocks = {}
        for code, f in stocks.items():
            new_total = f.get('value_score', 0)
            nf = dict(f)
            nf['total_score'] = new_total
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, new_total))
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks
        port = []
        for rank, (code, tscore) in enumerate(scored[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': tscore, 'reason': f'V100 {tscore:.1f}',
            })
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


# ═══════════════════════════════════════════════════════════════
# 백테스트 실행
# ═══════════════════════════════════════════════════════════════
def run_bt(start, end, factors, portfolio, prices, params, allocation):
    bt = PositionSizedBacktester(params=params, allocation=allocation)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors
    bt.capital = params.initial_capital

    s_ymd = start.replace("-", "")
    e_ymd = end.replace("-", "")
    trading_days = [f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    for ymd in sorted(factors.keys()) if s_ymd <= ymd <= e_ymd]
    if not trading_days:
        return None
    logging.disable(logging.CRITICAL)
    try:
        prev = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)
            total = bt._calculate_total_value(date)
            dr = (total - prev) / prev if prev > 0 else 0
            cum = (total - params.initial_capital) / params.initial_capital
            bt.daily_snapshots.append(DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total - bt.capital,
                total_value=total, position_count=len(bt.positions),
                daily_return=dr, cumulative_return=cum,
            ))
            prev = total
        bt._close_all_positions(trading_days[-1])
        return bt._create_result(start, end, len(trading_days))
    finally:
        logging.disable(logging.NOTSET)


def kospi_returns_money(prices, initial=10_000_000):
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            ratio = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close'])
            out[tag] = {'return': ratio - 1, 'final': initial * ratio, 'profit': initial * (ratio - 1)}
    return out


ALLOCATIONS = [
    ("Equal (1/N, 현행)",         'equal'),
    ("Score proportional",         'score_prop'),
    ("Rank inverse (1위 ↑)",       'rank_inv'),
    ("Inverse volatility",         'inv_vol'),
    ("Score × Inv Vol",            'score_inv_vol'),
    ("Top-heavy (상위3 50%)",      'top_heavy'),
]


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  자금 배분 멀티버스 (V100 종목 선정 고정, 배분 방식만 변경)")
    emit("  (자본 1,000만원 기준)")
    emit("=" * 130)

    print("\n[1/3] 데이터 로딩...", flush=True)
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    emit(f"  {time.time()-t0:.1f}초, {len(days)}거래일, {len(prices)}종목")

    print("\n[2/3] V100 factor cache 구성...", flush=True)
    fc, pc = build_v100_cache(saved_factors, saved_portfolio)

    k = kospi_returns_money(prices)
    emit("")
    emit("[KOSPI B&H - 천만원 기준]")
    for tag, s, e in PERIODS:
        r = k.get(tag)
        if r:
            emit(f"  {tag:<28}  1,000만 -> {r['final']/10000:,.0f}만 ({r['return']:+.1%})")

    print("\n[3/3] 배분 방식별 백테스트...", flush=True)
    t2 = time.time()
    emit("")
    emit("=" * 130)
    emit(f"{'배분 방식':<25} | {'구간':<28} | {'최종':>10} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    emit("-" * 130)

    results = []
    for label, alloc in ALLOCATIONS:
        row = {'label': label, 'alloc': alloc}
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params(), alloc)
            row[tag] = r
            strategy_profit = r.final_total_value - 10_000_000
            k_prof = k.get(tag, {}).get('profit', 0)
            diff = strategy_profit - k_prof
            emit(f"{label:<25} | {tag:<28} | {r.final_total_value/10000:>8,.0f}만 | "
                  f"{strategy_profit/10000:>+8,.0f}만 | {r.total_return:>+7.1%} | "
                  f"{diff/10000:>+8,.0f}만 | {r.total_trades:>6d}")
        emit("")
        results.append(row)

    emit(f"총 {time.time()-t2:.1f}초")

    # 순위
    emit("")
    emit("=" * 130)
    emit("전체 2년 기준 순위")
    emit("=" * 130)
    k_all = k.get("전체 2년", {}).get('profit', 0)
    sorted_res = sorted(results, key=lambda r: r["전체 2년"].total_return, reverse=True)
    emit(f"{'순위':>4} {'배분 방식':<25} | {'최종':>10} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    for i, r in enumerate(sorted_res, 1):
        res = r["전체 2년"]
        profit = res.final_total_value - 10_000_000
        diff = profit - k_all
        marker = " ★" if "현행" in r['label'] else ""
        emit(f"{i:>4} {r['label']:<25}{marker} | {res.final_total_value/10000:>8,.0f}만 | "
              f"{profit/10000:>+8,.0f}만 | {res.total_return:>+7.1%} | {diff/10000:>+8,.0f}만 | {res.total_trades:>6d}")

    out = Path("results/position_sizing_v2.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
