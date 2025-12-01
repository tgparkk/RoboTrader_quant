"""DB 기록 현황 조회"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/robotrader.db')
cursor = conn.cursor()

# 1. 테이블 목록 확인
print('=== DB 테이블 목록 ===')
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
for t in tables:
    print(f'  - {t[0]}')

print()

# 2. 각 테이블별 기록 개수
print('=== 테이블별 전체 기록 수 ===')
for table in [t[0] for t in tables]:
    try:
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        count = cursor.fetchone()[0]
        print(f'  {table}: {count}건')
    except:
        pass

print()

# 3. 오늘 날짜 기록 확인
print('=== 오늘(2025-12-01) 기록 ===')

# candidate_stocks
cursor.execute("SELECT COUNT(*) FROM candidate_stocks WHERE selection_date LIKE '2025-12-01%'")
count = cursor.fetchone()[0]
print(f'  candidate_stocks (후보종목): {count}건')

# virtual_trading_records
try:
    cursor.execute("SELECT COUNT(*) FROM virtual_trading_records WHERE timestamp LIKE '2025-12-01%'")
    count = cursor.fetchone()[0]
    print(f'  virtual_trading_records (가상매매): {count}건')
except:
    print('  virtual_trading_records: 테이블 없음')

# real_trading_records
try:
    cursor.execute("SELECT COUNT(*) FROM real_trading_records WHERE timestamp LIKE '2025-12-01%'")
    count = cursor.fetchone()[0]
    print(f'  real_trading_records (실제매매): {count}건')
except:
    print('  real_trading_records: 테이블 없음')

print()

# 4. 오늘 후보 종목 상세
print('=== 오늘 선정된 후보 종목 상세 ===')
query = '''
SELECT stock_code, stock_name, score, reasons, status, selection_date
FROM candidate_stocks
WHERE selection_date LIKE '2025-12-01%'
ORDER BY score DESC
'''
df = pd.read_sql_query(query, conn)
if len(df) > 0:
    print(df.to_string())
else:
    print('오늘 선정된 후보 없음')

conn.close()

