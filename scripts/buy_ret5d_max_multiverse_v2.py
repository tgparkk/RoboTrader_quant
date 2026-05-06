#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BUY_RET5D_MAX 멀티버스 v2 — 058430 사고 포함 + 임계값 세분화 + 차단 효과 추적

기존 v1(buy_ret5d_max_multiverse.py) 보강:
  1. 기간을 058430 사고 시점까지 연장 (~2026-05-06)
  2. SWEEP_VALUES 세분화: 058430 4/30(+64.83%), 5/4(+49.91%) 사이 결정 영역 강조
  3. 종목별 차단 효과 별도 추적 (058430 매매 추적)
  4. 분기별 sharpe 추가 (2026Q1, 2026Q2)
  5. baseline 진단 출력

사용법:
    python scripts/buy_ret5d_max_multiverse_v2.py
    python scripts/buy_ret5d_max_multiverse_v2.py --start 2024-01-01 --end 2026-05-06
    python scripts/buy_ret5d_max_multiverse_v2.py --output results/buy_ret5d_max_v2.csv
"""
import sys
import time
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot, TradeAction
from backtest.metrics import MetricsCalculator


START_DATE = "2023-01-01"
END_DATE = "2026-05-06"

# 운영 baseline (V100, TP12/SL6, BUY_RET5D_MIN=-3, sm 비활성)
# v1과 동일한 BASE를 유지하여 결과 비교 가능
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
    buy_ret5d_max=None,
)

# 사고 종목 4/30(+64.83%), 5/4(+49.91%) 영역 강조
SWEEP_VALUES = [
    None,
    100.0, 80.0, 70.0, 60.0,
    50.0, 45.0, 40.0, 35.0, 30.0,
    25.0, 20.0, 17.0, 15.0, 12.0, 10.0, 8.0, 5.0,
]

YEARS = ["2023", "2024", "2025", "2026"]
TRACK_CODE = "058430"  # 차단 효과 추적 대상


def yearly_sharpe(snapshots, year_prefix):
    subset = [s for s in snapshots if s.date.startswith(year_prefix)]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def quarter_sharpe(snapshots, year, quarter):
    """quarter: 1=01-03, 2=04-06, 3=07-09, 4=10-12"""
    months = {1: ('01', '02', '03'), 2: ('04', '05', '06'),
              3: ('07', '08', '09'), 4: ('10', '11', '12')}[quarter]
    subset = [s for s in snapshots
              if s.date.startswith(year) and s.date[5:7] in months]
    if len(subset) < 2:
        return float('nan')
    return MetricsCalculator.calculate_sharpe_ratio(subset)


def track_stock_pnl(trades, code):
    """특정 종목의 매수 횟수 / 매도 횟수 / 누적 손익 / 손절 횟수"""
    buys = [t for t in trades if t.stock_code == code and t.action == TradeAction.BUY]
    sells = [t for t in trades if t.stock_code == code and t.action == TradeAction.SELL]
    pnl = sum((t.profit_loss or 0) for t in sells)
    stop_loss_cnt = sum(1 for t in sells if t.reason and '손절' in t.reason)
    return {
        'buys': len(buys),
        'sells': len(sells),
        'pnl': pnl,
        'stop_loss_cnt': stop_loss_cnt,
    }


def run_one(loader, trading_days, ret5d_max, start_norm, end_norm):
    merged = {**BASE, 'buy_ret5d_max': ret5d_max}
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
    result = bt._create_result(start_norm, end_norm, len(trading_days))

    yearly = {y: yearly_sharpe(bt.daily_snapshots, y) for y in YEARS}
    q26 = {q: quarter_sharpe(bt.daily_snapshots, '2026', q) for q in (1, 2)}
    track = track_stock_pnl(bt.trades, TRACK_CODE)

    return {
        'buy_ret5d_max': ret5d_max,
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
        'sharpe_2023': yearly['2023'],
        'sharpe_2024': yearly['2024'],
        'sharpe_2025': yearly['2025'],
        'sharpe_2026': yearly['2026'],
        'sharpe_2026Q1': q26[1],
        'sharpe_2026Q2': q26[2],
        f'{TRACK_CODE}_buys': track['buys'],
        f'{TRACK_CODE}_sells': track['sells'],
        f'{TRACK_CODE}_pnl': track['pnl'],
        f'{TRACK_CODE}_stops': track['stop_loss_cnt'],
    }


def fmt(v, dp=2):
    if v != v:  # NaN
        return "  n/a"
    return f"{v:>6.{dp}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=START_DATE)
    ap.add_argument('--end', default=END_DATE)
    ap.add_argument('--output', default='results/buy_ret5d_max_multiverse_v2.csv')
    args = ap.parse_args()

    print("=" * 110)
    print("  BUY_RET5D_MAX 멀티버스 v2 (058430 사고 포함 + 차단 효과 추적)")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  Baseline: TP12/SL6, V100 buy_min_score=95, BUY_RET5D_MIN=-3%, sm 비활성")
    print(f"  추적 종목: {TRACK_CODE} (4/30 ret_5d +64.83%, 5/4 +49.91% 사고 케이스)")
    print(f"  Sweep: {len(SWEEP_VALUES)}개 값")
    print("=" * 110)

    print("\n데이터 로딩 중...")
    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(args.start)
    end_norm = loader._normalize_date(args.end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    rows = []
    t0 = time.time()
    for i, v in enumerate(SWEEP_VALUES, 1):
        ts = time.time()
        r = run_one(loader, trading_days, v, start_norm, end_norm)
        elapsed = time.time() - ts
        label = "OFF" if v is None else f"+{v:>4.0f}%"
        marker = "  ★ 현행" if v is None else ""
        track_str = (f"{TRACK_CODE}: 매수{r[f'{TRACK_CODE}_buys']:>2d} "
                     f"손절{r[f'{TRACK_CODE}_stops']:>2d} "
                     f"손익{int(r[f'{TRACK_CODE}_pnl']):>+8,}")
        print(f"  [{i:>2d}/{len(SWEEP_VALUES)}] MAX={label:>6} → "
              f"샤프 {r['sharpe']:>5.2f}  수익 {r['total_return']:>7.0%}  "
              f"MDD {r['mdd']:>5.1%}  승률 {r['win_rate']:>5.1%}  "
              f"거래 {r['trades']:>4d}  | {track_str}  ({elapsed:.1f}s){marker}")
        rows.append(r)
    total = time.time() - t0
    print(f"\n총 소요: {total:.1f}초")

    # 전체 결과 (sharpe 순)
    print("\n" + "=" * 130)
    print("  결과 (전체 기간 sharpe 순)")
    print("=" * 130)
    print(f"  {'MAX':>6} │ {'sharpe':>6} {'return':>8} {'MDD':>6} {'wr':>5} "
          f"{'PF':>5} {'trades':>6} │ {'2023':>6} {'2024':>6} {'2025':>6} "
          f"{'2026Q1':>7} {'2026Q2':>7} │ {'058430':>16}")
    print("-" * 130)
    for r in sorted(rows, key=lambda x: x['sharpe'], reverse=True):
        v = r['buy_ret5d_max']
        label = "OFF" if v is None else f"+{v:.0f}%"
        marker = " ★" if v is None else "  "
        track_short = f"매{r[f'{TRACK_CODE}_buys']:d}/손{r[f'{TRACK_CODE}_stops']:d}/{int(r[f'{TRACK_CODE}_pnl']):+,}"
        print(f"  {label:>6} │ {r['sharpe']:>6.2f} {r['total_return']:>7.0%} "
              f"{r['mdd']:>5.1%} {r['win_rate']:>4.0%} {r['pf']:>5.2f} {r['trades']:>6d} │ "
              f"{fmt(r['sharpe_2023'])} {fmt(r['sharpe_2024'])} "
              f"{fmt(r['sharpe_2025'])} "
              f"{fmt(r['sharpe_2026Q1'])} {fmt(r['sharpe_2026Q2'])} │ "
              f"{track_short:>16}{marker}")

    # 채택 기준 평가
    base = next(r for r in rows if r['buy_ret5d_max'] is None)
    print("\n" + "=" * 110)
    print("  채택 기준 평가 (현행 None 대비)")
    print("=" * 110)
    print(f"  기준: ① in-sample sharpe ≥ base  ② 연도별 4개 중 ≥3개 우위  ③ 거래수 감소 ≤30%")
    print(f"        ④ 058430 손절 횟수 감소 (사고 패턴 차단 효과)")
    print(f"  base sharpe={base['sharpe']:.2f}, trades={base['trades']}, "
          f"058430 손절={base[f'{TRACK_CODE}_stops']}회 손익={int(base[f'{TRACK_CODE}_pnl']):+,}원")
    print()
    candidates = []
    for r in sorted(rows, key=lambda x: (x['buy_ret5d_max'] is None, -(x['buy_ret5d_max'] or 0))):
        if r['buy_ret5d_max'] is None:
            continue
        c1 = r['sharpe'] >= base['sharpe']
        years_better = sum(
            1 for y in YEARS
            if (r[f'sharpe_{y}'] == r[f'sharpe_{y}']
                and base[f'sharpe_{y}'] == base[f'sharpe_{y}']
                and r[f'sharpe_{y}'] >= base[f'sharpe_{y}'])
        )
        c2 = years_better >= 3
        trade_drop = 1 - r['trades'] / base['trades'] if base['trades'] > 0 else 0
        c3 = trade_drop <= 0.30
        c4 = r[f'{TRACK_CODE}_stops'] < base[f'{TRACK_CODE}_stops']
        passed = c1 and c2 and c3 and c4
        if passed:
            candidates.append(r)
        flag = "PASS" if passed else "FAIL"
        print(f"  MAX +{r['buy_ret5d_max']:>4.0f}% | "
              f"sharpe {r['sharpe']:>5.2f} {'OK' if c1 else 'NO':<3} | "
              f"yearly {years_better}/4 {'OK' if c2 else 'NO':<3} | "
              f"trades drop {trade_drop:>5.1%} {'OK' if c3 else 'NO':<3} | "
              f"058430 손절 {r[f'{TRACK_CODE}_stops']:>2d} {'OK' if c4 else 'NO':<3} | {flag}")

    print()
    if candidates:
        best = max(candidates, key=lambda x: x['sharpe'])
        print(f"  [PASS] 채택 후보: MAX = +{best['buy_ret5d_max']:.0f}% "
              f"(sharpe {best['sharpe']:.2f}, "
              f"058430 손절 {base[f'{TRACK_CODE}_stops']} → {best[f'{TRACK_CODE}_stops']})")
    else:
        print("  [FAIL] 채택 기준을 모두 만족하는 임계값 없음 (도입 보류)")

    # CSV 저장
    out_path = project_root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n결과 저장: {out_path}")


if __name__ == '__main__':
    main()
