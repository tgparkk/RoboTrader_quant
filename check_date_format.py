#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
candidate_stocks 테이블의 selection_date 형식 확인
"""

import sqlite3
import os

def check_date_format():
    """데이터베이스의 날짜 형식 확인"""
    db_path = "data/robotrader.db"
    
    if not os.path.exists(db_path):
        print(f"❌ 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # selection_date 컬럼의 실제 값들 확인
        cursor.execute("""
            SELECT DISTINCT selection_date, 
                   DATE(selection_date) as date_only,
                   strftime('%Y%m%d', selection_date) as formatted_date
            FROM candidate_stocks 
            ORDER BY selection_date 
            LIMIT 10
        """)
        
        rows = cursor.fetchall()
        
        print("📊 candidate_stocks 테이블의 selection_date 형식 확인:")
        print("=" * 80)
        print(f"{'원본값':<25} {'DATE()':<12} {'strftime()':<12}")
        print("-" * 80)
        
        for row in rows:
            original, date_only, formatted = row
            print(f"{str(original):<25} {str(date_only):<12} {str(formatted):<12}")
        
        # 2025-09-05 관련 데이터 확인
        print("\n🔍 2025-09-05 관련 데이터 확인:")
        print("=" * 50)
        
        # 다양한 날짜 형식으로 테스트
        test_queries = [
            ("DATE(selection_date) = '2025-09-05'", "DATE() = '2025-09-05'"),
            ("DATE(selection_date) = '20250905'", "DATE() = '20250905'"),
            ("strftime('%Y%m%d', selection_date) = '20250905'", "strftime() = '20250905'"),
            ("selection_date LIKE '2025-09-05%'", "LIKE '2025-09-05%'"),
            ("selection_date LIKE '20250905%'", "LIKE '20250905%'")
        ]
        
        for query, description in test_queries:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM candidate_stocks WHERE {query}")
                count = cursor.fetchone()[0]
                print(f"{description:<25}: {count}개")
            except Exception as e:
                print(f"{description:<25}: 오류 - {e}")
        
        # 실제 2025-09-05 데이터 샘플 확인
        print("\n📋 2025-09-05 실제 데이터 샘플:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT stock_code, stock_name, selection_date
            FROM candidate_stocks 
            WHERE selection_date LIKE '2025-09-05%'
            LIMIT 5
        """)
        
        sample_rows = cursor.fetchall()
        for row in sample_rows:
            print(f"종목코드: {row[0]}, 종목명: {row[1]}, 날짜: {row[2]}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    check_date_format()
