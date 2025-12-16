#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""12월 1일 이전 매매 기록 삭제"""
import sqlite3
from pathlib import Path
from datetime import datetime

db_path = Path(__file__).parent / "data" / "robotrader.db"

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cutoff_date = "2025-12-01"

print("=" * 100)
print(f"[{cutoff_date} 이전 매매 기록 삭제]")
print("=" * 100)

# 삭제 전 확인
cursor.execute('''
    SELECT COUNT(*) FROM virtual_trading_records 
    WHERE is_test = 1 AND DATE(timestamp) < ?
''', (cutoff_date,))
total_count = cursor.fetchone()[0]

print(f"\n삭제 대상: {total_count}건")

if total_count == 0:
    print("삭제할 기록이 없습니다.")
    conn.close()
    exit(0)

# 사용자 확인
print(f"\n경고: {cutoff_date} 이전의 모든 가상 매매 기록({total_count}건)을 삭제합니다.")
print("이 작업은 되돌릴 수 없습니다.\n")

# 삭제 실행
try:
    cursor.execute('''
        DELETE FROM virtual_trading_records 
        WHERE is_test = 1 AND DATE(timestamp) < ?
    ''', (cutoff_date,))
    
    deleted_count = cursor.rowcount
    conn.commit()
    
    print(f"삭제 완료: {deleted_count}건")
    
    # 삭제 후 확인
    cursor.execute('''
        SELECT COUNT(*) FROM virtual_trading_records 
        WHERE is_test = 1
    ''')
    remaining_count = cursor.fetchone()[0]
    print(f"\n남은 가상 매매 기록: {remaining_count}건")
    
    # 날짜별 분포 확인
    print("\n[남은 기록 날짜별 분포]")
    cursor.execute('''
        SELECT DATE(timestamp) as date, action, COUNT(*) as cnt
        FROM virtual_trading_records
        WHERE is_test = 1
        GROUP BY DATE(timestamp), action
        ORDER BY date DESC
        LIMIT 10
    ''')
    
    rows = cursor.fetchall()
    for row in rows:
        date, action, cnt = row
        print(f"  {date}: {action} {cnt}건")
    
except Exception as e:
    conn.rollback()
    print(f"삭제 실패: {e}")
    raise
finally:
    conn.close()

print("\n" + "=" * 100)

