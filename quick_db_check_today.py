#!/usr/bin/env python3
"""데이터베이스 빠른 확인"""
import sqlite3
from pathlib import Path

db_path = Path("data/robotrader.db")

if not db_path.exists():
    print(f"데이터베이스 파일을 찾을 수 없습니다: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 전체 레코드 수
cursor.execute('SELECT COUNT(*) FROM candidate_stocks')
total = cursor.fetchone()[0]
print(f"전체 candidate_stocks 레코드 수: {total}")

# 최근 10일간 데이터
cursor.execute('''
    SELECT DATE(selection_date) as date, COUNT(*) as cnt 
    FROM candidate_stocks 
    GROUP BY DATE(selection_date) 
    ORDER BY date DESC 
    LIMIT 10
''')
rows = cursor.fetchall()
print("\n최근 10일간 데이터:")
for row in rows:
    print(f"  {row[0]}: {row[1]}개")

# 가장 최근 날짜의 종목들
if rows:
    latest_date = rows[0][0]
    print(f"\n가장 최근 날짜 ({latest_date})의 종목들:")
    cursor.execute('''
        SELECT stock_code, stock_name, score
        FROM candidate_stocks
        WHERE DATE(selection_date) = ?
        ORDER BY score DESC
        LIMIT 10
    ''', (latest_date,))
    stocks = cursor.fetchall()
    for stock in stocks:
        print(f"  {stock[0]}: {stock[1]} (점수: {stock[2]})")

conn.close()


