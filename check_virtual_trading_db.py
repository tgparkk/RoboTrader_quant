#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
가상매매 DB 상태 점검 스크립트
"""
import psycopg2
from datetime import datetime

conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader_quant', user='postgres', password='postgres')
cursor = conn.cursor()

print("=" * 100)
print("🔍 가상매매 DB 상태 점검")
print("=" * 100)
print()

# 1. is_test 플래그별 통계
print("1️⃣ is_test 플래그별 거래 통계")
print("-" * 100)
cursor.execute('''
    SELECT
        is_test,
        action,
        COUNT(*) as count,
        SUM(quantity * price) as total_amount
    FROM virtual_trading_records
    GROUP BY is_test, action
    ORDER BY is_test, action
''')

results = cursor.fetchall()
if results:
    print(f"{'is_test':<10} {'Action':<10} {'Count':>10} {'Total Amount':>20}")
    print("-" * 100)
    for is_test, action, count, total_amt in results:
        test_label = "테스트" if is_test else "실전"
        print(f"{test_label:<10} {action:<10} {count:>10} {total_amt or 0:>20,.0f}원")
else:
    print("  거래 기록 없음")
print()

# 2. 오늘 날짜 거래 (is_test 구분)
print("2️⃣ 오늘(2026-01-20) 거래 내역 (is_test 구분)")
print("-" * 100)
cursor.execute('''
    SELECT
        is_test,
        action,
        stock_code,
        stock_name,
        quantity,
        price,
        timestamp
    FROM virtual_trading_records
    WHERE DATE(to_timestamp(timestamp) AT TIME ZONE 'Asia/Seoul') = '2026-01-20'
    ORDER BY timestamp
''')

today_records = cursor.fetchall()
if today_records:
    for is_test, action, stock_code, stock_name, qty, price, ts in today_records:
        test_label = "[테스트]" if is_test else "[실전]"
        ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M') if isinstance(ts, (int, float)) else str(ts)[:16]
        print(f"{test_label} {ts_str} | {action:<4} | {stock_code} ({stock_name}) | {qty}주 @{price:,.0f}원")
else:
    print("  오늘 거래 내역 없음")
print()

# 3. 최근 10건 거래 (is_test 포함)
print("3️⃣ 최근 10건 거래 내역")
print("-" * 100)
cursor.execute('''
    SELECT
        timestamp,
        is_test,
        action,
        stock_code,
        stock_name,
        quantity,
        price,
        profit_loss
    FROM virtual_trading_records
    ORDER BY timestamp DESC
    LIMIT 10
''')

recent = cursor.fetchall()
if recent:
    for row in recent:
        ts = str(row[0]) if row[0] else ""
        is_test = row[1]
        action = row[2]
        stock_code = row[3]
        stock_name = row[4]
        qty = row[5]
        price = row[6]
        pl = row[7]

        test_label = "[테스트]" if is_test else "[실전]"
        ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M') if ts.isdigit() else ts[:16]
        pl_str = f"손익 {pl:,.0f}원" if pl and action == 'SELL' else ""
        print(f"{test_label} {ts_str} | {action:<4} | {stock_code} ({stock_name}) | {qty}주 @{price:,.0f}원 {pl_str}")
else:
    print("  거래 내역 없음")
print()

# 4. 현재 보유 종목 (is_test 구분)
print("4️⃣ 현재 보유 종목 (is_test 구분)")
print("-" * 100)
cursor.execute('''
    SELECT
        b.is_test,
        b.stock_code,
        b.stock_name,
        b.quantity,
        b.price,
        b.timestamp
    FROM virtual_trading_records b
    WHERE b.action = 'BUY'
      AND NOT EXISTS (
        SELECT 1 FROM virtual_trading_records s
        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
      )
    ORDER BY b.is_test, b.timestamp DESC
''')

holdings = cursor.fetchall()
if holdings:
    test_count = 0
    real_count = 0
    for is_test, stock_code, stock_name, qty, price, ts in holdings:
        test_label = "[테스트]" if is_test else "[실전]"
        ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d') if isinstance(ts, (int, float)) else str(ts)[:10]
        print(f"{test_label} {stock_code} ({stock_name}) | {qty}주 @{price:,.0f}원 | 매수일: {ts_str}")
        if is_test:
            test_count += 1
        else:
            real_count += 1
    print()
    print(f"  📊 요약: 실전 {real_count}개, 테스트 {test_count}개")
else:
    print("  보유 종목 없음")
print()

# 5. 전체 통계
print("5️⃣ 전체 가상매매 통계")
print("-" * 100)
cursor.execute('''
    SELECT
        is_test,
        COUNT(CASE WHEN action = 'BUY' THEN 1 END) as buys,
        COUNT(CASE WHEN action = 'SELL' THEN 1 END) as sells,
        SUM(CASE WHEN action = 'SELL' THEN profit_loss ELSE 0 END) as total_pl
    FROM virtual_trading_records
    GROUP BY is_test
''')

stats = cursor.fetchall()
if stats:
    for is_test, buys, sells, total_pl in stats:
        test_label = "테스트 모드" if is_test else "실전 모드"
        print(f"{test_label}:")
        print(f"  - 매수: {buys}건")
        print(f"  - 매도: {sells}건")
        print(f"  - 실현 손익: {total_pl or 0:,.0f}원")
        print()
else:
    print("  통계 없음")

conn.close()

print("=" * 100)
print("✅ 점검 완료")
print("=" * 100)
