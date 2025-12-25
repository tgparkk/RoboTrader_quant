import sqlite3
import pandas as pd
from datetime import datetime, timedelta

db_path = 'd:/GIT/RoboTrader_quant/data/robotrader.db'
conn = sqlite3.connect(db_path)

print('=' * 100)
print('                           Data Storage Health Check')
print('=' * 100)
print()

# 1. 일봉 데이터 (daily_prices)
print('[1] Daily Prices (daily_prices)')
print('-' * 100)
query = '''
SELECT
    date,
    COUNT(DISTINCT stock_code) as stocks,
    COUNT(*) as records
FROM daily_prices
WHERE date >= '2025-12-20'
GROUP BY date
ORDER BY date DESC
LIMIT 10
'''
df_daily = pd.read_sql_query(query, conn)
print(df_daily.to_string(index=False))
print()

# 2. 재무제표 테이블 스키마 확인
print('[2] Financial Statements Schema')
print('-' * 100)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%financial%'")
tables = cursor.fetchall()
print('Financial tables:', [t[0] for t in tables])
print()

if tables:
    for table_name, in tables:
        cursor.execute(f'PRAGMA table_info({table_name})')
        columns = cursor.fetchall()
        print(f'Table: {table_name}')
        for col in columns:
            print(f'  - {col[1]} ({col[2]})')
        print()

# 3. 재무지표 데이터 확인
print('[3] Financial Data Status')
print('-' * 100)
query = '''
SELECT
    COUNT(DISTINCT stock_code) as total_stocks,
    COUNT(*) as total_records,
    MAX(updated_at) as last_update
FROM financial_data
'''
df_fd = pd.read_sql_query(query, conn)
print(df_fd.to_string(index=False))
print()

# 샘플 데이터 확인
query = '''
SELECT stock_code, per, pbr, roe, debt_ratio, updated_at
FROM financial_data
ORDER BY updated_at DESC
LIMIT 5
'''
df_sample = pd.read_sql_query(query, conn)
if len(df_sample) > 0:
    print('Sample records:')
    print(df_sample.to_string(index=False))
else:
    print('No financial data found')
print()

# 4. 퀀트 팩터 점수
print('[4] Quant Factor Scores (quant_factors)')
print('-' * 100)
query = '''
SELECT
    calc_date,
    COUNT(DISTINCT stock_code) as stocks,
    COUNT(*) as records,
    AVG(total_score) as avg_score,
    MIN(total_score) as min_score,
    MAX(total_score) as max_score
FROM quant_factors
WHERE calc_date >= '20251220'
GROUP BY calc_date
ORDER BY calc_date DESC
'''
df_qf = pd.read_sql_query(query, conn)
if len(df_qf) > 0:
    print(df_qf.to_string(index=False))
else:
    print('No recent factor data')
print()

# 5. 데이터 일관성 체크
print('[5] Data Consistency Check')
print('-' * 100)

# 12/24 데이터 비교
query = '''
SELECT
    (SELECT COUNT(DISTINCT stock_code) FROM daily_prices WHERE date = '2025-12-24') as daily_stocks,
    (SELECT COUNT(DISTINCT stock_code) FROM quant_factors WHERE calc_date = '20251224') as factor_stocks,
    (SELECT COUNT(DISTINCT stock_code) FROM quant_portfolio WHERE calc_date = '20251224') as portfolio_stocks
'''
df_check = pd.read_sql_query(query, conn)
print('2025-12-24 Data:')
print(f'  Daily prices: {df_check["daily_stocks"].iloc[0]} stocks')
print(f'  Factor scores: {df_check["factor_stocks"].iloc[0]} stocks')
print(f'  Portfolio: {df_check["portfolio_stocks"].iloc[0]} stocks')
print()

# 문제 진단
issues = []
daily = df_check["daily_stocks"].iloc[0]
factor = df_check["factor_stocks"].iloc[0]
portfolio = df_check["portfolio_stocks"].iloc[0]

if daily > 0 and factor == 0:
    issues.append('WARNING: Daily prices exist but no factor scores')
elif daily == 0:
    issues.append('WARNING: No daily price data for 2025-12-24')

if factor > 0 and daily > 0 and factor != daily:
    issues.append(f'INFO: Factor stocks ({factor}) != Daily stocks ({daily})')
    issues.append('  -> This is normal: factors are calculated for all stocks, not just held ones')

if portfolio == 0 and factor > 0:
    issues.append('WARNING: Factor scores exist but no portfolio')

if len(issues) == 0:
    print('STATUS: All data checks passed')
else:
    print('ISSUES FOUND:')
    for issue in issues:
        print(f'  - {issue}')
print()

# 6. 일봉 데이터 저장 패턴 분석
print('[6] Daily Price Storage Pattern Analysis')
print('-' * 100)

query = '''
SELECT
    date,
    COUNT(DISTINCT stock_code) as stocks
FROM daily_prices
WHERE date >= '2025-12-01'
GROUP BY date
ORDER BY date DESC
LIMIT 20
'''
df_pattern = pd.read_sql_query(query, conn)
print(df_pattern.to_string(index=False))
print()

if len(df_pattern) > 0:
    avg_stocks = df_pattern['stocks'].mean()
    min_stocks = df_pattern['stocks'].min()
    max_stocks = df_pattern['stocks'].max()

    print(f'Statistics:')
    print(f'  Average: {avg_stocks:.0f} stocks/day')
    print(f'  Range: {min_stocks} - {max_stocks} stocks')

    if max_stocks - min_stocks > 10:
        print(f'  WARNING: Large variation in stock count ({max_stocks - min_stocks} stocks)')
        print(f'  -> Some days may have incomplete data')
print()

# 7. 재무 데이터 업데이트 빈도
print('[7] Financial Data Update Frequency')
print('-' * 100)

query = '''
SELECT
    DATE(updated_at) as update_date,
    COUNT(*) as updates
FROM financial_data
WHERE updated_at >= datetime('now', '-30 days')
GROUP BY DATE(updated_at)
ORDER BY update_date DESC
LIMIT 10
'''
df_updates = pd.read_sql_query(query, conn)
if len(df_updates) > 0:
    print(df_updates.to_string(index=False))
else:
    print('No recent updates in the last 30 days')
    print('WARNING: Financial data may be stale')

conn.close()

print()
print('=' * 100)
print('Check complete')
print('=' * 100)
