"""
보유 종목 대차대조표 데이터 수집 스크립트
"""
import sys
import os

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.ml_data_collector import MLDataCollector
from db.database_manager import DatabaseManager
import pandas as pd

def main():
    print("=" * 60)
    print("보유 종목 대차대조표 데이터 수집")
    print("=" * 60)

    # DatabaseManager 초기화
    db_manager = DatabaseManager('data/robotrader.db')

    # 보유 종목 조회
    print("\n1. 보유 종목 조회 중...")
    holdings = db_manager.get_virtual_open_positions()

    if holdings.empty:
        print("[WARNING] 보유 종목이 없습니다.")
        return

    stock_codes = holdings['stock_code'].unique().tolist()
    print(f"[OK] 보유 종목 {len(stock_codes)}개 확인:")
    for idx, row in holdings.iterrows():
        print(f"  - {row['stock_code']} {row['stock_name']}: {row['quantity']:,}주 @ {row['buy_price']:,.0f}원")

    # MLDataCollector 초기화
    print("\n2. 데이터 수집기 초기화 중...")
    collector = MLDataCollector(db_path='data/robotrader.db')

    # 각 종목별 재무 데이터 수집
    print("\n3. 대차대조표 데이터 수집 시작...")
    success_count = 0
    fail_count = 0

    for idx, stock_code in enumerate(stock_codes, 1):
        stock_name = holdings[holdings['stock_code'] == stock_code]['stock_name'].iloc[0]
        print(f"\n[{idx}/{len(stock_codes)}] {stock_code} {stock_name}")

        try:
            result = collector.save_financial_data(stock_code)
            if result:
                print(f"  [OK] 성공")
                success_count += 1
            else:
                print(f"  [WARNING] 데이터 없음")
                fail_count += 1
        except Exception as e:
            print(f"  [ERROR] 오류: {e}")
            fail_count += 1

        # API 호출 제한 대비 대기
        if idx < len(stock_codes):
            import time
            time.sleep(0.2)

    # 결과 요약
    print("\n" + "=" * 60)
    print("수집 완료")
    print("=" * 60)
    print(f"총 종목 수: {len(stock_codes)}개")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")

    # 데이터 확인
    print("\n4. 저장된 대차대조표 데이터 확인...")
    import psycopg2
    conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader_quant', user='postgres', password='postgres')

    for stock_code in stock_codes[:3]:  # 처음 3개만 샘플 확인
        query = f"""
        SELECT stock_code, report_date,
               total_assets, current_assets, current_liabilities,
               total_liabilities, total_equity
        FROM financial_statements
        WHERE stock_code = '{stock_code}'
        ORDER BY report_date DESC
        LIMIT 1
        """
        df = pd.read_sql_query(query, conn)

        if not df.empty:
            row = df.iloc[0]
            print(f"\n{stock_code} ({row['report_date']}):")
            if pd.notna(row['total_assets']) and row['total_assets'] > 0:
                print(f"  자산총계: {row['total_assets']:,.0f}")
                print(f"  유동자산: {row['current_assets']:,.0f}")
                print(f"  유동부채: {row['current_liabilities']:,.0f}")
                if row['current_liabilities'] > 0:
                    current_ratio = (row['current_assets'] / row['current_liabilities']) * 100
                    print(f"  유동비율: {current_ratio:.1f}%")
            else:
                print(f"  [WARNING] 대차대조표 데이터 없음")

    conn.close()
    print("\n완료!")

if __name__ == "__main__":
    main()
