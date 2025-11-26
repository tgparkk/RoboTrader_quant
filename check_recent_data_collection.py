#!/usr/bin/env python3
"""
최근 며칠간 데이터 수집 상태 확인 스크립트
"""
import sqlite3
import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import sys

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_recent_candidate_stocks(db_path: str, days: int = 7) -> Dict[str, List[Dict[str, str]]]:
    """최근 며칠간의 후보 종목 조회"""
    try:
        today = now_kst().date()
        results = {}
        
        with sqlite3.connect(db_path) as conn:
            for i in range(days):
                target_date = today - timedelta(days=i)
                target_date_str = target_date.strftime('%Y-%m-%d')
                
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT stock_code, stock_name, selection_date, score
                    FROM candidate_stocks
                    WHERE DATE(selection_date) = ?
                    ORDER BY score DESC
                ''', (target_date_str,))
                
                rows = cursor.fetchall()
                candidates = []
                for row in rows:
                    candidates.append({
                        'stock_code': row[0].zfill(6),
                        'stock_name': row[1],
                        'selection_date': row[2],
                        'score': row[3]
                    })
                
                if candidates:
                    results[target_date_str] = candidates
        
        return results
            
    except Exception as e:
        logger.error(f"후보 종목 조회 실패: {e}")
        return {}


def check_minute_data(stock_code: str, date_str: str) -> Tuple[bool, int, str]:
    """분봉 데이터 확인"""
    try:
        minute_cache_dir = project_root / "cache" / "minute_data"
        cache_file = minute_cache_dir / f"{stock_code}_{date_str}.pkl"
        
        if not cache_file.exists():
            return False, 0, "파일 없음"
        
        with open(cache_file, 'rb') as f:
            df = pickle.load(f)
        
        if df is None or df.empty:
            return False, 0, "빈 데이터"
        
        # 날짜 필터링 확인
        date_count = 0
        if 'date' in df.columns:
            date_count = len(df[df['date'].astype(str) == date_str])
        elif 'datetime' in df.columns:
            df['date_str'] = pd.to_datetime(df['datetime']).dt.strftime('%Y%m%d')
            date_count = len(df[df['date_str'] == date_str])
        
        return True, date_count, f"{len(df)}건 (당일: {date_count}건)"
        
    except Exception as e:
        return False, 0, f"오류: {e}"


def check_daily_data(stock_code: str, date_str: str) -> Tuple[bool, int, str]:
    """일봉 데이터 확인"""
    try:
        daily_cache_dir = project_root / "cache" / "daily"
        cache_file = daily_cache_dir / f"{stock_code}_{date_str}_daily.pkl"
        
        if not cache_file.exists():
            return False, 0, "파일 없음"
        
        with open(cache_file, 'rb') as f:
            df = pickle.load(f)
        
        if df is None or df.empty:
            return False, 0, "빈 데이터"
        
        # 최신 날짜 확인
        latest_date = None
        if 'stck_bsop_date' in df.columns:
            latest_date = df['stck_bsop_date'].max()
        elif 'date' in df.columns:
            latest_date = df['date'].max()
        
        date_info = f"최신: {latest_date}" if latest_date else ""
        return True, len(df), f"{len(df)}일치 {date_info}"
        
    except Exception as e:
        return False, 0, f"오류: {e}"


def check_recent_data_collection(days: int = 7):
    """최근 며칠간 데이터 수집 상태 확인"""
    print("=" * 80)
    print("[최근 데이터 수집 상태 확인]")
    print("=" * 80)
    
    # 데이터베이스 경로
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return
    
    # 최근 며칠간의 후보 종목 조회
    date_candidates = get_recent_candidate_stocks(str(db_path), days)
    
    if not date_candidates:
        print(f"[경고] 최근 {days}일간의 후보 종목이 없습니다.")
        return
    
    print(f"\n[확인 기간] 최근 {days}일")
    print(f"[발견된 날짜] {len(date_candidates)}일\n")
    
    # 날짜별로 확인
    for date_str in sorted(date_candidates.keys(), reverse=True):
        candidates = date_candidates[date_str]
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_ymd = date_obj.strftime('%Y%m%d')
        
        print("=" * 80)
        print(f"[날짜] {date_str} ({date_ymd}) - {len(candidates)}개 종목")
        print("=" * 80)
        
        minute_ok = 0
        daily_ok = 0
        results = []
        
        for candidate in candidates:
            stock_code = candidate['stock_code']
            stock_name = candidate['stock_name']
            
            # 분봉 데이터 확인
            minute_exists, minute_count, minute_info = check_minute_data(stock_code, date_ymd)
            if minute_exists and minute_count > 0:
                minute_ok += 1
            
            # 일봉 데이터 확인
            daily_exists, daily_count, daily_info = check_daily_data(stock_code, date_ymd)
            if daily_exists:
                daily_ok += 1
            
            results.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'minute_exists': minute_exists,
                'minute_count': minute_count,
                'minute_info': minute_info,
                'daily_exists': daily_exists,
                'daily_count': daily_count,
                'daily_info': daily_info
            })
        
        # 종목별 결과 출력
        for result in results:
            minute_status = "[OK]" if result['minute_exists'] and result['minute_count'] > 0 else "[누락]"
            daily_status = "[OK]" if result['daily_exists'] else "[누락]"
            
            print(f"  [{result['stock_code']}] {result['stock_name']}")
            print(f"    분봉: {minute_status} {result['minute_info']}")
            print(f"    일봉: {daily_status} {result['daily_info']}")
        
        # 요약
        print(f"\n  [요약] 분봉: {minute_ok}/{len(candidates)}개 ({minute_ok/len(candidates)*100:.1f}%), 일봉: {daily_ok}/{len(candidates)}개 ({daily_ok/len(candidates)*100:.1f}%)")
        
        # 문제가 있는 종목
        missing_minute = [r for r in results if not r['minute_exists'] or r['minute_count'] == 0]
        missing_daily = [r for r in results if not r['daily_exists']]
        
        if missing_minute:
            print(f"  [경고] 분봉 누락: {len(missing_minute)}개")
        if missing_daily:
            print(f"  [경고] 일봉 누락: {len(missing_daily)}개")
        
        print()
    
    # 전체 요약
    print("=" * 80)
    print("[전체 요약]")
    print("=" * 80)
    
    total_dates = len(date_candidates)
    total_stocks = sum(len(c) for c in date_candidates.values())
    
    print(f"확인한 날짜: {total_dates}일")
    print(f"전체 종목 수: {total_stocks}개")
    
    # 날짜별 통계
    for date_str in sorted(date_candidates.keys(), reverse=True):
        candidates = date_candidates[date_str]
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_ymd = date_obj.strftime('%Y%m%d')
        
        minute_ok = 0
        daily_ok = 0
        
        for candidate in candidates:
            stock_code = candidate['stock_code']
            minute_exists, minute_count, _ = check_minute_data(stock_code, date_ymd)
            daily_exists, _, _ = check_daily_data(stock_code, date_ymd)
            
            if minute_exists and minute_count > 0:
                minute_ok += 1
            if daily_exists:
                daily_ok += 1
        
        print(f"  {date_str}: 분봉 {minute_ok}/{len(candidates)}, 일봉 {daily_ok}/{len(candidates)}")
    
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='최근 며칠간 데이터 수집 상태 확인')
    parser.add_argument('--days', type=int, default=7, help='확인할 일수 (기본: 7일)')
    args = parser.parse_args()
    
    check_recent_data_collection(args.days)


