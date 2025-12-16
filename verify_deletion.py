#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""삭제 확인"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "data" / "robotrader.db"

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

print("=" * 100)
print("[삭제 확인]")
print("=" * 100)

# 12월 1일 이전 기록 확인
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE is_test = 1 AND DATE(timestamp) < '2025-12-01'
''')
old_count = cursor.fetchone()[0]

print(f"\n12월 1일 이전 기록: {old_count}건 (0이어야 함)")

# 전체 기록 수
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE is_test = 1
''')
total_count = cursor.fetchone()[0]

print(f"전체 가상 매매 기록: {total_count}건")

# 보유 종목 수 확인
cursor.execute('''
    SELECT 
        buy.stock_code,
        SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty
    FROM virtual_trading_records buy
    LEFT JOIN virtual_trading_records sell 
        ON buy.id = sell.buy_record_id AND sell.action = 'SELL'
    WHERE buy.action = 'BUY' AND buy.is_test = 1
    GROUP BY buy.stock_code
    HAVING holding_qty > 0
''')
holdings = cursor.fetchall()

print(f"\n보유 종목 수: {len(holdings)}개")

# 099440 종목 확인
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE stock_code = '099440' AND is_test = 1
''')
stock_099440_count = cursor.fetchone()[0]

print(f"\n099440(스맥) 기록: {stock_099440_count}건 (0이어야 함)")

conn.close()

print("\n" + "=" * 100)

