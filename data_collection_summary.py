#!/usr/bin/env python3
"""
데이터 수집 상태 요약 리포트
"""
import sqlite3
import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import sys

project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_recent_dates_with_stocks(db_path: str, days: int = 7) -> Dict[str, int]:
    """최근 며칠간 종목이 있는 날짜 조회"""
    try:
        today = now_kst().date()
        start_date = (today - timedelta(days=days)).strftime('%Y-%m-%d')
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DATE(selection_date) as date, COUNT(DISTINCT stock_code) as cnt
                FROM candidate_stocks
                WHERE DATE(selection_date) >= ?
                GROUP BY DATE(selection_date)
                ORDER BY date DESC
            ''', (start_date,))
            
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.error(f"날짜 조회 실패: {e}")
        return {}


def check_minute_data(stock_code: str, date_str: str) -> Tuple[bool, int]:
    """분봉 데이터 확인"""
    try:
        minute_cache_dir = project_root / "cache" / "minute_data"
        cache_file = minute_cache_dir / f"{stock_code}_{date_str}.pkl"
        
        if not cache_file.exists():
            return False, 0
        
        with open(cache_file, 'rb') as f:
            df = pickle.load(f)
        
        if df is None or df.empty:
            return False, 0
        
        # 날짜 필터링 확인
        date_count = 0
        if 'date' in df.columns:
            date_count = len(df[df['date'].astype(str) == date_str])
        elif 'datetime' in df.columns:
            df['date_str'] = pd.to_datetime(df['datetime']).dt.strftime('%Y%m%d')
            date_count = len(df[df['date_str'] == date_str])
        
        return date_count > 0, date_count
    except:
        return False, 0


def check_daily_data(stock_code: str, date_str: str) -> bool:
    """일봉 데이터 확인"""
    try:
        daily_cache_dir = project_root / "cache" / "daily"
        cache_file = daily_cache_dir / f"{stock_code}_{date_str}_daily.pkl"
        return cache_file.exists()
    except:
        return False


def get_stocks_by_date(db_path: str, date_str: str) -> List[str]:
    """특정 날짜의 종목 코드 리스트"""
    try:
        if len(date_str) == 8:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            target_date = date_obj.strftime('%Y-%m-%d')
        else:
            target_date = date_str
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT stock_code
                FROM candidate_stocks
                WHERE DATE(selection_date) = ?
            ''', (target_date,))
            
            return [row[0].zfill(6) for row in cursor.fetchall()]
    except:
        return []


def generate_summary(days: int = 7):
    """데이터 수집 상태 요약 리포트 생성"""
    print("=" * 80)
    print("[데이터 수집 상태 요약 리포트]")
    print("=" * 80)
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return
    
    # 최근 며칠간 종목이 있는 날짜 조회
    date_stocks = get_recent_dates_with_stocks(str(db_path), days)
    
    if not date_stocks:
        print(f"[경고] 최근 {days}일간의 후보 종목이 없습니다.")
        return
    
    print(f"\n[확인 기간] 최근 {days}일")
    print(f"[발견된 날짜] {len(date_stocks)}일\n")
    
    # 날짜별로 확인
    summary_data = []
    
    for date_str in sorted(date_stocks.keys(), reverse=True):
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_ymd = date_obj.strftime('%Y%m%d')
        total_stocks = date_stocks[date_str]
        
        stocks = get_stocks_by_date(str(db_path), date_str)
        
        minute_ok = 0
        daily_ok = 0
        
        for stock_code in stocks:
            minute_exists, minute_count = check_minute_data(stock_code, date_ymd)
            daily_exists = check_daily_data(stock_code, date_ymd)
            
            if minute_exists and minute_count > 0:
                minute_ok += 1
            if daily_exists:
                daily_ok += 1
        
        summary_data.append({
            'date': date_str,
            'date_ymd': date_ymd,
            'total': total_stocks,
            'minute_ok': minute_ok,
            'daily_ok': daily_ok,
            'minute_pct': (minute_ok / total_stocks * 100) if total_stocks > 0 else 0,
            'daily_pct': (daily_ok / total_stocks * 100) if total_stocks > 0 else 0
        })
    
    # 결과 출력
    print("=" * 80)
    print("[날짜별 수집 상태]")
    print("=" * 80)
    print(f"{'날짜':<12} {'종목수':<8} {'분봉':<12} {'일봉':<12} {'상태':<10}")
    print("-" * 80)
    
    for data in summary_data:
        status = "완료" if data['minute_ok'] == data['total'] and data['daily_ok'] == data['total'] else "부분"
        if data['minute_ok'] == 0 and data['daily_ok'] == 0:
            status = "누락"
        
        print(f"{data['date']:<12} {data['total']:<8} "
              f"{data['minute_ok']}/{data['total']} ({data['minute_pct']:.1f}%)  "
              f"{data['daily_ok']}/{data['total']} ({data['daily_pct']:.1f}%)  "
              f"{status:<10}")
    
    # 문제가 있는 날짜
    missing_dates = [d for d in summary_data if d['minute_ok'] == 0 and d['daily_ok'] == 0]
    partial_dates = [d for d in summary_data if (d['minute_ok'] < d['total'] or d['daily_ok'] < d['total']) and (d['minute_ok'] > 0 or d['daily_ok'] > 0)]
    
    print("\n" + "=" * 80)
    print("[요약]")
    print("=" * 80)
    
    total_dates = len(summary_data)
    complete_dates = len([d for d in summary_data if d['minute_ok'] == d['total'] and d['daily_ok'] == d['total']])
    
    print(f"확인한 날짜: {total_dates}일")
    print(f"완전 수집: {complete_dates}일 ({complete_dates/total_dates*100:.1f}%)")
    
    if missing_dates:
        print(f"\n[경고] 데이터가 전혀 수집되지 않은 날짜: {len(missing_dates)}일")
        for d in missing_dates:
            print(f"  - {d['date']} ({d['total']}개 종목)")
    
    if partial_dates:
        print(f"\n[주의] 일부 종목만 수집된 날짜: {len(partial_dates)}일")
        for d in partial_dates:
            print(f"  - {d['date']}: 분봉 {d['minute_ok']}/{d['total']}, 일봉 {d['daily_ok']}/{d['total']}")
    
    # 최종 판단
    print("\n" + "=" * 80)
    if complete_dates == total_dates:
        print("[결론] 모든 날짜의 데이터 수집이 완료되었습니다!")
    elif missing_dates:
        print(f"[결론] {len(missing_dates)}일의 데이터가 누락되었습니다. 수집 스크립트를 실행해주세요.")
    else:
        print("[결론] 대부분의 데이터는 수집되었으나, 일부 누락이 있습니다.")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='데이터 수집 상태 요약 리포트')
    parser.add_argument('--days', type=int, default=7, help='확인할 일수 (기본: 7일)')
    args = parser.parse_args()
    
    generate_summary(args.days)

