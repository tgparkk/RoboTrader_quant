import sqlite3
import pandas as pd

db_path = 'd:/GIT/RoboTrader_quant/data/robotrader.db'
conn = sqlite3.connect(db_path)

print('=' * 100)
print('                           2025-12-24 RoboTrader Daily Report')
print('=' * 100)
print()

# 1. Data Collection Status
print('[1] Data Collection Status')
print('-' * 100)

query_data = '''
SELECT
    COUNT(DISTINCT stock_code) as stocks,
    COUNT(*) as records,
    MIN(date) as date
FROM daily_prices
WHERE date = '2025-12-24'
'''
df_data = pd.read_sql_query(query_data, conn)
print(f'   - Collected Stocks: {df_data["stocks"].iloc[0]} stocks')
print(f'   - Daily Price Records: {df_data["records"].iloc[0]} records')
print(f'   - Data Date: {df_data["date"].iloc[0]}')
print()

# 2. Trading Activity on 12/24
print('[2] Trading Activity on 2025-12-24')
print('-' * 100)

query_trading = '''
SELECT
    timestamp,
    stock_code,
    stock_name,
    action,
    quantity,
    price,
    ROUND(price * quantity, 0) as amount,
    ROUND(profit_loss, 0) as pnl,
    ROUND(profit_rate * 100, 2) as return_pct,
    ROUND(target_profit_rate * 100, 1) as target_profit_pct,
    ROUND(stop_loss_rate * 100, 1) as stop_loss_pct,
    reason
FROM virtual_trading_records
WHERE DATE(timestamp) = '2025-12-24'
ORDER BY timestamp
'''
df_trading = pd.read_sql_query(query_trading, conn)

if len(df_trading) > 0:
    # Sells
    sells = df_trading[df_trading['action'] == 'SELL']
    buys = df_trading[df_trading['action'] == 'BUY']

    if len(sells) > 0:
        print('   [SELL Orders]')
        for idx, row in sells.iterrows():
            print(f'      - [{row["timestamp"]}] {row["stock_name"]}({row["stock_code"]})')
            print(f'        Qty: {row["quantity"]} @ {row["price"]:,.0f} KRW = {row["amount"]:,.0f} KRW')
            print(f'        P&L: {row["pnl"]:,.0f} KRW ({row["return_pct"]:+.2f}%)')
            print(f'        Reason: {row["reason"]}')

            # 상세 매도 사유 추가
            if row["stock_code"] == '138490':
                print(f'        Detail: 12/24 목표 포트폴리오 TOP 30에서 제외됨 (순위 하락)')
            print()

    if len(buys) > 0:
        print('   [BUY Orders]')
        for idx, row in buys.iterrows():
            print(f'      - [{row["timestamp"]}] {row["stock_name"]}({row["stock_code"]})')
            print(f'        Qty: {row["quantity"]} @ {row["price"]:,.0f} KRW = {row["amount"]:,.0f} KRW')
            print(f'        Target: Profit +{row["target_profit_pct"]:.1f}% / Stop -{row["stop_loss_pct"]:.1f}%')
            print()
else:
    print('   No trading activity')
    print()

# 3. Daily P&L Summary
print('[3] Daily P&L Summary (2025-12-24)')
print('-' * 100)

query_daily = '''
SELECT
    SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
    SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sells,
    ROUND(SUM(CASE WHEN action = 'SELL' THEN profit_loss ELSE 0 END), 0) as daily_pnl,
    ROUND(AVG(CASE WHEN action = 'SELL' THEN profit_rate * 100 ELSE NULL END), 2) as avg_return,
    SUM(CASE WHEN action = 'SELL' AND profit_loss > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN action = 'SELL' AND profit_loss < 0 THEN 1 ELSE 0 END) as losses
FROM virtual_trading_records
WHERE DATE(timestamp) = '2025-12-24'
'''
df_daily = pd.read_sql_query(query_daily, conn)
print(f'   - Buy Orders: {df_daily["buys"].iloc[0]}')
print(f'   - Sell Orders: {df_daily["sells"].iloc[0]} (Wins: {df_daily["wins"].iloc[0]}, Losses: {df_daily["losses"].iloc[0]})')
if df_daily['sells'].iloc[0] > 0:
    print(f'   - Daily P&L: {df_daily["daily_pnl"].iloc[0]:,.0f} KRW')
    print(f'   - Average Return: {df_daily["avg_return"].iloc[0]:+.2f}%')
print()

# 4. Current Holdings
print('[4] Current Holdings (as of 2025-12-24 EOD)')
print('-' * 100)

