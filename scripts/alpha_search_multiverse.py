#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
알파 탐색 멀티버스 — look-ahead 제거된 clean 팩터 위에서 진짜 알파 찾기

탐색 축:
  1. KOSPI Buy&Hold        (시장 베이스라인)
  2. 현행 (V25/M30/Q22.5/G22.5)  (우리 전략의 clean 버전)
  3. 단일 팩터 (V/M/Q/G/Timing 각 100%)  (어느 팩터에 알파가?)
  4. 팩터 역전 (하위 매수)  (전략 방향이 뒤집혀 있는지)
  5. 랜덤 10종목           (운 vs 스킬)

기간:
  - IS : 2024-04-01 ~ 2025-06-30
  - OOS: 2025-07-01 ~ 2026-04-09
  - ALL: 2024-04-01 ~ 2026-04-09
"""
import sys
import time
import logging
import random
from pathlib import Path
from copy import deepcopy

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import BACKTEST_DB_CONFIG


PERIODS = [
    ("IS ",  "2024-04-01", "2025-06-30"),
    ("OOS",  "2025-07-01", "2026-04-09"),
    ("ALL",  "2024-04-01", "2026-04-09"),
]


def common_params(**overrides):
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
    base.update(overrides)
    return BacktestParams(**base)


# ────────────────────────────────────────────────────────────
# 캐시 재구성: 개별 팩터 가중치로 factor_rank / portfolio 재계산
# ────────────────────────────────────────────────────────────
def rebuild_caches(saved_factors, saved_portfolio, weights, reverse=False,
                   portfolio_top_n=50):
    """
    weights = (v, m, q, g, timing)  (합=1.0 권장, 엄격 강제 X)
    reverse=True 면 하위 종목을 포트폴리오 상위로 (역전 테스트)
    """
    # stock name lookup
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])

    v_w, m_w, q_w, g_w, t_w = weights
    new_factors = {}
    new_portfolio = {}
    for calc_date, stocks in saved_factors.items():
        new_stocks = {}
        scored = []
        for code, f in stocks.items():
            # timing_score는 DB에 없으면 fallback으로 0
            new_total = (
                f.get('value_score', 50) * v_w +
                f.get('momentum_score', 50) * m_w +
                f.get('quality_score', 50) * q_w +
                f.get('growth_score', 50) * g_w
            )
            # timing 가중치: factor_details가 없으므로 total_score를 재사용하거나 skip
            # 간단히 t_w 무시 (추후 필요 시 개별 구현)
            new_f = dict(f)
            new_f['total_score'] = new_total
            new_f['factor_rank'] = 0
            new_stocks[code] = new_f
            scored.append((code, new_total))

        scored.sort(key=lambda x: x[1], reverse=(not reverse))
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks

        port = []
        for rank, (code, tscore) in enumerate(scored[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': tscore,
                'reason': f'w{weights} score {tscore:.1f}',
            })
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


def rebuild_random(saved_factors, saved_portfolio, seed=42, portfolio_top_n=50):
    """랜덤 10종목 (매일 다른 순서)"""
    stock_names = {}
    for port in saved_portfolio.values():
        for it in port:
            stock_names[it['stock_code']] = it.get('stock_name', it['stock_code'])

    rng = random.Random(seed)
    new_factors = {}
    new_portfolio = {}
    for calc_date, stocks in saved_factors.items():
        codes = list(stocks.keys())
        rng.shuffle(codes)
        new_stocks = {}
        for rank, code in enumerate(codes, 1):
            f = dict(stocks[code])
            # buy_min_score=65를 우회하기 위해 total_score를 항상 70으로 (필터 통과)
            f['total_score'] = 70.0
            f['factor_rank'] = rank
            new_stocks[code] = f
        new_factors[calc_date] = new_stocks

        port = []
        for rank, code in enumerate(codes[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': 70.0, 'reason': 'random',
            })
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


def run_bt(scenario_name, start, end, factors, portfolio, prices, params):
    """
    _preload_data()가 주입 캐시를 덮어쓰지 않도록, bt.backtest() 대신
    수동 시뮬레이션 루프 실행 (factor_weight_multiverse.py와 동일 패턴).
    """
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = prices
    bt.portfolio_cache = portfolio
    bt.factors_cache = factors
    bt.capital = params.initial_capital

    start_norm = bt._normalize_date(start)
    end_norm = bt._normalize_date(end)

    # 거래일은 factors_cache 기반으로 추출 (DB 재조회 회피)
    cached_dates = sorted(factors.keys())  # yyyymmdd
    s_ymd = start_norm.replace("-", "")
    e_ymd = end_norm.replace("-", "")
    trading_days = []
    for ymd in cached_dates:
        if s_ymd <= ymd <= e_ymd:
            trading_days.append(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")

    if not trading_days:
        return None

    logging.disable(logging.CRITICAL)
    try:
        prev_total = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)

            total = bt._calculate_total_value(date)
            daily_ret = (total - prev_total) / prev_total if prev_total > 0 else 0
            cum = (total - params.initial_capital) / params.initial_capital
            bt.daily_snapshots.append(DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total - bt.capital,
                total_value=total, position_count=len(bt.positions),
                daily_return=daily_ret, cumulative_return=cum,
            ))
            prev_total = total

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))
    finally:
        logging.disable(logging.NOTSET)
    return result


def kospi_buy_hold(prices, start, end):
    df = prices.get('KS11')
    if df is None:
        return None
    sub = df.loc[start:end]
    if len(sub) < 2:
        return None
    ret = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close']) - 1
    # 일별 수익률 → 샤프
    import numpy as np
    closes = sub['close'].astype(float).values
    dr = np.diff(closes) / closes[:-1]
    sharpe = (np.mean(dr) / np.std(dr) * np.sqrt(252)) if np.std(dr) > 0 else 0.0
    # MDD
    cum = (1 + dr).cumprod()
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = abs(dd.min())
    return {
        'total_return': ret,
        'sharpe': sharpe,
        'mdd': mdd,
    }


SCENARIOS = [
    # (label, kind, arg)  kind: 'weight' | 'reverse' | 'random'
    ("현행 V25/M30/Q22.5/G22.5",  'weight',  (0.25, 0.30, 0.225, 0.225, 0)),
    ("Value only (100%)",          'weight',  (1.0, 0.0, 0.0, 0.0, 0)),
    ("Momentum only",              'weight',  (0.0, 1.0, 0.0, 0.0, 0)),
    ("Quality only",               'weight',  (0.0, 0.0, 1.0, 0.0, 0)),
    ("Growth only",                'weight',  (0.0, 0.0, 0.0, 1.0, 0)),
    ("역전 V25/M30/Q22.5/G22.5",   'reverse', (0.25, 0.30, 0.225, 0.225, 0)),
    ("Random (seed=42)",           'random',  42),
]


def main():
    results_log = []  # 결과 수집

    def emit(s):
        print(s)
        results_log.append(s)

    emit("=" * 110)
    emit("  알파 탐색 멀티버스 (clean 팩터, IS/OOS 분할)")
    emit("=" * 110)

    print("\n데이터 로딩...")
    t0 = time.time()
    loader = Backtester(params=common_params())
    start_norm = loader._normalize_date("2024-04-01")
    end_norm = loader._normalize_date("2026-04-09")
    days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(days)
    prices = loader.daily_prices_cache
    saved_factors = loader.factors_cache
    saved_portfolio = loader.portfolio_cache
    emit(f"로드 {time.time()-t0:.1f}초, {len(days)}거래일, {len(saved_factors)}일 팩터, {len(prices)}종목\n")

    # KOSPI 벤치마크
    kospi_rows = []
    for tag, s, e in PERIODS:
        r = kospi_buy_hold(prices, s, e)
        if r:
            kospi_rows.append((tag, r))

    emit("=" * 110)
    emit(f"{'Scenario':<38} {'Period':<4} {'Return':>9} {'Sharpe':>8} {'MDD':>7} {'Trades':>7} {'WinR':>6}")
    emit("-" * 110)
    # KOSPI
    for tag, r in kospi_rows:
        emit(f"{'KOSPI Buy&Hold':<38} {tag:<4} {r['total_return']:>8.1%} {r['sharpe']:>8.2f} {r['mdd']:>6.1%} {'-':>7} {'-':>6}")
    emit("")

    # 각 시나리오
    for label, kind, arg in SCENARIOS:
        # 캐시 재구성
        if kind == 'weight':
            f_cache, p_cache = rebuild_caches(saved_factors, saved_portfolio, arg, reverse=False)
        elif kind == 'reverse':
            f_cache, p_cache = rebuild_caches(saved_factors, saved_portfolio, arg, reverse=True)
        elif kind == 'random':
            f_cache, p_cache = rebuild_random(saved_factors, saved_portfolio, seed=arg)

        # 역전/랜덤은 buy_min_score 낮추기
        if kind == 'reverse':
            params = common_params(buy_min_score=0.0)  # 점수 기준 없이 상위 매수
        elif kind == 'random':
            params = common_params(buy_min_score=0.0, hard_stop_score=0.0,
                                    soft_stop_score=0.0, safe_score=999.0)
        else:
            params = common_params()

        for tag, s, e in PERIODS:
            s_n = loader._normalize_date(s)
            e_n = loader._normalize_date(e)
            r = run_bt(label, s_n, e_n, f_cache, p_cache, prices, params)
            emit(f"{label:<38} {tag:<4} {r.total_return:>8.1%} {r.sharpe_ratio:>8.2f} "
                  f"{r.max_drawdown:>6.1%} {r.total_trades:>7d} {r.win_rate:>5.1%}")

        emit("")

    emit("=" * 110)

    # 결과 파일로 저장 (encoding 문제 회피)
    from pathlib import Path
    out = Path("results/alpha_search.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(results_log), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
