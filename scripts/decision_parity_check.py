#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
시뮬 vs 실전 '결정 일치도' 검증 (같은 데이터 기준)

각 실전 포지션(매수~매도)에 대해:
- 실전 매수가, TP/SL 사용 (DB target_profit_rate / stop_loss_rate)
- 시뮬 엔진 규칙(일봉 고가/저가 터치)으로 매도 시점 계산
- 실전 매도일/사유와 비교

결정이 일치해야 엔진이 현실을 올바르게 모사한다고 볼 수 있음.
체결가는 달라도 의사결정은 같아야 함.
"""
import sys
from pathlib import Path

import psycopg2
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.db_config import DB_CONFIG


def load_closed_positions(start: str, end: str) -> pd.DataFrame:
    """실전 청산 포지션 로드 (매수~매도 매칭)"""
    sql = """
        SELECT
          b.id AS buy_id, b.stock_code, b.stock_name,
          b.timestamp AS buy_time, b.price AS buy_price,
          b.target_profit_rate, b.stop_loss_rate,
          s.id AS sell_id, s.timestamp AS sell_time,
          s.price AS sell_price, s.reason AS sell_reason,
          s.profit_loss, s.profit_rate
        FROM real_trading_records b
        JOIN real_trading_records s
          ON s.buy_record_id = b.id AND s.action='SELL'
        WHERE b.action='BUY'
          AND b.timestamp >= %s AND b.timestamp < %s
        ORDER BY b.timestamp
    """
    with psycopg2.connect(**DB_CONFIG) as conn:
        return pd.read_sql_query(sql, conn, params=(start, end))


def load_daily_ohlc(codes: list, start: str, end: str) -> dict:
    """일봉 OHLC를 {code: DataFrame(date→OHLC)}로"""
    with psycopg2.connect(**DB_CONFIG) as conn:
        df = pd.read_sql_query(
            """SELECT stock_code, date, open, high, low, close
               FROM daily_prices
               WHERE stock_code = ANY(%s) AND date >= %s AND date <= %s
               ORDER BY stock_code, date""",
            conn, params=(codes, start, end)
        )
    df['date'] = pd.to_datetime(df['date'])
    return {c: g.set_index('date') for c, g in df.groupby('stock_code')}


def simulate_exit(row, ohlc_by_code):
    """일봉 고가/저가 터치 기반 매도 시점 시뮬레이션

    규칙 (backtest/backtester.py와 동일):
    - buy_date 당일은 TP/SL 차단 (P3)
    - 다음날부터: 고가 >= TP가 → TP, 저가 <= SL가 → SL (동시 히트는 SL 우선)
    - 매도 없으면 기간 말까지 보유
    """
    code = row['stock_code']
    buy_date = pd.Timestamp(row['buy_time']).normalize()
    sell_date_actual = pd.Timestamp(row['sell_time']).normalize()
    buy_price = row['buy_price']
    tp_rate = row['target_profit_rate'] or 0.15
    sl_rate = row['stop_loss_rate'] or 0.08
    tp_price = buy_price * (1 + tp_rate)
    sl_price = buy_price * (1 - sl_rate)

    df = ohlc_by_code.get(code)
    if df is None or df.empty:
        return {'sim_exit_date': None, 'sim_reason': 'NODATA'}

    # buy_date 다음날부터 검사
    mask = (df.index > buy_date)
    future = df[mask]
    if future.empty:
        return {'sim_exit_date': None, 'sim_reason': 'HOLD'}

    for dt, r in future.iterrows():
        hit_sl = r['low'] <= sl_price
        hit_tp = r['high'] >= tp_price
        if hit_sl:
            return {'sim_exit_date': dt, 'sim_reason': 'SL',
                    'tp_price': tp_price, 'sl_price': sl_price}
        if hit_tp:
            return {'sim_exit_date': dt, 'sim_reason': 'TP',
                    'tp_price': tp_price, 'sl_price': sl_price}

    # 미도달 → 기간 말까지 보유 (리밸런싱이나 실전 개입 외)
    return {'sim_exit_date': None, 'sim_reason': 'HOLD',
            'tp_price': tp_price, 'sl_price': sl_price}


def classify_live_reason(reason: str) -> str:
    if pd.isna(reason):
        return 'OTHER'
    if '익절' in reason:
        return 'TP'
    if '손절' in reason:
        return 'SL'
    if '리밸런싱' in reason:
        return 'REBAL'
    if '수동매도' in reason:
        return 'MANUAL'
    if '전쟁' in reason or '긴급' in reason:
        return 'MANUAL'
    return 'OTHER'


def main():
    START = '2026-02-12'
    END = '2026-04-13'

    print(f"실전 청산 포지션 로드: {START} ~ {END}")
    positions = load_closed_positions(START, END)
    print(f"  표본: {len(positions)}건")

    # 일봉은 매수 이전 여유 + 매도 이후 30일
    date_lo = (pd.Timestamp(START) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    date_hi = (pd.Timestamp(END) + pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    codes = positions['stock_code'].unique().tolist()
    print(f"  일봉 로드: {len(codes)}종목, {date_lo} ~ {date_hi}")
    ohlc_by_code = load_daily_ohlc(codes, date_lo, date_hi)

    # 각 포지션 시뮬레이션
    sim_results = positions.apply(lambda r: simulate_exit(r, ohlc_by_code), axis=1)
    positions['sim_exit_date'] = sim_results.apply(lambda x: x.get('sim_exit_date'))
    positions['sim_reason'] = sim_results.apply(lambda x: x.get('sim_reason'))

    # 실전 사유 분류
    positions['live_reason'] = positions['sell_reason'].apply(classify_live_reason)

    # 매도일 차이(일)
    positions['sell_date_live'] = pd.to_datetime(positions['sell_time']).dt.normalize()
    positions['day_gap'] = (positions['sim_exit_date'] - positions['sell_date_live']).dt.days

    # 사유 일치 판정 (수동매도 제외, 리밸런싱/HOLD/OTHER은 따로)
    def is_match(r):
        if r['live_reason'] in ('TP', 'SL') and r['sim_reason'] in ('TP', 'SL'):
            return r['live_reason'] == r['sim_reason']
        return None  # 비교 불가

    positions['reason_match'] = positions.apply(is_match, axis=1).astype('object')

    # 집계
    print("\n" + "=" * 75)
    print("실전 매도 사유 분포")
    print("=" * 75)
    print(positions['live_reason'].value_counts().to_string())

    print("\n" + "=" * 75)
    print("시뮬 결정 분포")
    print("=" * 75)
    print(positions['sim_reason'].value_counts().to_string())

    print("\n" + "=" * 75)
    print("결정 일치도 (실전 TP/SL vs 시뮬 TP/SL)")
    print("=" * 75)
    comp = positions[positions['reason_match'].notna()]
    print(f"  비교 가능 표본: {len(comp)}건")
    if len(comp) > 0:
        match = comp['reason_match'].sum()
        print(f"  일치: {match}/{len(comp)} ({match/len(comp)*100:.1f}%)")
        print("\n  불일치 케이스 (live → sim):")
        mismatch = comp[comp['reason_match'] == False]
        for _, r in mismatch.iterrows():
            print(f"    {r['stock_code']} {r['stock_name'][:10]:<10} "
                  f"buy={r['buy_time'].strftime('%m-%d')} "
                  f"live={r['live_reason']}({r['sell_time'].strftime('%m-%d')}, {r['profit_rate']*100:+.2f}%) "
                  f"sim={r['sim_reason']}({r['sim_exit_date'].strftime('%m-%d') if pd.notna(r['sim_exit_date']) else 'N/A'})")

    # 매도일 차이 (TP/TP, SL/SL 매칭 케이스만)
    both_tp_sl = comp[comp['reason_match'] == True]
    if len(both_tp_sl) > 0:
        print(f"\n  사유 일치 케이스의 매도일 차이(사이ム-실전, 일):")
        print(f"    평균: {both_tp_sl['day_gap'].mean():+.2f}일")
        print(f"    중위: {both_tp_sl['day_gap'].median():+.1f}일")
        print(f"    시뮬이 더 빠름: {(both_tp_sl['day_gap']<0).sum()}건")
        print(f"    같은 날:      {(both_tp_sl['day_gap']==0).sum()}건")
        print(f"    시뮬이 더 늦음: {(both_tp_sl['day_gap']>0).sum()}건")

    # 실전=SL인데 시뮬=HOLD (보유 유지), 실전=TP인데 시뮬=HOLD 등
    print("\n" + "=" * 75)
    print("시뮬 사유별 × 실전 사유 교차표")
    print("=" * 75)
    ct = pd.crosstab(positions['live_reason'], positions['sim_reason'], margins=True)
    print(ct)


if __name__ == "__main__":
    main()
