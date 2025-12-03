#!/usr/bin/env python3
"""가상매매 DB 저장 테스트"""
import asyncio
from core.models import TradingConfig, Order, OrderType, OrderStatus
from core.order_manager import OrderManager
from api.kis_api_manager import KISAPIManager
from db.database_manager import DatabaseManager
from utils.korean_time import now_kst

async def test_virtual_buy():
    """가상매수 DB 저장 테스트"""
    print("=== 가상매매 DB 저장 테스트 ===\n")
    
    # 설정 로드
    config = TradingConfig.load_from_file()
    
    # DB 매니저 초기화
    db_manager = DatabaseManager()
    
    # API 매니저 초기화 (실제 API는 사용하지 않음)
    api_manager = KISAPIManager()
    
    # OrderManager 초기화 (db_manager 포함)
    order_manager = OrderManager(config, api_manager, None, db_manager)
    
    print(f"1. 설정 확인:")
    print(f"   paper_trading: {getattr(config, 'paper_trading', False)}")
    print()
    
    # 테스트 매수 주문
    print("2. 테스트 매수 주문 실행:")
    test_stock_code = "TEST01"
    test_quantity = 10
    test_price = 10000.0
    
    order_id = await order_manager.place_buy_order(
        stock_code=test_stock_code,
        quantity=test_quantity,
        price=test_price
    )
    
    if order_id:
        print(f"   ✅ 주문 ID: {order_id}")
    else:
        print(f"   ❌ 주문 실패")
    print()
    
    # DB 확인
    print("3. DB 저장 확인:")
    import sqlite3
    conn = sqlite3.connect('data/robotrader.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT stock_code, stock_name, action, quantity, price, timestamp
        FROM virtual_trading_records
        WHERE stock_code = ?
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (test_stock_code,))
    
    row = cursor.fetchone()
    if row:
        print(f"   ✅ DB 저장 성공!")
        print(f"   종목: {row[0]} {row[1]}")
        print(f"   액션: {row[2]}")
        print(f"   수량: {row[3]}주")
        print(f"   가격: {row[4]:,.0f}원")
        print(f"   시간: {row[5]}")
    else:
        print(f"   ❌ DB 저장 실패 - 기록 없음")
    
    conn.close()
    print()
    
    print("4. 테스트 완료!")
    print("   실제 리밸런싱 시에도 동일하게 DB에 저장됩니다.")

if __name__ == "__main__":
    asyncio.run(test_virtual_buy())

