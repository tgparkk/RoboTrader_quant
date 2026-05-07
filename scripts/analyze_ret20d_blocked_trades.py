#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
buy_ret20d_max 게이트가 차단하는 매수의 정체 분석

baseline(OFF) vs MAX=30 vs MAX=20 세 백테스트의 trade list를 비교해서
어떤 종목/날짜가 차단되는지 추출. 058430 같은 단일 종목이 sharpe 결과를
좌우하는지 (= 과적합 여부) 확인.

각 차단된 매수에 대해:
  - 종목코드, 매수 시도일, 점수, ret_5d, ret_20d
  - 만약 baseline에서는 매수돼서 매도까지 갔다면, 그 손익
"""
import sys
import io
from pathlib import Path
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot, TradeAction


START_DATE = "2023-01-01"
END_DATE = "2026-02-28"

BASE = dict(
    initial_capital=50_000_000,
    portfolio_size=10,
    target_profit_rate=0.12,
    stop_loss_rate=0.06,
    hard_stop_score=65.0,
    soft_stop_score=67.0,
    soft_stop_rank=30,
    safe_score=75.0,
    safe_rank=25,
    min_hold_days=0,
    max_hold_days=0,
    buy_min_score=95.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015,
    sell_cost_rate=0.00245,
    slippage_rate=0.0025,
    regime_filter_enabled=False,
    buy_ret5d_min=-3.0,
    buy_ret5d_max=17.0,
)


def run(loader, trading_days, ret20d_max, start_norm, end_norm):
    merged = {**BASE, 'buy_ret20d_max': ret20d_max}
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
    return bt.trades


def buy_keys(trades):
    """매수 종목+날짜 set + dict (date,code) -> trade"""
    buys = {}
    for t in trades:
        if t.action == TradeAction.BUY:
            buys[(t.date, t.stock_code)] = t
    return buys


def compute_position_pnl(trades, key):
    """특정 매수 (date, code)에 매칭되는 매도 trade 찾아서 손익 계산"""
    date, code = key
    if key not in buy_keys(trades):
        return None
    buy_t = buy_keys(trades)[key]
    # 해당 종목의 같은 매수 후 첫 번째 매도 (FIFO)
    sells_after = [t for t in trades
                   if t.action == TradeAction.SELL
                   and t.stock_code == code
                   and t.date > date]
    if not sells_after:
        return None
    sell_t = sorted(sells_after, key=lambda x: x.date)[0]
    pnl = (sell_t.price - buy_t.price) * buy_t.quantity
    pct = (sell_t.price / buy_t.price - 1) * 100 if buy_t.price > 0 else 0
    return pnl, pct, sell_t.date


def get_ret20d(loader, code, date):
    """ret_20d 계산 (D-1 종가 vs D-21 종가)"""
    price_hist = loader.daily_prices_cache.get(code)
    if price_hist is None or date not in price_hist.index:
        return None
    idx = price_hist.index.get_loc(date)
    if idx < 21:
        return None
    cp = float(price_hist.iloc[idx - 1]['close'])
    c21 = float(price_hist.iloc[idx - 21]['close'])
    if c21 <= 0:
        return None
    return (cp / c21 - 1) * 100


def main():
    print("=" * 100)
    print("  buy_ret20d_max 차단 매수 식별 (baseline vs MAX=30 vs MAX=20)")
    print(f"  기간: {START_DATE} ~ {END_DATE}")
    print("=" * 100)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    # 3 runs
    print("Run baseline (OFF)...")
    trades_off = run(loader, trading_days, None, start_norm, end_norm)
    print("Run MAX=30...")
    trades_30 = run(loader, trading_days, 30.0, start_norm, end_norm)
    print("Run MAX=20...")
    trades_20 = run(loader, trading_days, 20.0, start_norm, end_norm)

    buys_off = buy_keys(trades_off)
    buys_30 = buy_keys(trades_30)
    buys_20 = buy_keys(trades_20)

    print(f"\n매수 건수: OFF={len(buys_off)}  MAX=30={len(buys_30)}  MAX=20={len(buys_20)}")

    # 차단된 매수 = OFF에는 있는데 MAX=N에는 없는 것
    blocked_30 = sorted(set(buys_off.keys()) - set(buys_30.keys()))
    blocked_20 = sorted(set(buys_off.keys()) - set(buys_20.keys()))

    print(f"\nMAX=30이 차단한 매수: {len(blocked_30)}건")
    print(f"MAX=20이 차단한 매수: {len(blocked_20)}건")
    print(f"  (MAX=20에만 추가 차단: {len(set(blocked_20) - set(blocked_30))}건)")

    # 차단된 매수 상세 출력 (MAX=20 기준 — 가장 많이 차단)
    print("\n" + "=" * 100)
    print("  MAX=20이 차단한 매수 상세 (baseline에서 실제 손익)")
    print("=" * 100)
    print(f"  {'date':12} {'code':>7} {'name':12} {'qty':>4} {'price':>7} "
          f"{'ret_20d':>8} | baseline 손익        | 비고")
    print("-" * 100)

    rows_with_pnl = []
    for key in blocked_20:
        date, code = key
        buy_t = buys_off[key]
        ret_20d = get_ret20d(loader, code, date)
        pnl_info = compute_position_pnl(trades_off, key)
        if pnl_info:
            pnl, pct, sell_date = pnl_info
            tag = "[손절]" if pct < 0 else "[익절]"
            pnl_str = f"{pnl:>+10.0f}원 ({pct:>+6.2f}%) → {sell_date}"
        else:
            pnl_str = "(미체결/기간 외)"
            pct = 0
        also_in_30 = key not in blocked_30
        marker = "" if not also_in_30 else " ★MAX=20만 차단"
        rows_with_pnl.append((date, code, buy_t.stock_name, ret_20d, pnl_info, also_in_30))
        print(f"  {date:12} {code:>7} {buy_t.stock_name[:11]:12} {buy_t.quantity:>4} "
              f"{buy_t.price:>7.0f} {ret_20d:>+7.1f}% | {pnl_str}{marker}")

    # 종목별 분포
    print("\n" + "=" * 100)
    print("  차단 매수 종목 분포 (MAX=20 기준)")
    print("=" * 100)
    code_counter = Counter([key[1] for key in blocked_20])
    for code, cnt in code_counter.most_common():
        # 해당 종목 baseline 총 손익
        total_pnl = 0
        for key in [k for k in blocked_20 if k[1] == code]:
            pnl_info = compute_position_pnl(trades_off, key)
            if pnl_info:
                total_pnl += pnl_info[0]
        print(f"  {code} (차단 {cnt}회): baseline 총 손익 {total_pnl:>+10.0f}원")

    # MAX=30이 추가로 잡은 사고 종목
    print("\n" + "=" * 100)
    print("  MAX=30이 잡은 매수 (= MAX=30 차단 ⊂ MAX=20 차단)")
    print("=" * 100)
    for key in blocked_30:
        date, code = key
        buy_t = buys_off[key]
        ret_20d = get_ret20d(loader, code, date)
        pnl_info = compute_position_pnl(trades_off, key)
        if pnl_info:
            pnl, pct, sell_date = pnl_info
            tag = "[손절]" if pct < 0 else "[익절]"
            print(f"  {date:12} {code:>7} {buy_t.stock_name[:11]:12} ret20d={ret_20d:>+5.1f}% "
                  f"손익 {pnl:>+10.0f}원 ({pct:>+6.2f}%) {tag}")
        else:
            print(f"  {date:12} {code:>7} {buy_t.stock_name[:11]:12} ret20d={ret_20d:>+5.1f}% (미체결)")

    # 차단된 매수의 baseline 누적 손익 (MAX=20 vs MAX=30)
    print("\n" + "=" * 100)
    print("  차단으로 회피한 누적 손익 (baseline에서의 실현 손익)")
    print("=" * 100)
    for label, blocked_set in [('MAX=30', blocked_30), ('MAX=20', blocked_20)]:
        wins = losses = 0
        win_pnl = loss_pnl = 0
        for key in blocked_set:
            pnl_info = compute_position_pnl(trades_off, key)
            if pnl_info:
                pnl, pct, _ = pnl_info
                if pnl > 0:
                    wins += 1
                    win_pnl += pnl
                else:
                    losses += 1
                    loss_pnl += pnl
        net = win_pnl + loss_pnl
        print(f"  {label}: 차단 {len(blocked_set)}건 → "
              f"baseline에선 익절 {wins}건 (+{win_pnl:.0f}원) / 손절 {losses}건 ({loss_pnl:.0f}원) "
              f"→ 회피 순효과 {-net:>+10.0f}원")

    return 0


if __name__ == "__main__":
    sys.exit(main())
