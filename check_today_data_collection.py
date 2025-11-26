#!/usr/bin/env python3
"""
오늘 데이터 수집 상태 확인 스크립트
- candidate_stocks 테이블에서 오늘 날짜의 종목 조회
- 각 종목별 분봉/일봉 데이터 수집 상태 확인
"""
import sqlite3
import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import sys

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_today_candidate_stocks(db_path: str) -> List[Dict[str, str]]:
    """오늘 날짜의 후보 종목 조회"""
    try:
        today = now_kst().date()
        target_date = today.strftime('%Y-%m-%d')
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT stock_code, stock_name, selection_date, score
                FROM candidate_stocks
                WHERE DATE(selection_date) = ?
                ORDER BY score DESC
            ''', (target_date,))
            
            rows = cursor.fetchall()
            candidates = []
            for row in rows:
                candidates.append({
                    'stock_code': row[0].zfill(6),  # 6자리로 패딩
                    'stock_name': row[1],
                    'selection_date': row[2],
                    'score': row[3]
                })
            
            logger.info(f"[{target_date}] {len(candidates)}개 종목 조회")
            return candidates
            
    except Exception as e:
        logger.error(f"후보 종목 조회 실패: {e}")
        return []


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


def check_today_data_collection():
    """오늘 데이터 수집 상태 확인"""
    print("=" * 80)
    print("[데이터 수집 상태 확인]")
    print("=" * 80)
    
    # 오늘 날짜
    today = now_kst()
    today_str = today.strftime('%Y%m%d')
    today_date_str = today.strftime('%Y-%m-%d')
    
    print(f"\n[확인 날짜] {today_date_str} ({today_str})")
    print(f"[확인 시간] {today.strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    # 데이터베이스 경로
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return
    
    # 오늘 날짜의 후보 종목 조회
    candidates = get_today_candidate_stocks(str(db_path))
    
    if not candidates:
        print(f"[경고] 오늘 날짜({today_date_str})의 후보 종목이 없습니다.")
        print("   (주말/휴일이거나 아직 종목 선정이 안 된 경우일 수 있습니다)")
        return
    
    print(f"[후보 종목] {len(candidates)}개\n")
    
    # 각 종목별 데이터 확인
    results = []
    minute_ok = 0
    daily_ok = 0
    
    for candidate in candidates:
        stock_code = candidate['stock_code']
        stock_name = candidate['stock_name']
        
        # 분봉 데이터 확인
        minute_exists, minute_count, minute_info = check_minute_data(stock_code, today_str)
        if minute_exists and minute_count > 0:
            minute_ok += 1
        
        # 일봉 데이터 확인
        daily_exists, daily_count, daily_info = check_daily_data(stock_code, today_str)
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
    
    # 결과 출력
    print("=" * 80)
    print("[종목별 데이터 수집 상태]")
    print("=" * 80)
    
    for result in results:
        minute_status = "[OK]" if result['minute_exists'] and result['minute_count'] > 0 else "[누락]"
        daily_status = "[OK]" if result['daily_exists'] else "[누락]"
        
        print(f"\n[{result['stock_code']}] {result['stock_name']}")
        print(f"  분봉: {minute_status} {result['minute_info']}")
        print(f"  일봉: {daily_status} {result['daily_info']}")
    
    # 요약
    print("\n" + "=" * 80)
    print("[수집 상태 요약]")
    print("=" * 80)
    print(f"전체 종목 수: {len(candidates)}개")
    if len(candidates) > 0:
        print(f"분봉 데이터 수집: {minute_ok}/{len(candidates)}개 ({minute_ok/len(candidates)*100:.1f}%)")
        print(f"일봉 데이터 수집: {daily_ok}/{len(candidates)}개 ({daily_ok/len(candidates)*100:.1f}%)")
    
    # 문제가 있는 종목
    missing_minute = [r for r in results if not r['minute_exists'] or r['minute_count'] == 0]
    missing_daily = [r for r in results if not r['daily_exists']]
    
    if missing_minute:
        print(f"\n[경고] 분봉 데이터 누락: {len(missing_minute)}개")
        for r in missing_minute:
            print(f"  - {r['stock_code']} {r['stock_name']}: {r['minute_info']}")
    
    if missing_daily:
        print(f"\n[경고] 일봉 데이터 누락: {len(missing_daily)}개")
        for r in missing_daily:
            print(f"  - {r['stock_code']} {r['stock_name']}: {r['daily_info']}")
    
    # 최종 판단
    print("\n" + "=" * 80)
    if len(candidates) > 0:
        if minute_ok == len(candidates) and daily_ok == len(candidates):
            print("[성공] 모든 종목의 데이터 수집이 완료되었습니다!")
        elif minute_ok == 0 and daily_ok == 0:
            print("[실패] 데이터 수집이 전혀 되지 않았습니다. 수집 스크립트를 실행해주세요.")
        else:
            print("[부분 성공] 일부 종목의 데이터가 누락되었습니다. 확인이 필요합니다.")
    print("=" * 80)


if __name__ == "__main__":
    check_today_data_collection()

