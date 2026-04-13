#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실전 vs 시뮬 체결가 괴리 실측 (2026-02-27 ~ 2026-03-26)

목적: 백테스트 엔진의 슬리피지/체결 가정이 현실과 얼마나 다른지 확인

비교:
- 매수: 실전 실제 체결가 vs 시뮬 가정가 (시가 × 1.001)
- 매도: 실전 실제 체결가 vs 시뮬 가정가 (목표가+종가)/2 × 0.999
- 수동개입 매도는 제외
"""
import sys
from pathlib import Path

import psycopg2
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.db_config import DB_CONFIG

START = '2026-02-27'
END = '2026-03-27'  # exclusive


def load_live_trades() -> pd.DataFrame:
    """실전 BUY/SELL + 일봉 OHLC 조인"""
    sql = """
        SELECT r.id, r.stock_code, r.action,
               r.price AS exec_price,
               DATE(r.timestamp) AS trade_date,
               r.reason,
               r.target_profit_rate, r.stop_loss_rate,
               r.buy_record_id,
               d.open, d.high, d.low, d.close,
               d.returns_1d
        FROM real_trading_records r
        LEFT JOIN daily_prices d
          ON d.stock_code = r.stock_code
         AND d.date = TO_CHAR(r.timestamp, 'YYYY-MM-DD')
        WHERE r.timestamp >= %s AND r.timestamp < %s
        ORDER BY r.timestamp
    """
    with psycopg2.connect(**DB_CONFIG) as conn:
        df = pd.read_sql_query(sql, conn, params=(START, END))
    return df


def analyze_buys(df: pd.DataFrame):
    """매수 체결가 vs 시뮬 가정가(= open × 1.001) 비교"""
    buys = df[df['action'] == 'BUY'].copy()
    buys = buys.dropna(subset=['open'])  # 일봉 없는 건 제외
    # 시뮬 매수가: 시가 × (1 + 0.001)
    buys['sim_price'] = buys['open'] * 1.001
    buys['gap_pct'] = (buys['exec_price'] - buys['sim_price']) / buys['sim_price'] * 100
    buys['within_day_pct'] = (buys['exec_price'] - buys['open']) / buys['open'] * 100

    print("\n[매수 체결가 비교] (시뮬 가정 = 시가 × 1.001)")
    print(f"  표본: {len(buys)}건")
    print(f"  실전 실제 체결가 vs 시뮬 가정가 괴리(%):")
    print(f"    평균: {buys['gap_pct'].mean():+.3f}%")
    print(f"    중위: {buys['gap_pct'].median():+.3f}%")
    print(f"    p25: {buys['gap_pct'].quantile(0.25):+.3f}%   p75: {buys['gap_pct'].quantile(0.75):+.3f}%")
    print(f"    표준편차: {buys['gap_pct'].std():.3f}%")
    print(f"    범위: [{buys['gap_pct'].min():+.2f}%, {buys['gap_pct'].max():+.2f}%]")
    print(f"\n  실전 체결가가 시가 대비 (within-day):")
    print(f"    평균 위치: {buys['within_day_pct'].mean():+.3f}%  (0이면 시가, +이면 시가 위에서 매수)")
    print(f"    중위: {buys['within_day_pct'].median():+.3f}%")
    return buys


def analyze_sells(df: pd.DataFrame):
    """매도 체결가 vs 시뮬 가정가 비교 (수동매도 제외)"""
    sells_all = df[df['action'] == 'SELL'].copy()
    # 수동개입 제외
    mask_manual = sells_all['reason'].str.contains('수동매도|전쟁 리스크', regex=True, na=False)
    sells = sells_all[~mask_manual].dropna(subset=['high', 'low', 'close']).copy()

    # 시뮬 가정가 (P2 + slippage):
    # - 익절: (목표가 + 종가) / 2 × 0.999, 여기서 목표가 = buy_price × (1 + target_profit_rate)
    # - 손절: (손절가 + 종가) / 2 × 0.999
    # 매수가가 필요 → buy_record_id 조인
    sells = sells.dropna(subset=['buy_record_id']).copy()
    sells['buy_record_id'] = sells['buy_record_id'].astype(int)

    with psycopg2.connect(**DB_CONFIG) as conn:
        buys_df = pd.read_sql_query(
            "SELECT id, price AS buy_price FROM real_trading_records WHERE id = ANY(%s)",
            conn, params=(sells['buy_record_id'].tolist(),)
        )
    sells = sells.merge(buys_df, left_on='buy_record_id', right_on='id', suffixes=('', '_buy'))

    # 분류
    sells['is_tp'] = sells['reason'].str.contains('익절', na=False)
    sells['is_sl'] = sells['reason'].str.contains('손절', na=False)

    def sim_price(row):
        if row['is_tp']:
            tp_rate = row['target_profit_rate'] if pd.notna(row['target_profit_rate']) else 0.15
            target = row['buy_price'] * (1 + tp_rate)
            return (target + row['close']) / 2 * 0.999
        elif row['is_sl']:
            sl_rate = row['stop_loss_rate'] if pd.notna(row['stop_loss_rate']) else 0.08
            stop = row['buy_price'] * (1 - sl_rate)
            return (stop + row['close']) / 2 * 0.999
        else:
            return row['close'] * 0.999  # 리밸런싱 매도

    sells['sim_price'] = sells.apply(sim_price, axis=1)
    sells['gap_pct'] = (sells['exec_price'] - sells['sim_price']) / sells['sim_price'] * 100

    print("\n[매도 체결가 비교] (수동매도·전쟁 제외)")
    print(f"  표본: {len(sells)}건 (TP: {sells['is_tp'].sum()}, SL: {sells['is_sl'].sum()}, 리밸/기타: {(~sells['is_tp'] & ~sells['is_sl']).sum()})")
    print(f"  실전 실제 체결가 vs 시뮬 가정가 괴리(%):")
    print(f"    평균: {sells['gap_pct'].mean():+.3f}%")
    print(f"    중위: {sells['gap_pct'].median():+.3f}%")
    print(f"    표준편차: {sells['gap_pct'].std():.3f}%")

    for kind, m in [('TP', sells['is_tp']), ('SL', sells['is_sl'])]:
        sub = sells[m]
        if len(sub) == 0:
            continue
        print(f"\n  [{kind} 전용, n={len(sub)}]")
        print(f"    평균 괴리: {sub['gap_pct'].mean():+.3f}%  중위 {sub['gap_pct'].median():+.3f}%  std {sub['gap_pct'].std():.3f}%")
        print(f"    실전 실제 체결가/매수가 = {(sub['exec_price']/sub['buy_price']).mean():.4f} (평균 실현 수익률)")
        print(f"    시뮬 가정 체결가/매수가 = {(sub['sim_price']/sub['buy_price']).mean():.4f}")

    return sells


def main():
    print("=" * 75)
    print("실전 vs 시뮬 체결가 괴리 실측")
    print(f"기간: {START} ~ {END} (exclusive)")
    print("=" * 75)

    df = load_live_trades()
    print(f"\n전체 실전 레코드: {len(df)}건")
    print(f"  BUY: {(df['action']=='BUY').sum()}, SELL: {(df['action']=='SELL').sum()}")

    buys = analyze_buys(df)
    sells = analyze_sells(df)

    # 종합 슬리피지 추정
    print("\n" + "=" * 75)
    print("[종합 해석]")
    buy_slip = buys['gap_pct'].mean() / 100
    sell_slip = sells['gap_pct'].mean() / 100
    print(f"  현재 엔진 가정: 매수 +0.10%, 매도 -0.10% (일봉 OHLC 기반)")
    print(f"  실측 괴리:       매수 {buy_slip*100:+.3f}%, 매도 {sell_slip*100:+.3f}%")
    total_gap = abs(buy_slip) + abs(sell_slip)
    print(f"  왕복 괴리(절대값 합): {total_gap*100:.3f}% per trade")
    print(f"  건당 금액 영향 (평균 거래금액 100만원 가정): {total_gap*1_000_000:,.0f}원/건")


if __name__ == "__main__":
    main()
