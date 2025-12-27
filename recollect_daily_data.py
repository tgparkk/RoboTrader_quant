"""
보유 종목 일봉 데이터 재수집 (시가총액 NULL 해결)
"""
import sys
import os
import time

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.ml_data_collector import MLDataCollector
from db.database_manager import DatabaseManager

def main():
    print("=" * 80)
    print("보유 종목 일봉 데이터 재수집 (시가총액 업데이트)")
    print("=" * 80)
    print()

    # 1. 보유 종목 조회
    print("1. 보유 종목 조회 중...")
    db_manager = DatabaseManager('data/robotrader.db')
    holdings = db_manager.get_virtual_open_positions()

    if holdings.empty:
        print("  [WARNING] 보유 종목이 없습니다.")
        return

    stock_codes = holdings['stock_code'].unique().tolist()
    print(f"  [OK] {len(stock_codes)}개 종목 확인")
    print()

    # 종목 정보 출력
    for _, row in holdings.iterrows():
        stock_code = row['stock_code']
        stock_name = row.get('stock_name', f'Stock_{stock_code}')
        quantity = int(row['quantity'])
        buy_price = int(row['buy_price'])
        print(f"  - {stock_code} {stock_name}: {quantity}주 @ {buy_price:,}원")
    print()

    # 2. 데이터 수집기 초기화
    print("2. 데이터 수집기 초기화 중...")
    collector = MLDataCollector(db_path='data/robotrader.db')
    print("  [OK] 초기화 완료")
    print()

    # 3. 일봉 데이터 재수집
    print("3. 일봉 데이터 재수집 중...")
    print()

    success_count = 0
    fail_count = 0

    for i, stock_code in enumerate(stock_codes, 1):
        stock_name = holdings[holdings['stock_code'] == stock_code]['stock_name'].iloc[0] if 'stock_name' in holdings.columns else f'Stock_{stock_code}'

        print(f"[{i}/{len(stock_codes)}] {stock_code} {stock_name}")

        try:
            # 일봉 데이터 재수집 (최근 7일)
            result = collector.save_daily_price_data(stock_code)

            if result:
                print(f"  [OK] 수집 완료")
                success_count += 1
            else:
                print(f"  [WARNING] 수집 실패")
                fail_count += 1

            # API 호출 간격 (0.2초)
            if i < len(stock_codes):
                time.sleep(0.2)

        except Exception as e:
            print(f"  [ERROR] 오류 발생: {e}")
            fail_count += 1

        print()

    # 4. 결과 요약
    print("=" * 80)
    print("재수집 완료")
    print("=" * 80)
    print(f"총 종목 수: {len(stock_codes)}개")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")
    print()

    # 5. 시가총액 업데이트 확인
    print("5. 시가총액 업데이트 확인 중...")
    print()

    import sqlite3
    with sqlite3.connect('data/robotrader.db') as conn:
        cursor = conn.cursor()

        # 최근 데이터 NULL 비율 확인
        cursor.execute('''
            SELECT
              COUNT(*) as total_records,
              SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) as null_count,
              ROUND(SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as null_percentage
            FROM daily_prices
            WHERE date >= '2025-12-23'
        ''')

        row = cursor.fetchone()
        total_records, null_count, null_percentage = row

        print(f"최근 데이터 (2025-12-23 이후):")
        print(f"  총 레코드: {total_records:,}건")
        print(f"  NULL/0 개수: {null_count:,}건")
        print(f"  NULL 비율: {null_percentage}%")

        if null_percentage == 0:
            print("  [OK] 시가총액이 모든 날짜에 저장되었습니다!")
        elif null_percentage < 10:
            print("  [WARNING] 일부 날짜에 시가총액이 없습니다.")
        else:
            print("  [ERROR] 여전히 많은 NULL이 있습니다.")

        print()

        # 샘플 데이터 출력
        print("샘플 데이터 (최근 10건):")
        cursor.execute('''
            SELECT stock_code, date, close, market_cap
            FROM daily_prices
            WHERE date >= '2025-12-23'
            ORDER BY date DESC, stock_code
            LIMIT 10
        ''')

        print(f"{'종목코드':<10} {'날짜':<12} {'종가':>12} {'시가총액':>20}")
        print("-" * 60)

        for row in cursor.fetchall():
            stock_code, date, close, market_cap = row
            market_cap_str = f"{market_cap:,.0f}원" if market_cap else "NULL"
            status = "" if market_cap else " [ERROR]"
            print(f"{stock_code:<10} {date:<12} {close:>12,.0f} {market_cap_str:>20}{status}")

    print()
    print("=" * 80)
    print("완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
