#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""12월 1일 이전 매매 기록 확인"""
import sqlite3
from pathlib import Path
from datetime import datetime

db_path = Path(__file__).parent / "data" / "robotrader.db"

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cutoff_date = "2025-12-01"

print("=" * 100)
print(f"[{cutoff_date} 이전 매매 기록 확인]")
print("=" * 100)

# 매수 기록 확인
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE action = 'BUY' AND is_test = 1 AND DATE(timestamp) < ?
''', (cutoff_date,))
buy_count = cursor.fetchone()[0]

# 매도 기록 확인
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE action = 'SELL' AND is_test = 1 AND DATE(timestamp) < ?
''', (cutoff_date,))
sell_count = cursor.fetchone()[0]

print(f"\n매수 기록: {buy_count}건")
print(f"매도 기록: {sell_count}건")
print(f"총 {buy_count + sell_count}건")

# 날짜별 분포 확인
print("\n[날짜별 분포]")
cursor.execute('''
    SELECT DATE(timestamp) as date, action, COUNT(*) as cnt
    FROM virtual_trading_records
    WHERE is_test = 1 AND DATE(timestamp) < ?
    GROUP BY DATE(timestamp), action
    ORDER BY date DESC
    LIMIT 20
''', (cutoff_date,))

rows = cursor.fetchall()
for row in rows:
    date, action, cnt = row
    print(f"  {date}: {action} {cnt}건")

conn.close()

