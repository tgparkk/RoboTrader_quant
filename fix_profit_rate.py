"""
기존 매도 기록의 손익률을 재계산하여 업데이트하는 스크립트

문제:
- 여러 번 분할 매수한 종목을 한 번에 매도할 때
- 첫 번째 매수 가격만 참조하여 손익 계산되었음
- 실제 평균 매수가로 재계산 필요
"""
import sqlite3
from pathlib import Path


def fix_virtual_trading_profit_rates():
    """가상 매매 기록의 손익률 재계산"""
    db_path = Path(__file__).parent / "data" / "robotrader.db"

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 모든 매도 기록 조회
        cursor.execute('''
            SELECT id, stock_code, quantity, price
            FROM virtual_trading_records
            WHERE action = 'SELL' AND is_test = 1
        ''')

        sell_records = cursor.fetchall()

        print(f"총 {len(sell_records)}건의 매도 기록 재계산 중...")

        updated_count = 0
        for sell_id, stock_code, sell_qty, sell_price in sell_records:
            # 해당 매도 시점 이전의 미체결 매수 기록으로 평균 매수가 계산
            # (해당 매도 기록의 timestamp 이전)
            cursor.execute('''
                SELECT s.timestamp
                FROM virtual_trading_records s
                WHERE s.id = ?
            ''', (sell_id,))
            sell_time_row = cursor.fetchone()
            if not sell_time_row:
                continue

            sell_timestamp = sell_time_row[0]

            # 해당 매도 시점까지의 평균 매수가 계산
            cursor.execute('''
                SELECT
                    SUM(b.quantity * b.price) / SUM(b.quantity) as avg_buy_price,
                    SUM(b.quantity) as total_buy_qty
                FROM virtual_trading_records b
                WHERE b.stock_code = ?
                  AND b.action = 'BUY'
                  AND b.is_test = 1
                  AND b.timestamp < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM virtual_trading_records s2
                      WHERE s2.buy_record_id = b.id
                        AND s2.action = 'SELL'
                        AND s2.timestamp < ?
                  )
            ''', (stock_code, sell_timestamp, sell_timestamp))

            avg_result = cursor.fetchone()
            if not avg_result or avg_result[0] is None:
                continue

            avg_buy_price, total_buy_qty = avg_result

            # 새로운 손익 계산
            new_profit_loss = (sell_price - avg_buy_price) * sell_qty
            new_profit_rate = ((sell_price - avg_buy_price) / avg_buy_price) * 100

            # 기존 손익 조회
            cursor.execute('''
                SELECT profit_loss, profit_rate
                FROM virtual_trading_records
                WHERE id = ?
            ''', (sell_id,))
            old_result = cursor.fetchone()
            old_profit_loss, old_profit_rate = old_result if old_result else (0, 0)

            # 업데이트
            cursor.execute('''
                UPDATE virtual_trading_records
                SET profit_loss = ?, profit_rate = ?
                WHERE id = ?
            ''', (new_profit_loss, new_profit_rate, sell_id))

            # 변경된 경우만 출력
            if abs((old_profit_rate or 0) - new_profit_rate) > 0.01:
                print(f"  {stock_code}: {old_profit_rate:+.2f}% → {new_profit_rate:+.2f}% "
                      f"(평균매수가: {avg_buy_price:,.0f}원)")
                updated_count += 1

        conn.commit()
        print(f"\n✅ 완료: {updated_count}건 업데이트됨")


def fix_real_trading_profit_rates():
    """실거래 기록의 손익률 재계산"""
    db_path = Path(__file__).parent / "data" / "robotrader.db"

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 모든 매도 기록 조회
        cursor.execute('''
            SELECT id, stock_code, quantity, price
            FROM real_trading_records
            WHERE action = 'SELL'
        ''')

        sell_records = cursor.fetchall()

        if not sell_records:
            print("실거래 매도 기록 없음")
            return

        print(f"\n총 {len(sell_records)}건의 실거래 매도 기록 재계산 중...")

        updated_count = 0
        for sell_id, stock_code, sell_qty, sell_price in sell_records:
            # 해당 매도 시점 이전의 미체결 매수 기록으로 평균 매수가 계산
            cursor.execute('''
                SELECT s.timestamp
                FROM real_trading_records s
                WHERE s.id = ?
            ''', (sell_id,))
            sell_time_row = cursor.fetchone()
            if not sell_time_row:
                continue

            sell_timestamp = sell_time_row[0]

            # 해당 매도 시점까지의 평균 매수가 계산
            cursor.execute('''
                SELECT
                    SUM(b.quantity * b.price) / SUM(b.quantity) as avg_buy_price,
                    SUM(b.quantity) as total_buy_qty
                FROM real_trading_records b
                WHERE b.stock_code = ?
                  AND b.action = 'BUY'
                  AND b.timestamp < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM real_trading_records s2
                      WHERE s2.buy_record_id = b.id
                        AND s2.action = 'SELL'
                        AND s2.timestamp < ?
                  )
            ''', (stock_code, sell_timestamp, sell_timestamp))

            avg_result = cursor.fetchone()
            if not avg_result or avg_result[0] is None:
                continue

            avg_buy_price, total_buy_qty = avg_result

            # 새로운 손익 계산
            new_profit_loss = (sell_price - avg_buy_price) * sell_qty
            new_profit_rate = ((sell_price - avg_buy_price) / avg_buy_price) * 100

            # 기존 손익 조회
            cursor.execute('''
                SELECT profit_loss, profit_rate
                FROM real_trading_records
                WHERE id = ?
            ''', (sell_id,))
            old_result = cursor.fetchone()
            old_profit_loss, old_profit_rate = old_result if old_result else (0, 0)

            # 업데이트
            cursor.execute('''
                UPDATE real_trading_records
                SET profit_loss = ?, profit_rate = ?
                WHERE id = ?
            ''', (new_profit_loss, new_profit_rate, sell_id))

            # 변경된 경우만 출력
            if abs((old_profit_rate or 0) - new_profit_rate) > 0.01:
                print(f"  {stock_code}: {old_profit_rate:+.2f}% → {new_profit_rate:+.2f}% "
                      f"(평균매수가: {avg_buy_price:,.0f}원)")
                updated_count += 1

        conn.commit()
        print(f"\n✅ 실거래 완료: {updated_count}건 업데이트됨")


if __name__ == "__main__":
    print("=" * 60)
    print("손익률 재계산 스크립트")
    print("=" * 60)

    # 가상 매매 기록 수정
    print("\n[1] 가상 매매 기록 재계산")
    fix_virtual_trading_profit_rates()

    # 실거래 기록 수정
    print("\n[2] 실거래 기록 재계산")
    fix_real_trading_profit_rates()

    print("\n" + "=" * 60)
    print("재계산 완료!")
    print("=" * 60)
