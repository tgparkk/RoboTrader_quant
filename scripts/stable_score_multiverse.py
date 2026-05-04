#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
'천천히 변하는 종합 점수' 멀티버스

기존 V100(value_score 단독) 대비, 다중 데이터를 조합한 stable_score 테스트.
모든 구성요소는 본질적으로 천천히 변하는 지표만 사용:
  - Value (분기 재무)
  - Quality (분기 재무)
  - 외국인 보유율 레벨
  - 60일 변동성 (스무딩됨)
  - 60일 평균 시가총액

거래수(턴오버) 증가 여부를 핵심 지표로 측정.
결과: 천만원 기준 수익·KOSPI 대비 차액·거래수.
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
import psycopg2

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from config.db_config import BACKTEST_DB_CONFIG


PERIODS = [
    ("2024-04~2025-06 (15개월)", "2024-04-01", "2025-06-30"),
    ("2025-07~2026-04 (9개월)",  "2025-07-01", "2026-04-09"),
    ("전체 2년",                 "2024-04-01", "2026-04-09"),
]


def common_params(**ov):
    base = dict(
        initial_capital=10_000_000,     # 1,000만원 기준
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
# 외부 지표 로드 (외국인 보유율, 시가총액, 변동성)
# ═══════════════════════════════════════════════════════════════
def load_slow_features(start_date="2023-01-01", end_date="2026-04-09"):
    """
    각 (stock_code, date)별 천천히 변하는 지표들 로드.
    반환: dict {(code, yyyymmdd): {'foreign_level': x, 'size': x, 'vol60d': x}}
    """
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        # 외국인 보유율
        inv_df = pd.read_sql_query(
            """SELECT stock_code, date, foreign_holding_pct
               FROM investor_flow WHERE date >= %s AND date <= %s""",
            conn, params=(start_date.replace("-", ""), end_date.replace("-", ""))
        )
        # 시가총액 + 가격(변동성 계산용)
        dp_df = pd.read_sql_query(
            """SELECT stock_code, date::text AS date, close, market_cap, volatility_20d
               FROM daily_prices
               WHERE date >= %s AND date <= %s
               AND stock_code NOT IN ('KS11', 'KQ11')
               ORDER BY stock_code, date""",
            conn, params=(start_date, end_date)
        )

    # 외국인 보유율 맵
    foreign_map = {}
    for row in inv_df.itertuples(index=False):
        if pd.notna(row.foreign_holding_pct):
            foreign_map[(row.stock_code, row.date)] = float(row.foreign_holding_pct)

    # 종목별 60일 변동성, 시가총액 맵
    slow_feats = {}
    for code, g in dp_df.groupby('stock_code'):
        g = g.sort_values('date').reset_index(drop=True)
        closes = g['close'].values.astype(float)
        mcaps = g['market_cap'].values
        dates = g['date'].values

        for idx in range(1, len(g)):
            prev = idx - 1
            d = dates[idx]
            ymd = d.replace("-", "")
            feat = {}

            # 60일 변동성 (D-1 이전 60일)
            if prev >= 60:
                window = closes[prev - 60:prev + 1]
                if np.all(window > 0):
                    daily_ret = np.diff(window) / window[:-1]
                    if len(daily_ret) > 0 and daily_ret.std() > 0:
                        feat['vol60d'] = float(np.std(daily_ret) * np.sqrt(252))

            # 60일 평균 시가총액
            if prev >= 60:
                mc_window = mcaps[prev - 60:prev + 1]
                valid_mc = mc_window[~pd.isna(mc_window)]
                if len(valid_mc) >= 30:
                    feat['size'] = float(np.mean(valid_mc))

            # 외국인 보유율 (D-1 기준)
            prev_ymd = str(dates[prev]).replace("-", "")
            fh = foreign_map.get((code, prev_ymd))
            if fh is not None:
                feat['foreign_level'] = fh

            if feat:
                slow_feats[(code, ymd)] = feat
    return slow_feats


# ═══════════════════════════════════════════════════════════════
# 횡단면 백분위 정규화 (0-100)
# ═══════════════════════════════════════════════════════════════
def percentile_rank(values_by_date):
    """
    values_by_date: {yyyymmdd: {code: value}}
    반환: {yyyymmdd: {code: percentile_0_100}}
    """
    out = {}
    for d, stocks in values_by_date.items():
        valid = [(c, v) for c, v in stocks.items() if v is not None]
        if len(valid) < 5:
            out[d] = {}
            continue
        valid.sort(key=lambda x: x[1])
        n = len(valid)
        out[d] = {c: (i / max(1, n - 1)) * 100 for i, (c, _) in enumerate(valid)}
    return out


# ═══════════════════════════════════════════════════════════════
# stable_score 계산 + factors_cache 재구성
# ═══════════════════════════════════════════════════════════════
def build_stable_cache(saved_factors, slow_feats, weights, portfolio_top_n=50,
                       smoothing_days=0):
    """
    weights: dict {'value': x, 'quality': x, 'foreign': x, 'low_vol': x, 'size': x}
              합 1.0 권장
    smoothing_days: 0 = 스무딩 없음, N>0 = N일 이동평균
    """
    # 1) 각 구성요소별 (date → code → value) 수집
    value_by_date = defaultdict(dict)
    quality_by_date = defaultdict(dict)
    foreign_by_date = defaultdict(dict)
    vol_by_date = defaultdict(dict)       # 값은 낮을수록 좋음
    size_by_date = defaultdict(dict)

    for calc_date, stocks in saved_factors.items():
        for code, f in stocks.items():
            value_by_date[calc_date][code] = f.get('value_score', 0)
            quality_by_date[calc_date][code] = f.get('quality_score', 0)
            # 외부 피처
            slow = slow_feats.get((code, calc_date), {})
            if 'foreign_level' in slow:
                foreign_by_date[calc_date][code] = slow['foreign_level']
            if 'vol60d' in slow:
                vol_by_date[calc_date][code] = slow['vol60d']
            if 'size' in slow:
                size_by_date[calc_date][code] = slow['size']

    # 2) Value와 Quality는 raw 점수 유지 (저턴오버 보존)
    # 외국인·변동성·시총만 percentile 정규화 (단위가 달라 필요)
    foreign_pct = percentile_rank(foreign_by_date)
    vol_pct = percentile_rank(vol_by_date)   # 낮은 변동성 종목이 상위 백분위
    size_pct = percentile_rank(size_by_date)

    # 3) 종합 점수 계산 (각 날짜)
    # Value/Quality raw (0-100 절대) + 보조 지표 percentile (0-100 상대)
    raw_scores = {}
    for calc_date in saved_factors:
        codes = set(saved_factors[calc_date].keys())
        day_scores = {}
        for code in codes:
            # Raw 점수 (천천히 변함)
            v_raw = value_by_date.get(calc_date, {}).get(code, 50.0)
            q_raw = quality_by_date.get(calc_date, {}).get(code, 50.0)

            # Percentile 정규화 (단위 통일용)
            f = foreign_pct.get(calc_date, {}).get(code)
            vol = vol_pct.get(calc_date, {}).get(code)
            s = size_pct.get(calc_date, {}).get(code)
            f = f if f is not None else 50.0
            vol = vol if vol is not None else 50.0
            s = s if s is not None else 50.0

            score = (
                v_raw * weights.get('value', 0) +
                q_raw * weights.get('quality', 0) +
                f * weights.get('foreign', 0) +
                (100 - vol) * weights.get('low_vol', 0) +   # 저변동성 가점
                s * weights.get('size', 0)
            )
            day_scores[code] = score
        raw_scores[calc_date] = day_scores

    # 4) 스무딩 (선택적)
    if smoothing_days > 0:
        sorted_dates = sorted(raw_scores.keys())
        smoothed = {}
        for i, d in enumerate(sorted_dates):
            start_idx = max(0, i - smoothing_days + 1)
            window_dates = sorted_dates[start_idx:i + 1]
            day_smooth = {}
            codes = set()
            for wd in window_dates:
                codes.update(raw_scores[wd].keys())
            for code in codes:
                vals = [raw_scores[wd].get(code) for wd in window_dates]
                vals = [v for v in vals if v is not None]
                if vals:
                    day_smooth[code] = sum(vals) / len(vals)
            smoothed[d] = day_smooth
        raw_scores = smoothed

    # 5) factors_cache 재구성
    new_factors = {}
    new_portfolio = {}
    stock_names = {}

    for calc_date, stocks in saved_factors.items():
        day_score = raw_scores.get(calc_date, {})
        scored = []
        new_stocks = {}
        for code, f in stocks.items():
            new_total = day_score.get(code, 0)
            nf = dict(f)
            nf['total_score'] = new_total
            nf['factor_rank'] = 0
            new_stocks[code] = nf
            scored.append((code, new_total))
            if 'stock_name' in f:
                stock_names[code] = f.get('stock_name', code)

        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(scored, 1):
            new_stocks[code]['factor_rank'] = rank
        new_factors[calc_date] = new_stocks

        port = []
        for rank, (code, tscore) in enumerate(scored[:portfolio_top_n], 1):
            port.append({
                'calc_date': calc_date, 'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'rank': rank, 'total_score': tscore,
                'reason': f'stable {tscore:.1f}',
            })
        new_portfolio[calc_date] = port
    return new_factors, new_portfolio


# ═══════════════════════════════════════════════════════════════
# 백테스트 실행 (공통)
# ═══════════════════════════════════════════════════════════════
def run_bt(start, end, factors, portfolio, prices, params):
    bt = Backtester(params=params)
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
    """천만원 기준 KOSPI 수익"""
    df = prices.get('KS11')
    out = {}
    if df is None:
        return out
    for tag, s, e in PERIODS:
        sub = df.loc[s:e]
        if len(sub) >= 2:
            ratio = float(sub.iloc[-1]['close']) / float(sub.iloc[0]['close'])
            out[tag] = {
                'return_pct': ratio - 1,
                'final': initial * ratio,
                'profit': initial * (ratio - 1),
            }
    return out


# ═══════════════════════════════════════════════════════════════
# 시나리오 정의
# ═══════════════════════════════════════════════════════════════
SCENARIOS = [
    # (label, weights, smoothing_days)
    ("V100 (현행 baseline)",        {'value': 1.0}, 0),
    ("A: V40/외20/저변15/Q15/크기10", {'value': 0.40, 'foreign': 0.20, 'low_vol': 0.15, 'quality': 0.15, 'size': 0.10}, 0),
    ("B: V50/외20/Q20/크기10",        {'value': 0.50, 'foreign': 0.20, 'quality': 0.20, 'size': 0.10}, 0),
    ("C: V30/외30/Q20/저변20",        {'value': 0.30, 'foreign': 0.30, 'quality': 0.20, 'low_vol': 0.20}, 0),
    ("D: V60/저변20/Q20",             {'value': 0.60, 'low_vol': 0.20, 'quality': 0.20}, 0),
    ("E: V50/Q50",                    {'value': 0.50, 'quality': 0.50}, 0),
    ("F: V70/외30",                   {'value': 0.70, 'foreign': 0.30}, 0),
    ("G: V70/저변30",                 {'value': 0.70, 'low_vol': 0.30}, 0),
    ("H: V50/저변25/Q25",             {'value': 0.50, 'low_vol': 0.25, 'quality': 0.25}, 0),
]


def main():
    log_lines = []
    def emit(s=""):
        print(s, flush=True)
        log_lines.append(s)

    emit("=" * 130)
    emit("  Stable Score 멀티버스: 천천히 변하는 종합 점수 조합 테스트")
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
    emit(f"  {time.time()-t0:.1f}초, {len(days)}거래일, {len(prices)}종목")

    print("\n[2/3] 외부 지표 로드 (외국인/시총/60일변동성)...", flush=True)
    t1 = time.time()
    slow_feats = load_slow_features("2023-01-01", "2026-04-09")
    emit(f"  {time.time()-t1:.1f}초, {len(slow_feats):,}건")

    k = kospi_returns_money(prices)
    emit("")
    emit("[KOSPI B&H - 천만원 기준]")
    for tag, s, e in PERIODS:
        r = k.get(tag)
        if r:
            emit(f"  {tag:<28}  1,000만 → {r['final']/10000:,.0f}만 ({r['return_pct']:+.1%})")

    print("\n[3/3] 시나리오 백테스트...", flush=True)
    t2 = time.time()

    emit("")
    emit("=" * 130)
    emit(f"{'시나리오':<32} | {'구간':<28} | {'최종자산':>12} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    emit("-" * 130)

    results = []
    for label, weights, smooth in SCENARIOS:
        t_start = time.time()
        fc, pc = build_stable_cache(saved_factors, slow_feats, weights, smoothing_days=smooth)

        row = {'label': label, 'weights': weights}
        for tag, s, e in PERIODS:
            r = run_bt(s, e, fc, pc, prices, common_params())
            row[tag] = r
            k_prof = k.get(tag, {}).get('profit', 0)
            strategy_profit = r.final_total_value - 10_000_000
            diff = strategy_profit - k_prof
            emit(f"{label:<32} | {tag:<28} | {r.final_total_value/10000:>10,.0f}만 | "
                  f"{strategy_profit/10000:>+8,.0f}만 | {r.total_return:>+7.1%} | "
                  f"{diff/10000:>+8,.0f}만 | {r.total_trades:>6d}")
        emit("")
        results.append(row)

    emit(f"총 {time.time()-t2:.1f}초")

    # 정렬: 전체 2년 수익률 순
    emit("")
    emit("=" * 130)
    emit("전체 2년 기준 순위 (KOSPI +121.4% 기준)")
    emit("=" * 130)
    k_all_profit = k.get("전체 2년", {}).get('profit', 0)
    sorted_res = sorted(results, key=lambda r: r["전체 2년"].total_return, reverse=True)
    emit(f"{'순위':>4} {'시나리오':<32} | {'최종':>10} | {'수익':>10} | {'수익률':>8} | {'KOSPI차':>10} | {'거래수':>6}")
    for i, r in enumerate(sorted_res, 1):
        res = r["전체 2년"]
        profit = res.final_total_value - 10_000_000
        diff = profit - k_all_profit
        marker = " ★" if "baseline" in r['label'] else ""
        emit(f"{i:>4} {r['label']:<32}{marker} | {res.final_total_value/10000:>8,.0f}만 | "
              f"{profit/10000:>+8,.0f}만 | {res.total_return:>+7.1%} | {diff/10000:>+8,.0f}만 | {res.total_trades:>6d}")

    out = Path("results/stable_score_multiverse.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == '__main__':
    main()
