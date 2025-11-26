#!/usr/bin/env python3
"""오늘 날짜 데이터베이스 확인"""
import sqlite3
from pathlib import Path

db_path = Path("data/robotrader.db")

if not db_path.exists():
    print(f"데이터베이스 파일을 찾을 수 없습니다: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 오늘 날짜의 후보 종목 확인
cursor.execute('''
    SELECT stock_code, stock_name, selection_date, score, reasons
    FROM candidate_stocks
    WHERE DATE(selection_date) = '2025-11-21'
    ORDER BY score DESC
''')
rows = cursor.fetchall()

print(f"오늘(2025-11-21) 날짜의 후보 종목: {len(rows)}개\n")

if rows:
    for row in rows:
        print(f"  {row[0]}: {row[1]}")
        print(f"    점수: {row[3]}, 날짜: {row[2]}")
        print(f"    이유: {row[4]}")
        print()
else:
    print("  후보 종목이 없습니다.")

conn.close()


