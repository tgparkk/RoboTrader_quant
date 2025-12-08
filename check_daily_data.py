"""일봉 데이터 수집 현황 확인"""
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

today = datetime.now().strftime('%Y-%m-%d')
print(f"=== {today} 일봉 데이터 수집 현황 ===\n")

db_path = Path("data/robotrader.db")
conn = sqlite3.connect(str(db_path))

# 1. 후보 종목 확인
print("1️⃣ 후보 종목")
print("-" * 60)
cursor = conn.cursor()
cursor.execute('SELECT stock_code, stock_name FROM candidate_stocks WHERE DATE(selection_date) = ?', (today,))
candidates = cursor.fetchall()
print(f"선정된 후보 종목: {len(candidates)}개")
for code, name in candidates:
    print(f"  - {code} ({name})")

# 2. 일봉 데이터 확인
print("\n2️⃣ 일봉 데이터 수집 현황")
print("-" * 60)
if candidates:
    candidate_codes = [c[0] for c in candidates]
    placeholders = ','.join(['?'] * len(candidate_codes))
    query = f'''
    SELECT stock_code, COUNT(*) as count, MIN(date) as first_date, MAX(date) as last_date
    FROM daily_prices
    WHERE stock_code IN ({placeholders})
    GROUP BY stock_code
    '''
    df = pd.read_sql_query(query, conn, params=candidate_codes)
    
    if len(df) > 0:
        print(f"일봉 데이터가 있는 종목: {len(df)}개")
        for _, row in df.iterrows():
            print(f"  - {row['stock_code']}: {row['count']}건 (기간: {row['first_date']} ~ {row['last_date']})")
    else:
        print("일봉 데이터가 있는 종목: 0개")
    
    # 오늘 날짜 일봉 데이터 확인
    query_today = f'''
    SELECT stock_code, COUNT(*) as count
    FROM daily_prices
    WHERE stock_code IN ({placeholders}) AND date = ?
    GROUP BY stock_code
    '''
    df_today = pd.read_sql_query(query_today, conn, params=candidate_codes + [today])
    print(f"\n오늘({today}) 일봉 데이터:")
    if len(df_today) > 0:
        for _, row in df_today.iterrows():
            print(f"  - {row['stock_code']}: {row['count']}건")
    else:
        print("  오늘 일봉 데이터 없음")
else:
    print("후보 종목이 없어 확인 불가")

# 3. 매매 판단에 필요한 데이터 확인
print("\n3️⃣ 매매 판단에 필요한 데이터")
print("-" * 60)
print("매매 판단은 주로 1분봉 데이터를 사용합니다:")
print("  - 최소 15개의 1분봉 데이터 필요")
print("  - 3분봉 변환 후 최소 5개 필요")
print("  - 일봉 데이터는 후보 선정 시에만 사용")

conn.close()
