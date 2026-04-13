#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실전매매 기간 백테스트 비교
2026-02-12 ~ 2026-03-26 (실전매매 기간)

Baseline  : 포트폴리오 = total_score 정렬 (기존 방식)
Two-stage : 포트폴리오 = hybrid_score = total_score*50% + timing_score*50% 정렬 (신규)

양쪽 모두 동일 조건: TP=12%, SL=6%, portfolio_size=10, buy_min_score=65.0
"""
import sys
import time
import numpy as np
import psycopg2
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot
from backtest.factor_calculator import calc_timing_score
from config.db_config import BACKTEST_DB_CONFIG


# ---------------------------------------------------------------------------
# 타이밍 점수 계산 (각 거래일, 전 종목)
# ---------------------------------------------------------------------------

def build_timing_scores(trading_days: List[str]) -> Dict[str, Dict[str, float]]:
    """
    backtest DB의 일봉 데이터로 각 거래일별 전 종목 timing_score 계산.
    반환: {yyyymmdd: {stock_code: timing_score}}
    타이밍 점수 계산에는 최소 61일치 종가 히스토리 필요.
    """
    if not trading_days:
        return {}

    # 타이밍 점수 계산에는 최소 61거래일 이전 데이터가 필요
    # 거래일 기준 100일 여유분 추가 (약 140일 캘린더)
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(trading_days[0], "%Y-%m-%d") - timedelta(days=140)
    extended_start = start_dt.strftime("%Y-%m-%d")
    end_date = trading_days[-1]

    print(f"  일봉 로드 중: {extended_start} ~ {end_date} (타이밍 계산용)")
    t0 = time.time()

    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        df = pd.read_sql_query(
            """
            SELECT stock_code, date, close
            FROM daily_prices
            WHERE date >= %s AND date <= %s
              AND stock_code NOT IN ('KS11', 'KQ11')
            ORDER BY stock_code, date
            """,
            conn, params=(extended_start, end_date)
        )

    print(f"  일봉 로드 완료: {len(df):,}건 ({time.time()-t0:.1f}s)")

    # stock_code별 인덱스 구축
    prices_by_stock: Dict[str, pd.Series] = {}
    for code, grp in df.groupby('stock_code'):
        prices_by_stock[code] = grp.sort_values('date')['close'].values

    # 각 거래일까지 누적 종가로 timing_score 계산
    # (trading_days는 오름차순이므로 날짜별 인덱스를 활용)
    date_to_idx: Dict[str, Dict[str, int]] = {}
    for code, grp in df.groupby('stock_code'):
        dates_arr = grp.sort_values('date')['date'].values
        for i, d in enumerate(dates_arr):
            if d not in date_to_idx:
                date_to_idx[d] = {}
            date_to_idx[d][code] = i

    # 종목별 날짜-인덱스 맵 (O(1) 조회용)
    stock_date_index: Dict[str, Dict[str, int]] = {}
    for code, grp in df.groupby('stock_code'):
        grp_sorted = grp.sort_values('date')
        stock_date_index[code] = {d: i for i, d in enumerate(grp_sorted['date'].values)}

    result: Dict[str, Dict[str, float]] = {}
    for date in trading_days:
        yyyymmdd = date.replace('-', '')
        scores: Dict[str, float] = {}

        for code, closes in prices_by_stock.items():
            idx_map = stock_date_index.get(code, {})
            if date not in idx_map:
                continue
            idx = idx_map[date]
            # 해당 날짜까지의 종가 (포함)
            history = closes[: idx + 1]
            scores[code] = calc_timing_score(history)

        result[yyyymmdd] = scores
        print(f"    {yyyymmdd}: timing_score 계산 완료 ({len(scores)} 종목)")

    return result


# ---------------------------------------------------------------------------
# 포트폴리오 캐시 구성
# ---------------------------------------------------------------------------

def build_portfolio_caches(
    trading_days: List[str],
    timing_scores: Dict[str, Dict[str, float]],
    portfolio_size: int = 50,
    top_n: int = 10,
    buy_min_score: float = 65.0,
) -> tuple:
    """
    backtest DB의 quant_factors + timing_scores 로 두 가지 포트폴리오 캐시를 생성.

    baseline_cache : total_score 정렬
    twostage_cache : hybrid_score = total_score*0.5 + timing_score*0.5 정렬

    반환 형식: {yyyymmdd: [{stock_code, stock_name, rank, total_score, ...}, ...]}
    backtester._execute_rebalancing 이 기대하는 형식과 동일.
    """
    start_yyyymmdd = trading_days[0].replace('-', '')
    end_yyyymmdd = trading_days[-1].replace('-', '')

    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        factors_df = pd.read_sql_query(
            """
            SELECT f.calc_date, f.stock_code,
                   COALESCE(n.stock_name, f.stock_code) AS stock_name,
                   f.total_score, f.factor_rank
            FROM quant_factors f
            LEFT JOIN stock_names n ON f.stock_code = n.stock_code
            WHERE f.calc_date >= %s AND f.calc_date <= %s
            ORDER BY f.calc_date, f.total_score DESC
            """,
            conn, params=(start_yyyymmdd, end_yyyymmdd)
        )

    print(f"\n  팩터 데이터: {len(factors_df):,}건 로드")

    baseline_cache: Dict[str, List[dict]] = {}
    twostage_cache: Dict[str, List[dict]] = {}

    for calc_date_raw, grp in factors_df.groupby('calc_date'):
        calc_date = str(calc_date_raw)
        day_timing = timing_scores.get(calc_date, {})

        rows = grp.to_dict('records')

        # hybrid_score 추가
        for row in rows:
            ts = day_timing.get(row['stock_code'], 50.0)
            row['timing_score'] = ts
            row['hybrid_score'] = row['total_score'] * 0.5 + ts * 0.5

        # --- Baseline: total_score 기준 정렬, 상위 portfolio_size 후보 ---
        baseline_sorted = sorted(rows, key=lambda x: (x['total_score'], x['factor_rank']), reverse=True)
        baseline_top = []
        for rank, r in enumerate(
            [r for r in baseline_sorted if r['total_score'] >= buy_min_score][:portfolio_size], 1
        ):
            entry = dict(r)
            entry['rank'] = rank
            baseline_top.append(entry)
        baseline_cache[calc_date] = baseline_top

        # --- Two-stage: hybrid_score 기준 정렬, 단 total_score >= buy_min_score 필터 후 ---
        twostage_candidates = [r for r in rows if r['total_score'] >= buy_min_score]
        twostage_sorted = sorted(twostage_candidates,
                                 key=lambda x: (x['hybrid_score'], x['factor_rank']),
                                 reverse=True)
        twostage_top = []
        for rank, r in enumerate(twostage_sorted[:portfolio_size], 1):
            entry = dict(r)
            entry['rank'] = rank
            twostage_top.append(entry)
        twostage_cache[calc_date] = twostage_top

    print(f"  포트폴리오 캐시 구성 완료: baseline={len(baseline_cache)}일, two-stage={len(twostage_cache)}일")
    return baseline_cache, twostage_cache


# ---------------------------------------------------------------------------
# 단일 백테스트 실행 (캐시 주입 방식)
# ---------------------------------------------------------------------------

def run_single_backtest(
    label: str,
    params: BacktestParams,
    trading_days: List[str],
    prices_cache: dict,
    portfolio_cache: dict,
    factors_cache: dict,
    start_norm: str,
    end_norm: str,
) -> BacktestResult:
    """캐시를 외부에서 주입해서 데이터 재로드 없이 백테스트 실행"""
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = prices_cache
    bt.portfolio_cache = portfolio_cache
    bt.factors_cache = factors_cache

    prev_total_value = params.initial_capital
    for date in trading_days:
        bt._today_stop_profit_sold = set()
        bt._today_rebalancing_bought = set()
        bt._today_regime = 'NORMAL'
        # TP/SL 먼저, 그다음 리밸런싱 (실전과 동일)
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
    return bt._create_result(start_norm, end_norm, len(trading_days))


# ---------------------------------------------------------------------------
# 비교 출력
# ---------------------------------------------------------------------------

def print_comparison(baseline: BacktestResult, twostage: BacktestResult):
    """두 결과 비교 테이블 출력"""
    def pct(v):
        return f"{v:.2%}"

    def diff(a, b, is_pct=True, higher_better=True):
        d = b - a
        sign = '+' if d >= 0 else ''
        fmt = f"{sign}{d:.2%}" if is_pct else f"{sign}{d:.2f}"
        arrow = ' ▲' if (d > 0) == higher_better else (' ▼' if d != 0 else '  ')
        return fmt + arrow

    print("\n" + "=" * 75)
    print("실전매매 기간 백테스트 비교 (2026-02-12 ~ 2026-03-26)")
    print("Baseline: total_score 정렬  |  Two-stage: hybrid_score 정렬")
    print("=" * 75)
    print(f"{'지표':<22} {'Baseline':>14} {'Two-stage':>14} {'차이(B→T)':>14}")
    print("-" * 75)

    rows = [
        ("총 수익률",        baseline.total_return,      twostage.total_return,      True,  True),
        ("연환산 수익률",    baseline.annualized_return,  twostage.annualized_return, True,  True),
        ("최대낙폭 (MDD)",   baseline.max_drawdown,       twostage.max_drawdown,      True,  False),
        ("변동성",           baseline.volatility,         twostage.volatility,        True,  False),
    ]

    for label, a, b, is_pct, higher_better in rows:
        print(f"  {label:<20} {pct(a):>14} {pct(b):>14} {diff(a, b, is_pct, higher_better):>14}")

    print("-" * 75)

    # Sharpe (not pct)
    def diff_float(a, b, higher_better=True):
        d = b - a
        sign = '+' if d >= 0 else ''
        arrow = ' ▲' if (d > 0) == higher_better else (' ▼' if d != 0 else '  ')
        return f"{sign}{d:.2f}{arrow}"

    print(f"  {'샤프 비율':<20} {baseline.sharpe_ratio:>14.2f} {twostage.sharpe_ratio:>14.2f} "
          f"{diff_float(baseline.sharpe_ratio, twostage.sharpe_ratio):>14}")

    print("-" * 75)

    bt_wins = baseline.winning_trades
    bt_total = baseline.winning_trades + baseline.losing_trades
    ts_wins = twostage.winning_trades
    ts_total = twostage.winning_trades + twostage.losing_trades

    print(f"  {'총 거래 수':<20} {baseline.total_trades:>14d} {twostage.total_trades:>14d} "
          f"  {twostage.total_trades - baseline.total_trades:+d}")
    print(f"  {'승률':<20} {pct(baseline.win_rate):>14} {pct(twostage.win_rate):>14} "
          f"{diff(baseline.win_rate, twostage.win_rate, True, True):>14}")
    print(f"  {'수익 팩터 (PF)':<20} {baseline.profit_factor:>14.2f} {twostage.profit_factor:>14.2f} "
          f"{diff_float(baseline.profit_factor, twostage.profit_factor):>14}")
    print(f"  {'승/패':<20} {f'{bt_wins}W/{baseline.losing_trades}L':>14} "
          f"{f'{ts_wins}W/{twostage.losing_trades}L':>14}")

    print("-" * 75)
    print(f"  {'최종 자산':<20} {baseline.final_total_value:>14,.0f} {twostage.final_total_value:>14,.0f}")
    delta_val = twostage.final_total_value - baseline.final_total_value
    print(f"  {'자산 차이':<20} {'':>14} {delta_val:>+14,.0f}")
    print(f"  {'총 거래비용':<20} {baseline.total_trading_cost:>14,.0f} {twostage.total_trading_cost:>14,.0f}")
    print("=" * 75)

    # Portfolio overlap analysis
    print("\n--- 포트폴리오 구성 비교 (첫 거래일 기준) ---")


def print_portfolio_diff(baseline_cache: dict, twostage_cache: dict, trading_days: List[str]):
    """각 거래일별 포트폴리오 구성 차이 출력"""
    for date in trading_days:
        yyyymmdd = date.replace('-', '')
        b_stocks = {r['stock_code'] for r in baseline_cache.get(yyyymmdd, [])[:10]}
        t_stocks = {r['stock_code'] for r in twostage_cache.get(yyyymmdd, [])[:10]}
        only_baseline = b_stocks - t_stocks
        only_twostage = t_stocks - b_stocks
        overlap = len(b_stocks & t_stocks)

        print(f"  {date}: 공통 {overlap}/10  |  Baseline만: {sorted(only_baseline)}  |  Two-stage만: {sorted(only_twostage)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 75)
    print("실전매매 기간 백테스트 비교")
    print("Baseline (total_score) vs Two-stage (hybrid_score)")
    print("=" * 75)
    print(f"기간: 2026-02-12 ~ 2026-03-26")
    print(f"TP=12%, SL=6%, portfolio_size=10, buy_min_score=65.0")
    print()

    PARAMS = BacktestParams(
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
        use_dynamic_targets=False,
        buy_cost_rate=0.00015,
        sell_cost_rate=0.00245,
        slippage_rate=0.001,
        regime_filter_enabled=False,
    )

    START_DATE = "2026-02-12"
    END_DATE = "2026-03-26"

    # 1. 공통 데이터 로드 (가격 캐시, 팩터 캐시)
    print("1. 공통 데이터 로드 중...")
    loader = Backtester(params=PARAMS)
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    prices_cache = loader.daily_prices_cache
    factors_cache = loader.factors_cache
    print(f"  가격 캐시: {len(prices_cache)}종목, 팩터 캐시: {len(factors_cache)}일, 거래일: {len(trading_days)}일")

    # 2. 타이밍 점수 계산 (가격 히스토리 기반)
    print("\n2. 타이밍 점수 계산 중...")
    timing_scores = build_timing_scores(trading_days)

    # 3. 두 가지 포트폴리오 캐시 구성
    print("\n3. 포트폴리오 캐시 구성 중...")
    baseline_cache, twostage_cache = build_portfolio_caches(
        trading_days=trading_days,
        timing_scores=timing_scores,
        portfolio_size=50,
        top_n=10,
        buy_min_score=65.0,
    )

    # 4. 두 백테스트 실행
    print("\n4. 백테스트 실행 중...")

    t0 = time.time()
    print("  [1/2] Baseline (total_score 정렬)...")
    baseline_result = run_single_backtest(
        label="Baseline",
        params=PARAMS,
        trading_days=trading_days,
        prices_cache=prices_cache,
        portfolio_cache=baseline_cache,
        factors_cache=factors_cache,
        start_norm=start_norm,
        end_norm=end_norm,
    )

    print(f"  [2/2] Two-stage (hybrid_score 정렬)...")
    twostage_result = run_single_backtest(
        label="Two-stage",
        params=PARAMS,
        trading_days=trading_days,
        prices_cache=prices_cache,
        portfolio_cache=twostage_cache,
        factors_cache=factors_cache,
        start_norm=start_norm,
        end_norm=end_norm,
    )
    print(f"  백테스트 완료 ({time.time()-t0:.1f}s)")

    # 5. 비교 출력
    print_comparison(baseline_result, twostage_result)
    print_portfolio_diff(baseline_cache, twostage_cache, trading_days)

    # 6. 포트폴리오 상세 (첫날)
    first_day = trading_days[0].replace('-', '')
    print(f"\n--- Baseline 첫 거래일({trading_days[0]}) 포트폴리오 (total_score 정렬) ---")
    for r in baseline_cache.get(first_day, [])[:10]:
        ts = r.get('timing_score', 0)
        hs = r.get('hybrid_score', 0)
        print(f"  {r['rank']:2d}. {r['stock_code']} {r.get('stock_name',''):<12} "
              f"total={r['total_score']:.1f}  timing={ts:.1f}  hybrid={hs:.1f}")

    print(f"\n--- Two-stage 첫 거래일({trading_days[0]}) 포트폴리오 (hybrid_score 정렬) ---")
    for r in twostage_cache.get(first_day, [])[:10]:
        ts = r.get('timing_score', 0)
        hs = r.get('hybrid_score', 0)
        print(f"  {r['rank']:2d}. {r['stock_code']} {r.get('stock_name',''):<12} "
              f"total={r['total_score']:.1f}  timing={ts:.1f}  hybrid={hs:.1f}")

    print()


if __name__ == '__main__':
    main()
