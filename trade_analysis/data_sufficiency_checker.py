#!/usr/bin/env python3
"""
데이터 충분성 검사 및 수집 모듈
메인 프로그램에서 쉽게 사용할 수 있는 간단한 인터페이스 제공
"""

import os
import sys
import pandas as pd
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_auth import KisAuth
from api.kis_chart_api import get_historical_minute_data, get_inquire_time_dailychartprice

logger = setup_logger(__name__)


def check_minute_data_sufficiency(stock_code: str, date_str: str, required_count: int = 15) -> bool:
    """
    분봉 데이터 충분성 검사
    
    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD)
        required_count: 필요한 최소 데이터 개수
        
    Returns:
        bool: 데이터가 충분한지 여부
    """
    try:
        # 분봉 캐시 파일 경로
        minute_cache_dir = project_root / "cache" / "minute_data"
        cache_file = minute_cache_dir / f"{stock_code}_{date_str}.pkl"
        
        if not cache_file.exists():
            logger.warning(f"❌ {stock_code} {date_str} 분봉 캐시 파일 없음")
            return False
        
        # 캐시에서 데이터 로드
        with open(cache_file, 'rb') as f:
            minute_data = pickle.load(f)
        
        if not isinstance(minute_data, pd.DataFrame) or minute_data.empty:
            logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 없음")
            return False
        
        data_count = len(minute_data)
        
        # 기본 개수 확인
        if data_count < required_count:
            logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {data_count}개 (최소 {required_count}개 필요)")
            return False
        
        # 현재 시간과 비교하여 데이터가 최신인지 확인
        current_time = now_kst()
        current_date = current_time.strftime('%Y%m%d')
        
        if date_str == current_date:
            # 오늘 날짜인 경우 현재 시간까지의 데이터가 있는지 확인
            current_hour = current_time.hour
            current_minute = current_time.minute
            
            # 장 시작 시간 (09:00) 이후인 경우
            if current_hour >= 9:
                # 현재 시간까지 예상되는 분봉 개수 계산
                if current_hour < 15 or (current_hour == 15 and current_minute <= 30):
                    # 장중인 경우: 09:00부터 현재까지의 분봉 개수
                    expected_count = (current_hour - 9) * 60 + current_minute
                    if data_count < expected_count * 0.8:  # 80% 이상 있어야 충분하다고 판단
                        logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {data_count}개 (예상 {expected_count}개)")
                        return False
                else:
                    # 장 마감 후인 경우: 09:00~15:30 (390분)
                    if data_count < 350:  # 350개 이상 있어야 충분하다고 판단
                        logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {data_count}개 (장 마감 후 최소 350개 필요)")
                        return False
        
        logger.debug(f"✅ {stock_code} {date_str} 분봉 데이터 충분: {data_count}개")
        return True
        
    except Exception as e:
        logger.error(f"분봉 데이터 충분성 검사 실패 ({stock_code}, {date_str}): {e}")
        return False


def collect_minute_data_from_api(stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
    """
    API에서 분봉 데이터 수집
    
    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD)
        
    Returns:
        pd.DataFrame: 분봉 데이터 또는 None
    """
    try:
        # API 인증
        kis_auth = KisAuth()
        if not kis_auth.initialize():
            logger.error("KIS API 인증 실패")
            return None
        
        # 분봉 데이터 조회 (당일 데이터만)
        result = get_historical_minute_data(
            stock_code=stock_code,
            target_date=date_str,
            end_hour="160000",
            past_data_yn="Y"
        )
        
        if result is not None and not result.empty:
            logger.info(f"✅ {stock_code} {date_str} 분봉 데이터 수집 완료: {len(result)}건")
            return result
        else:
            logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 수집 실패")
            return None
            
    except Exception as e:
        logger.error(f"분봉 데이터 수집 실패 ({stock_code}, {date_str}): {e}")
        return None


def ensure_sufficient_minute_data(stock_code: str, date_str: str = None, required_count: int = 15, use_api: bool = True) -> bool:
    """
    분봉 데이터 충분성 확인 및 필요시 수집
    
    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD), None이면 오늘 날짜
        required_count: 필요한 최소 분봉 개수
        use_api: API 사용 여부
        
    Returns:
        bool: 데이터가 충분한지 여부
    """
    try:
        if date_str is None:
            date_str = now_kst().strftime('%Y%m%d')
        
        # 1. 현재 데이터 충분성 검사
        if check_minute_data_sufficiency(stock_code, date_str, required_count):
            return True
        
        # 2. 데이터가 부족한 경우 API에서 수집
        if use_api:
            logger.info(f"🔄 {stock_code} 분봉 데이터 부족으로 API 수집 시작...")
            minute_data = collect_minute_data_from_api(stock_code, date_str)
            
            if minute_data is not None and not minute_data.empty:
                # 다시 충분성 검사
                if check_minute_data_sufficiency(stock_code, date_str, required_count):
                    logger.info(f"✅ {stock_code} 분봉 데이터 수집 완료")
                    return True
                else:
                    logger.warning(f"❌ {stock_code} 분봉 데이터 수집 후에도 부족")
                    return False
            else:
                logger.error(f"❌ {stock_code} 분봉 데이터 수집 실패")
                return False
        else:
            logger.warning(f"❌ {stock_code} 분봉 데이터 부족하고 API 사용 안함")
            return False
            
    except Exception as e:
        logger.error(f"분봉 데이터 충분성 확인 실패 ({stock_code}, {date_str}): {e}")
        return False


# 메인 프로그램에서 사용할 수 있는 간단한 함수들
def check_and_collect_data(stock_code: str, date_str: str = None, required_count: int = 15) -> bool:
    """
    종목 데이터 확인 및 필요시 수집 (메인 프로그램용)
    
    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD), None이면 오늘 날짜
        required_count: 필요한 최소 분봉 개수
        
    Returns:
        bool: 데이터가 충분한지 여부
    """
    return ensure_sufficient_minute_data(stock_code, date_str, required_count, True)


if __name__ == "__main__":
    # 테스트
    from utils.korean_time import now_kst
    
    today = now_kst().strftime('%Y%m%d')
    print(f"오늘 날짜: {today}")
    
    # 테스트 종목
    stock_code = "042520"
    result = check_and_collect_data(stock_code, today, 15)
    print(f"{stock_code} 데이터 충분성: {result}")
