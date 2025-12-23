"""보유 종목 현황 및 실시간 수익률 조회"""
import sqlite3
import sys
from pathlib import Path

# API 경로 추가
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from api import kis_market_api

db_path = Path(__file__).parent / 'data' / 'robotrader.db'

# 보유 종목 조회
with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            b.stock_code,
            b.stock_name,
            SUM(b.quantity) - COALESCE(SUM(s.quantity), 0) as qty,
            SUM(b.quantity * b.price) / SUM(b.quantity) as avg_buy,
            MAX(b.target_profit_rate) as target_profit_rate,
            MAX(b.stop_loss_rate) as stop_loss_rate
        FROM virtual_trading_records b
        LEFT JOIN virtual_trading_records s
            ON s.buy_record_id = b.id AND s.action = 'SELL'
        WHERE b.action = 'BUY' AND b.is_test = 1
        GROUP BY b.stock_code
        HAVING qty > 0
        ORDER BY MAX(b.timestamp) DESC
    ''')

    holdings = cursor.fetchall()

    print('=' * 105)
    print(f"{'보유 종목 현황':^103s}")
    print('=' * 105)
    header = f"{'종목코드':^8s}  {'종목명':^12s}  {'수량':^6s}  {'평균매수가':^12s}  {'현재가':^12s}  {'수익률':^9s}  {'목표익절':^9s}  {'손절':^7s}"
    print(header)
    print('-' * 105)

    total_buy_value = 0
    total_current_value = 0
    success_count = 0

    for stock_code, stock_name, qty, avg_buy, target_profit, stop_loss in holdings:
        try:
            # 현재가 조회
            price_data = kis_market_api.get_inquire_price(div_code='J', itm_no=stock_code)
            if price_data is not None and not price_data.empty:
                current_price = int(price_data.iloc[0]['stck_prpr'])
                profit_rate = ((current_price - avg_buy) / avg_buy) * 100

                buy_value = avg_buy * qty
                current_value = current_price * qty

                total_buy_value += buy_value
                total_current_value += current_value
                success_count += 1

                profit_str = f'{profit_rate:+.2f}%'
                target_str = f'+{target_profit*100:.1f}%' if target_profit else 'N/A'
                stop_str = f'-{stop_loss*100:.1f}%' if stop_loss else 'N/A'

                print(f'{stock_code:8s}  {stock_name:12s}  {qty:6.0f}  {avg_buy:12,.0f}원  {current_price:12,.0f}원  {profit_str:>9s}  {target_str:>9s}  {stop_str:>7s}')
            else:
                print(f'{stock_code:8s}  {stock_name:12s}  {qty:6.0f}  {avg_buy:12,.0f}원  [현재가 조회 실패]')
        except Exception as e:
            print(f'{stock_code:8s}  {stock_name:12s}  {qty:6.0f}  {avg_buy:12,.0f}원  [오류: {str(e)[:30]}]')

    print('-' * 105)
    if total_buy_value > 0:
        total_profit_rate = ((total_current_value - total_buy_value) / total_buy_value) * 100
        print(f'\n합계 ({success_count}/{len(holdings)}종목):')
        print(f'  매수금액: {total_buy_value:>15,.0f}원')
        print(f'  평가금액: {total_current_value:>15,.0f}원')
        print(f'  평가손익: {total_current_value - total_buy_value:>15,.0f}원 ({total_profit_rate:+.2f}%)')
    print('=' * 105)
