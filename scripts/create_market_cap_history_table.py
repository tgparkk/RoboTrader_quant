"""
시가총액 이력 테이블 생성

Look-ahead Bias 제거를 위해 시가총액을 별도 테이블로 관리합니다.
"""
import sys
import os
import sqlite3

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def create_market_cap_history_table():
    """시가총액 이력 테이블 생성"""
    db_path = 'data/robotrader.db'

    print("=" * 80)
    print("시가총액 이력 테이블 생성")
    print("=" * 80)
    print()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. 테이블 존재 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_cap_history'")
        if cursor.fetchone():
            print("⚠️ market_cap_history 테이블이 이미 존재합니다.")
            response = input("기존 테이블을 삭제하고 재생성하시겠습니까? (y/N): ")
            if response.lower() != 'y':
                print("취소되었습니다.")
                return

            cursor.execute("DROP TABLE market_cap_history")
            print("✅ 기존 테이블 삭제 완료")

        # 2. 테이블 생성
        cursor.execute('''
            CREATE TABLE market_cap_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code VARCHAR(10) NOT NULL,
                date TEXT NOT NULL,
                market_cap BIGINT NOT NULL,
                current_price INTEGER,
                listed_shares BIGINT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_code, date)
            )
        ''')

        # 3. 인덱스 생성
        cursor.execute('CREATE INDEX idx_market_cap_history_code_date ON market_cap_history(stock_code, date)')
        cursor.execute('CREATE INDEX idx_market_cap_history_date ON market_cap_history(date)')

        conn.commit()

        print("✅ market_cap_history 테이블 생성 완료")
        print()
        print("테이블 구조:")
        print("  - stock_code: 종목코드")
        print("  - date: 날짜 (YYYY-MM-DD)")
        print("  - market_cap: 시가총액 (원)")
        print("  - current_price: 현재가 (원)")
        print("  - listed_shares: 상장주식수")
        print("  - created_at: 생성일시")
        print()

        # 4. daily_prices 테이블의 기존 시가총액 데이터 마이그레이션
        print("4. 기존 시가총액 데이터 마이그레이션 중...")
        cursor.execute('''
            SELECT stock_code, date, market_cap, close
            FROM daily_prices
            WHERE market_cap IS NOT NULL AND market_cap > 0
            ORDER BY date DESC
        ''')

        rows = cursor.fetchall()
        migrated_count = 0

        for stock_code, date, market_cap, close_price in rows:
            try:
                # 상장주식수 계산 (시가총액 / 종가)
                listed_shares = int(market_cap / close_price) if close_price > 0 else None

                cursor.execute('''
                    INSERT OR IGNORE INTO market_cap_history
                    (stock_code, date, market_cap, current_price, listed_shares)
                    VALUES (?, ?, ?, ?, ?)
                ''', (stock_code, date, market_cap, close_price, listed_shares))

                if cursor.rowcount > 0:
                    migrated_count += 1
            except Exception as e:
                print(f"  ⚠️ [{stock_code}] {date} 마이그레이션 실패: {e}")

        conn.commit()

        print(f"✅ 마이그레이션 완료: {migrated_count:,}건")
        print()

        # 5. 통계 확인
        cursor.execute('''
            SELECT
                COUNT(DISTINCT stock_code) as stock_count,
                COUNT(*) as total_records,
                MIN(date) as min_date,
                MAX(date) as max_date
            FROM market_cap_history
        ''')

        stock_count, total_records, min_date, max_date = cursor.fetchone()

        print("=" * 80)
        print("마이그레이션 결과")
        print("=" * 80)
        print(f"종목 수: {stock_count:,}개")
        print(f"총 레코드: {total_records:,}건")
        print(f"날짜 범위: {min_date} ~ {max_date}")
        print()

        # 샘플 데이터 출력
        print("샘플 데이터 (최근 10건):")
        cursor.execute('''
            SELECT stock_code, date, market_cap, current_price
            FROM market_cap_history
            ORDER BY date DESC, stock_code
            LIMIT 10
        ''')

        print(f"{'종목코드':<10} {'날짜':<12} {'시가총액':>20} {'현재가':>12}")
        print("-" * 60)

        for row in cursor.fetchall():
            stock_code, date, market_cap, current_price = row
            print(f"{stock_code:<10} {date:<12} {market_cap:>20,} {current_price:>12,}")

        print()
        print("=" * 80)
        print("완료!")
        print("=" * 80)


if __name__ == "__main__":
    create_market_cap_history_table()
