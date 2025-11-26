#!/usr/bin/env python3
"""ML 테이블 존재 여부 확인"""
import sqlite3
from pathlib import Path

db_path = Path("data/robotrader.db")

if not db_path.exists():
    print(f"데이터베이스 파일을 찾을 수 없습니다: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 테이블 확인
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('daily_prices', 'financial_statements')")
tables = cursor.fetchall()

print("ML 테이블 존재 여부:")
if tables:
    for table in tables:
        print(f"  {table[0]}: 존재")
        
        # 테이블 구조 확인
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        print(f"    컬럼 수: {len(columns)}")
else:
    print("  daily_prices: 없음")
    print("  financial_statements: 없음")
    print("\n[주의] 테이블이 없습니다. 시스템을 재시작하면 자동으로 생성됩니다.")

conn.close()