query_positions = '''
SELECT
    stock_code,
    stock_name,
    quantity,
    buy_price,
    buy_timestamp,
    ROUND(target_profit_rate * 100, 1) as target_profit,
    ROUND(stop_loss_rate * 100, 1) as stop_loss,
    ROUND(buy_price * quantity, 0) as invested
FROM (
    SELECT
        b.stock_code,
        b.stock_name,
        b.quantity,
        b.price as buy_price,
        b.timestamp as buy_timestamp,
        b.target_profit_rate,
        b.stop_loss_rate,
        ROW_NUMBER() OVER (PARTITION BY b.stock_code ORDER BY b.timestamp DESC) as rn
    FROM virtual_trading_records b
    WHERE b.action = 'BUY'
    AND NOT EXISTS (
        SELECT 1 FROM virtual_trading_records s
        WHERE s.stock_code = b.stock_code
        AND s.action = 'SELL'
        AND s.timestamp > b.timestamp
    )
)
WHERE rn = 1
ORDER BY buy_timestamp DESC
'''
df_positions = pd.read_sql_query(query_positions, conn)
if len(df_positions) > 0:
    # Grade classification
    s_grade = df_positions[(df_positions['target_profit'] == 20.0) & (df_positions['stop_loss'] == 8.0)]
    a_grade = df_positions[(df_positions['target_profit'] == 17.0) & (df_positions['stop_loss'] == 9.0)]
    b_grade = df_positions[(df_positions['target_profit'] == 15.0) & (df_positions['stop_loss'] == 10.0)]

    print(f'   Total: {len(df_positions)} stocks (Invested: {df_positions["invested"].sum():,.0f} KRW)')
    print()

    if len(s_grade) > 0:
        print(f'   [S-Grade] {len(s_grade)} stocks - Target: +20% / Stop: -8%')
        for idx, row in s_grade.head(5).iterrows():
            print(f'      {row["stock_name"]}({row["stock_code"]}): {row["quantity"]}shares @ {row["buy_price"]:,.0f}KRW')
        if len(s_grade) > 5:
            print(f'      ... and {len(s_grade)-5} more')
        print()

    if len(a_grade) > 0:
        print(f'   [A-Grade] {len(a_grade)} stocks - Target: +17% / Stop: -9%')
        for idx, row in a_grade.head(5).iterrows():
            print(f'      {row["stock_name"]}({row["stock_code"]}): {row["quantity"]}shares @ {row["buy_price"]:,.0f}KRW')
        if len(a_grade) > 5:
            print(f'      ... and {len(a_grade)-5} more')
        print()

    if len(b_grade) > 0:
        print(f'   [B-Grade] {len(b_grade)} stocks - Target: +15% / Stop: -10%')
        for idx, row in b_grade.head(5).iterrows():
            print(f'      {row["stock_name"]}({row["stock_code"]}): {row["quantity"]}shares @ {row["buy_price"]:,.0f}KRW')
        if len(b_grade) > 5:
            print(f'      ... and {len(b_grade)-5} more')
        print()
else:
    print('   No holdings')
    print()

# 5. Cumulative Statistics
print('[5] Cumulative Statistics (All-Time)')
print('-' * 100)

query_total = '''
SELECT
    COUNT(*) as total_trades,
    SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as total_sells,
    ROUND(SUM(CASE WHEN action = 'SELL' THEN profit_loss ELSE 0 END), 0) as cumulative_pnl,
    ROUND(AVG(CASE WHEN action = 'SELL' THEN profit_rate * 100 ELSE NULL END), 2) as avg_return,
    SUM(CASE WHEN action = 'SELL' AND profit_loss > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN action = 'SELL' AND profit_loss < 0 THEN 1 ELSE 0 END) as losses,
    ROUND(SUM(CASE WHEN action = 'SELL' AND profit_loss > 0 THEN 1 ELSE 0 END) * 100.0 /
          NULLIF(SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END), 0), 1) as win_rate
FROM virtual_trading_records
'''
df_total = pd.read_sql_query(query_total, conn)
print(f'   - Total Trades: {df_total["total_trades"].iloc[0]} (Sells: {df_total["total_sells"].iloc[0]})')
print(f'   - Cumulative P&L: {df_total["cumulative_pnl"].iloc[0]:,.0f} KRW')
print(f'   - Average Return: {df_total["avg_return"].iloc[0]:+.2f}%')
print(f'   - Win Rate: {df_total["win_rate"].iloc[0]:.1f}% (Wins: {df_total["wins"].iloc[0]} / Losses: {df_total["losses"].iloc[0]})')
print()

print('=' * 100)

conn.close()
