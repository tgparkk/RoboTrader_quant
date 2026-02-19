"""오늘자 가상매매 분석 (is_test=1 기준)"""
import psycopg2
from datetime import datetime

conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader_quant', user='postgres', password='postgres')
cursor = conn.cursor()

today = '2026-01-19'

print("=" * 100)
print(f"📊 가상매매 분석 보고서 - {today}")
print("=" * 100)
print()

# 1. 오늘 매매 기록
cursor.execute('''
    SELECT action, stock_code, stock_name, quantity, price,
           to_char(to_timestamp(timestamp) AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') as trade_time,
           target_profit_rate, stop_loss_rate, strategy
    FROM virtual_trading_records
    WHERE DATE(to_timestamp(timestamp) AT TIME ZONE 'Asia/Seoul') = %s AND is_test = 1
    ORDER BY timestamp
''', (today,))

records = cursor.fetchall()

print("=" * 100)
print(f"1️⃣ 오늘 매매 내역: {len(records)}건")
print("=" * 100)

buy_count = 0
sell_count = 0
total_buy_amount = 0
total_sell_amount = 0

if records:
    print("\n💰 매수 내역:")
    print("-" * 100)
    for r in records:
        action, code, name, qty, price, ts, target, stop, strategy = r
        if action == "BUY":
            buy_count += 1
            amount = qty * price
            total_buy_amount += amount
            target_str = f"{target*100:.1f}%" if target else "N/A"
            stop_str = f"{stop*100:.1f}%" if stop else "N/A"
            print(f"  {ts} | {code} {name:20s} | {qty:4d}주 @{price:>10,.0f}원 = {amount:>12,.0f}원 | "
                  f"익절 {target_str} 손절 {stop_str}")

    print("\n💸 매도 내역:")
    print("-" * 100)
    sell_found = False
    for r in records:
        action, code, name, qty, price, ts, target, stop, strategy = r
        if action == "SELL":
            sell_count += 1
            sell_found = True
            amount = qty * price
            total_sell_amount += amount
            print(f"  {ts} | {code} {name:20s} | {qty:4d}주 @{price:>10,.0f}원 = {amount:>12,.0f}원")

    if not sell_found:
        print("  매도 없음")

    print()
    print(f"총 매수: {buy_count}건, {total_buy_amount:,.0f}원")
    print(f"총 매도: {sell_count}건, {total_sell_amount:,.0f}원")
else:
    print("매매 기록 없음")

print()

# 2. 현재 보유 종목 (미체결 포지션)
cursor.execute('''
    SELECT b.stock_code, b.stock_name, b.quantity, b.price,
           b.target_profit_rate, b.stop_loss_rate,
           to_char(to_timestamp(b.timestamp) AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') as buy_time
    FROM virtual_trading_records b
    WHERE b.action = 'BUY' AND b.is_test = 1
      AND NOT EXISTS (
        SELECT 1 FROM virtual_trading_records s
        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
      )
    ORDER BY b.timestamp DESC
''')

holdings = cursor.fetchall()

print("=" * 100)
print(f"2️⃣ 현재 보유 종목: {len(holdings)}개")
print("=" * 100)

if holdings:
    total_value = 0

    for code, name, qty, price, target, stop, buy_time in holdings:
        cursor.execute('''
            SELECT close FROM daily_prices
            WHERE stock_code = %s
            ORDER BY date DESC
            LIMIT 1
        ''', (code,))

        price_row = cursor.fetchone()
        current_price = price_row[0] if price_row else price

        buy_value = qty * price
        current_value = qty * current_price
        unrealized_pl = current_value - buy_value
        unrealized_pl_rate = (unrealized_pl / buy_value * 100) if buy_value > 0 else 0

        total_value += current_value

        pl_emoji = "🟢" if unrealized_pl >= 0 else "🔴"
        pl_sign = "+" if unrealized_pl >= 0 else ""

        target_str = f"{target*100:.0f}%" if target else "N/A"
        stop_str = f"{stop*100:.0f}%" if stop else "N/A"

        print(f"{code} {name:20s} | {qty:4d}주 @{price:>9,.0f}원 → {current_price:>9,.0f}원 | "
              f"{pl_emoji}{pl_sign}{unrealized_pl_rate:>6.1f}% ({pl_sign}{unrealized_pl:>10,.0f}원) | "
              f"익절{target_str} 손절{stop_str}")

    print("-" * 100)
    print(f"{'총 평가금액:':<80} {total_value:>15,.0f}원")
else:
    print("보유 종목 없음")

print()

# 3. 누적 수익 통계
cursor.execute('''
    SELECT
        COUNT(*) as total_trades,
        SUM(profit_loss) as total_pl,
        SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as win_count,
        SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as loss_count,
        AVG(profit_rate) as avg_profit_rate,
        MAX(profit_rate) as max_profit_rate,
        MIN(profit_rate) as min_profit_rate
    FROM virtual_trading_records
    WHERE action = 'SELL' AND is_test = 1
''')

stats = cursor.fetchone()

print("=" * 100)
print("3️⃣ 가상매매 누적 통계 (전체 기간)")
print("=" * 100)

if stats and stats[0] > 0:
    total_trades, total_pl, win_count, loss_count, avg_rate, max_rate, min_rate = stats
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

    print(f"총 매도 거래: {total_trades:,}건")
    print(f"  - 익절: {win_count}건 ({win_rate:.1f}%)")
    print(f"  - 손절: {loss_count}건 ({100-win_rate:.1f}%)")
    print()
    print(f"실현 손익: {total_pl:>15,.0f}원")
    print(f"평균 수익률: {avg_rate*100:>13.2f}%")
    print(f"최고 수익률: {max_rate*100:>13.2f}%")
    print(f"최저 수익률: {min_rate*100:>13.2f}%")
else:
    print("매도 거래 내역이 없습니다.")

print()

# 4. 최근 7일 매매 현황
cursor.execute('''
    SELECT
        DATE(to_timestamp(timestamp) AT TIME ZONE 'Asia/Seoul')::text as trade_date,
        action,
        COUNT(*) as count,
        SUM(quantity * price) as amount
    FROM virtual_trading_records
    WHERE is_test = 1
      AND DATE(to_timestamp(timestamp) AT TIME ZONE 'Asia/Seoul') >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY trade_date, action
    ORDER BY trade_date DESC, action
''')

recent_trades = cursor.fetchall()

print("=" * 100)
print("4️⃣ 최근 7일 매매 현황")
print("=" * 100)

if recent_trades:
    current_date = None
    for trade_date, action, count, amount in recent_trades:
        if trade_date != current_date:
            if current_date is not None:
                print()
            print(f"📅 {trade_date}:")
            current_date = trade_date

        emoji = "💰" if action == "BUY" else "💸"
        action_kr = "매수" if action == "BUY" else "매도"
        print(f"  {emoji} {action_kr}: {count:2d}건, {amount:>12,.0f}원")
else:
    print("최근 7일간 매매 기록 없음")

print()
print("=" * 100)
print("✅ 분석 완료")
print("=" * 100)

conn.close()
