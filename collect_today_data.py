#!/usr/bin/env python3
"""
오늘자 데이터 수집 스크립트
- candidate_stocks에서 오늘 날짜의 종목 조회
- 일봉 데이터 수집 및 캐시 저장
- 분봉 데이터는 장중에만 수집 가능 (현재는 일봉만 수집)
"""
import sqlite3
import sys
from pathlib import Path
from typing import List

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger
from core.post_market_data_saver import PostMarketDataSaver

logger = setup_logger(__name__)


def get_today_candidate_stocks(db_path: str) -> List[str]:
    """오늘 날짜의 후보 종목 코드 리스트 조회"""
    try:
        today = now_kst().date()
        target_date = today.strftime('%Y-%m-%d')
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT stock_code
                FROM candidate_stocks
                WHERE DATE(selection_date) = ?
                ORDER BY score DESC
            ''', (target_date,))
            
            stock_codes = [row[0].zfill(6) for row in cursor.fetchall()]
            
            logger.info(f"[{target_date}] {len(stock_codes)}개 종목 조회")
            return stock_codes
            
    except Exception as e:
        logger.error(f"후보 종목 조회 실패: {e}")
        return []


def collect_today_data():
    """오늘자 데이터 수집"""
    print("=" * 80)
    print("[오늘자 데이터 수집]")
    print("=" * 80)
    
    # 오늘 날짜
    today = now_kst()
    today_str = today.strftime('%Y%m%d')
    today_date_str = today.strftime('%Y-%m-%d')
    
    print(f"\n[수집 날짜] {today_date_str} ({today_str})")
    print(f"[수집 시간] {today.strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    # 데이터베이스 경로
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return
    
    # 오늘 날짜의 후보 종목 조회
    stock_codes = get_today_candidate_stocks(str(db_path))
    
    if not stock_codes:
        print(f"[경고] 오늘 날짜({today_date_str})의 후보 종목이 없습니다.")
        print("   (주말/휴일이거나 아직 종목 선정이 안 된 경우일 수 있습니다)")
        return
    
    print(f"[후보 종목] {len(stock_codes)}개")
    print(f"  종목 코드: {', '.join(stock_codes)}\n")
    
    # PostMarketDataSaver 초기화
    data_saver = PostMarketDataSaver()
    
    # 일봉 데이터 수집
    print("=" * 80)
    print("[1️⃣ 일봉 데이터 수집]")
    print("=" * 80)
    daily_result = data_saver.save_daily_data(stock_codes, today_str, days_back=100)
    
    print("\n" + "=" * 80)
    print("[수집 결과 요약]")
    print("=" * 80)
    print(f"전체 종목 수: {daily_result['total']}개")
    print(f"일봉 데이터 수집 성공: {daily_result['saved']}개")
    print(f"일봉 데이터 수집 실패: {daily_result['failed']}개")
    
    if daily_result['failed'] > 0:
        print(f"\n[경고] {daily_result['failed']}개 종목의 일봉 데이터 수집에 실패했습니다.")
    
    # 분봉 데이터 안내
    print("\n" + "=" * 80)
    print("[참고] 분봉 데이터")
    print("=" * 80)
    print("분봉 데이터는 장중에만 수집 가능합니다.")
    print("장 마감 후에는 분봉 데이터를 수집할 수 없습니다.")
    print("(장중에 main.py가 실행 중이었다면 자동으로 수집되었을 수 있습니다)")
    
    print("\n" + "=" * 80)
    if daily_result['saved'] == daily_result['total']:
        print("[성공] 모든 종목의 일봉 데이터 수집이 완료되었습니다!")
    elif daily_result['saved'] > 0:
        print("[부분 성공] 일부 종목의 일봉 데이터가 수집되었습니다.")
    else:
        print("[실패] 일봉 데이터 수집에 실패했습니다.")
    print("=" * 80)


if __name__ == "__main__":
    try:
        collect_today_data()
    except Exception as e:
        logger.error(f"데이터 수집 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

