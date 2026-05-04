#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Value 분해 멀티버스: PER / PBR / PSR 중 알파의 원천 찾기

Value = PER(30%) + PBR(35%) + PSR(35%) 중 어느 요소가 OOS 알파의 주범인가?

시나리오:
  - PER only, PBR only, PSR only
  - PER+PBR, PER+PSR, PBR+PSR
  - PER+PBR+PSR (=V100 재현)

공시 지연: 분기 45일 / 연간 90일 (look-ahead 제거)
기간: IS (2024-04~2025-06) / OOS (2025-07~2026-04) / ALL (2년)
"""
import sys
import time
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import psycopg2

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import BACKTEST_DB_CONFIG


PERIODS = [
    ("IS ", "2024-04-01", "2025-06-30"),
    ("OOS", "2025-07-01", "2026-04-09"),
    ("ALL", "2024-04-01", "2026-04-09"),
]


def common_params(**ov):
    base = dict(
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
        use_dynamic_targets=False,
        rebalancing_sell_cooldown_days=3,
    )
    base.update(ov)
    return BacktestParams(**base)


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def compute_sub_scores(daily_prices_df, financials_df, quarterly_lag=45, annual_lag=90):
    """
    각 (stock_code, calc_date)에 대해 PER/PBR/PSR 개별 점수(0~100) 계산.
    available_date(공시 지연) 반영. bisect + itertuples 기반 고속 버전.

    Returns:
        dict[calc_date_yyyymmdd][stock_code] = {'per': s, 'pbr': s, 'psr': s}
    """
    import bisect

    # 1) 재무: available_date 계산 + 종목별 정렬 배열 준비
    print("  [sub_scores] 재무 데이터 인덱싱...", flush=True)
    fin = financials_df.copy()
    rd = pd.to_datetime(fin['report_date'])
    is_annual = (rd.dt.month == 12) & (rd.dt.day == 31)
    lag_days = np.where(is_annual, annual_lag, quarterly_lag)
    fin['available_date'] = (rd + pd.to_timedelta(lag_days, unit='D')).dt.strftime('%Y-%m-%d')
    fin = fin.sort_values(['stock_code', 'available_date']).reset_index(drop=True)

    # 종목별: (available_dates 리스트, ni, eq, rev 배열)
    fin_cache = {}
    for code, g in fin.groupby('stock_code'):
        fin_cache[code] = (
            g['available_date'].tolist(),
            g['net_income'].tolist(),
            g['total_equity'].tolist(),
            g['revenue'].tolist(),
        )
    print(f"  [sub_scores] 재무 캐시: {len(fin_cache)}종목", flush=True)

    # 2) 가격: (code, date) → market_cap 딕셔너리
    print("  [sub_scores] 가격 인덱싱 (itertuples)...", flush=True)
    prices_mc = {}
    for row in daily_prices_df.itertuples(index=False):
        mc = row.market_cap
        if mc is None or pd.isna(mc) or mc <= 0:
            continue
        prices_mc[(row.stock_code, row.date)] = float(mc)
    print(f"  [sub_scores] 가격×날짜 인덱스: {len(prices_mc):,}건", flush=True)

    # 3) calc_date별 계산
    calc_dates = sorted(daily_prices_df['date'].unique())
    print(f"  [sub_scores] 스코어 계산 시작: {len(calc_dates)}일", flush=True)

    out = {}
    codes_with_fin = list(fin_cache.keys())
    t_start = time.time()
    for di, calc_date in enumerate(calc_dates):
        out_date = {}
        for code in codes_with_fin:
            mc = prices_mc.get((code, calc_date))
            if mc is None:
                continue
            avail_dates, nis, eqs, revs = fin_cache[code]
            # 이분탐색: available_date <= calc_date 중 가장 늦은 것
            idx = bisect.bisect_right(avail_dates, calc_date) - 1
            if idx < 0:
                continue
            ni = nis[idx]
            eq = eqs[idx]
            rev = revs[idx]

            per_s = 0.0
            pbr_s = 0.0
            psr_s = 0.0

            if ni is not None and not pd.isna(ni):
                ni = float(ni)
                if ni > 0:
                    per = mc / ni
                    per_s = clamp(100 - min(per / 50 * 100, 100))
            if eq is not None and not pd.isna(eq):
                eq = float(eq)
                if eq > 0:
                    pbr = mc / eq
                    pbr_s = clamp(100 - min(pbr / 5 * 100, 100))
            if rev is not None and not pd.isna(rev):
                rev = float(rev)
                if rev > 0:
                    psr = mc / rev
                    psr_s = clamp(100 - min(psr / 10 * 100, 100))

            out_date[code] = {'per': per_s, 'pbr': pbr_s, 'psr': psr_s}
        out[calc_date.replace('-', '')] = out_date

        if (di + 1) % 50 == 0 or di == len(calc_dates) - 1:
            el = time.time() - t_start
            rate = (di + 1) / el if el > 0 else 0
            print(f"  [sub_scores] 진행 {di+1}/{len(calc_dates)} ({rate:.1f}일/s)", flush=True)

    return out


def build_variant_cache(saved_factors, sub_scores, weights):
    """
    sub-score 조합으로 total_score 재계산 + portfolio 재정렬.
    weights = (per_w, pbr_w, psr_w)
    """
    per_w, pbr_w, psr_w = weights
    wsum = per_w + pbr_w + psr_w
    if wsum <= 0:
        return None, None

    new_factors = {}
    new_portfolio = {}
    stock_names = {}

    for calc_date, stocks in saved_factors.items():
        # factors_cache의 calc_date는 yyyymmdd
        sub_for_date = sub_scores.get(calc_date, {})
        new_stocks = {}
        scored = []

        for code, f in stocks.items():
            sub = sub_for_date.get(code)
            if sub is None:
                # 재무데이터 없는 종목 → 중립 50 (V100 재현 로직과 일관)
                new_total = 50.0
            else:
                new_total = (
                    sub['per'] * per_w +
                    sub['pbr'] * pbr_w +
                    sub['psr'] * psr_w
                ) / wsum
            new_total = clamp(new_total)

            nf = dict(f)
            nf['total_score'] = new_total
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, new_total))
            # 이름 수집
            if 'stock_name' in f:
                stock_names[code] = f.get('stock_name', code)

        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks

        port = []
        for rank, (code, tscore) in enumerate(scored[:50], 1):
            port.append({
                'calc_date': calc_date,
                'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank,
                'total_score': tscore,
                'reason': f'w{weights} {tscore:.1f}',
            })
        new_portfolio[calc_date] = port

    return new_factors, new_portfolio


def run_bt(start, end, factors, portfolio, prices, params):
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors
    bt.capital = params.initial_capital

    s_ymd = start.replace("-", "")
    e_ymd = end.replace("-", "")
    trading_days = []
    for ymd in sorted(factors.keys()):
        if s_ymd <= ymd <= e_ymd:
            trading_days.append(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")
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


def kospi_returns(prices):
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            ret = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close']) - 1
            out[tag] = ret
    return out


SCENARIOS = [
    ("PER only",           (1.0, 0.0, 0.0)),
    ("PBR only",           (0.0, 1.0, 0.0)),
    ("PSR only",           (0.0, 0.0, 1.0)),
    ("PER+PBR (50/50)",    (0.5, 0.5, 0.0)),
    ("PER+PSR (50/50)",    (0.5, 0.0, 0.5)),
    ("PBR+PSR (50/50)",    (0.0, 0.5, 0.5)),
    ("V100 재현 (30/35/35)",(0.30, 0.35, 0.35)),
]


def main():
    log_lines = []
    def emit(s=""):
        print(s)
        log_lines.append(s)

    emit("=" * 120)
    emit("  Value 분해 멀티버스 (PER / PBR / PSR 알파 원천 탐색)")
    emit("=" * 120)

    print("\n데이터 로딩...")
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    emit(f"로드 {time.time()-t0:.1f}초, {len(days)}거래일, {len(saved_factors)}일 팩터")

    # 재무 + 가격(마켓캡 포함) 조회
    print("재무 + 가격 데이터 로딩...")
    t1 = time.time()
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        fin_df = pd.read_sql_query(
            "SELECT stock_code, report_date, net_income, total_equity, revenue FROM financial_statements",
            conn
        )
        # 가격은 이미 로드된 prices cache에서 market_cap 뽑아내기
        # 하지만 Backtester._preload_data는 market_cap을 select하지 않음.
        # 별도로 daily_prices에서 mc 조회.
        dp_df = pd.read_sql_query(
            "SELECT stock_code, date::text AS date, market_cap "
            "FROM daily_prices WHERE date >= %s AND date <= %s",
            conn, params=('2024-04-01', '2026-04-09')
        )
    emit(f"  재무 {len(fin_df):,}행, 일봉(mc) {len(dp_df):,}행 로드 ({time.time()-t1:.1f}초)")

    print("Sub-score 계산 중 (PER/PBR/PSR)...")
    t2 = time.time()
    sub_scores = compute_sub_scores(dp_df, fin_df, quarterly_lag=45, annual_lag=90)
    total_entries = sum(len(v) for v in sub_scores.values())
    emit(f"  sub-score 계산 완료: {len(sub_scores)}일 × 평균 {total_entries//max(1,len(sub_scores))}종목 ({time.time()-t2:.1f}초)")
    emit("")

    kospi = kospi_returns(prices)
    emit(f"[KOSPI B&H]  IS {kospi.get('IS ', 0):+.1%}  OOS {kospi.get('OOS', 0):+.1%}  ALL {kospi.get('ALL', 0):+.1%}")
    emit("")

    emit("=" * 120)
    emit("Value 하위 요소 분해 결과")
    emit("=" * 120)
    emit(f"{'Scenario':<24}  {'IS_Ret':>8} {'IS_Shr':>6}  {'OOS_Ret':>8} {'OOS_Shr':>6}  {'ALL_Ret':>8} {'ALL_Shr':>6} {'ALL_MDD':>7} {'ALL_Tr':>6}  {'IS_α':>6} {'OOS_α':>7} {'ALL_α':>7}")
    emit("-" * 120)

    results = []
    for label, w in SCENARIOS:
        t = time.time()
        fc, pc = build_variant_cache(saved_factors, sub_scores, w)
        row = {'label': label, 'w': w}
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params())
            row[tag] = r
        is_a = row['IS '].total_return - kospi.get('IS ', 0)
        oos_a = row['OOS'].total_return - kospi.get('OOS', 0)
        all_a = row['ALL'].total_return - kospi.get('ALL', 0)
        row.update({'is_alpha': is_a, 'oos_alpha': oos_a, 'all_alpha': all_a})
        results.append(row)
        emit(f"{label:<24}  "
              f"{row['IS '].total_return:>7.1%} {row['IS '].sharpe_ratio:>6.2f}  "
              f"{row['OOS'].total_return:>7.1%} {row['OOS'].sharpe_ratio:>6.2f}  "
              f"{row['ALL'].total_return:>7.1%} {row['ALL'].sharpe_ratio:>6.2f} "
              f"{row['ALL'].max_drawdown:>6.1%} {row['ALL'].total_trades:>6d}  "
              f"{is_a:>+5.1%} {oos_a:>+6.1%} {all_a:>+6.1%}")

    emit("")
    emit("=" * 120)
    emit("정렬: OOS 알파 기준")
    emit("=" * 120)
    results.sort(key=lambda r: r['oos_alpha'], reverse=True)
    emit(f"{'순위':>4}  {'Scenario':<24}  {'OOS_α':>7} {'IS_α':>6} {'ALL_α':>7} {'OOS_Shr':>7}")
    for i, r in enumerate(results, 1):
        emit(f"{i:>4}  {r['label']:<24}  {r['oos_alpha']:>+6.1%} {r['is_alpha']:>+5.1%} {r['all_alpha']:>+6.1%} {r['OOS'].sharpe_ratio:>7.2f}")

    out = Path("results/value_decomp.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
