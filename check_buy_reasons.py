#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매수 사유 확인"""
import sqlite3
import pandas as pd
from pathlib import Path

db_path = Path(__file__).parent / "data" / "robotrader.db"

conn = sqlite3.connect(str(db_path))

print("=" * 100)
print("[12월 9일~12일 매수 종목의 매수 사유 확인]")
print("=" * 100)

# 목표 익절/손절률이 없는 종목들의 매수 기록 확인
query = '''
SELECT 
    stock_code,
    stock_name,
    DATE(timestamp) as buy_date,
    strategy,
    reason,
    target_profit_rate,
    stop_loss_rate
FROM virtual_trading_records
WHERE action = 'BUY' 
    AND is_test = 1
    AND DATE(timestamp) BETWEEN '2025-12-09' AND '2025-12-12'
    AND (target_profit_rate IS NULL OR stop_loss_rate IS NULL)
ORDER BY timestamp DESC
'''

df = pd.read_sql_query(query, conn)

if df.empty:
    print("해당 기간 매수 기록이 없습니다.")
else:
    print(f"\n총 {len(df)}건의 매수 기록")
    print(f"{'종목코드':<10} {'종목명':<20} {'매수일':<12} {'전략':<20} {'사유':<30} {'익절률':<10} {'손절률':<10}")
    print("-" * 100)
    for idx, row in df.iterrows():
        profit_rate = f"{row['target_profit_rate']*100:.1f}%" if row['target_profit_rate'] else "미설정"
        loss_rate = f"{row['stop_loss_rate']*100:.1f}%" if row['stop_loss_rate'] else "미설정"
        print(f"{row['stock_code']:<10} {row['stock_name']:<20} {row['buy_date']:<12} "
              f"{str(row['strategy']):<20} {str(row['reason']):<30} {profit_rate:<10} {loss_rate:<10}")

# 리밸런싱 매수 기록 확인
print("\n[리밸런싱 매수 기록 (12월 9일~12일)]")
print("-" * 100)

query_rebalancing = '''
SELECT 
    stock_code,
    stock_name,
    DATE(timestamp) as buy_date,
    strategy,
    reason,
    target_profit_rate,
    stop_loss_rate
FROM virtual_trading_records
WHERE action = 'BUY' 
    AND is_test = 1
    AND DATE(timestamp) BETWEEN '2025-12-09' AND '2025-12-12'
    AND (strategy LIKE '%리밸런싱%' OR reason LIKE '%리밸런싱%')
ORDER BY timestamp DESC
'''

df_rebalancing = pd.read_sql_query(query_rebalancing, conn)

if df_rebalancing.empty:
    print("리밸런싱 매수 기록이 없습니다.")
else:
    print(f"\n리밸런싱 매수 기록: {len(df_rebalancing)}건")
    with_rate = df_rebalancing[df_rebalancing['target_profit_rate'].notna()]
    without_rate = df_rebalancing[df_rebalancing['target_profit_rate'].isna()]
    
    print(f"목표 익절/손절률 설정: {len(with_rate)}건")
    print(f"목표 익절/손절률 미설정: {len(without_rate)}건")
    
    if len(without_rate) > 0:
        print("\n목표 익절/손절률이 미설정된 리밸런싱 매수 기록:")
        for idx, row in without_rate.iterrows():
            print(f"  {row['stock_code']} ({row['stock_name']}) - {row['buy_date']} - {row['reason']}")

conn.close()

print("\n" + "=" * 100)

