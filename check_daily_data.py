#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""일봉 데이터 확인"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "data" / "robotrader.db"

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 099440 일봉 데이터 확인
cursor.execute('SELECT COUNT(*) FROM daily_prices WHERE stock_code = ?', ('099440',))
count = cursor.fetchone()[0]
print(f"099440 일봉 데이터 건수: {count}")

if count > 0:
    cursor.execute('SELECT date, open, high, low, close, volume FROM daily_prices WHERE stock_code = ? ORDER BY date DESC LIMIT 10', ('099440',))
    rows = cursor.fetchall()
    print("\n최근 일봉 데이터:")
    for row in rows:
        date, open_price, high, low, close, volume = row
        change = close - open_price
        change_pct = (change / open_price * 100) if open_price > 0 else 0
        candle = "양봉" if change >= 0 else "음봉"
        print(f"  {date}: 시가 {open_price:,.0f} 종가 {close:,.0f} ({change:+,.0f}원, {change_pct:+.2f}%) - {candle}")
else:
    print("일봉 데이터 없음")

conn.close()
