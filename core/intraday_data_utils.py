"""
장중 데이터 검증 및 유틸리티 함수

IntradayStockManager에서 사용하는 독립적인 유틸리티 함수들
"""
from typing import List, Optional
import pandas as pd
from utils.logger import setup_logger


def calculate_time_range_minutes(start_time: str, end_time: str) -> int:
    """
    시작 시간과 종료 시간 사이의 분 수 계산

    Args:
        start_time: 시작시간 (HHMMSS 형식)
        end_time: 종료시간 (HHMMSS 형식)

    Returns:
        int: 시간 범위 (분)
    """
    try:
        if not start_time or not end_time or start_time == 'N/A' or end_time == 'N/A':
            return 0

        # 시간 문자열을 6자리로 맞춤
        start_time = str(start_time).zfill(6)
        end_time = str(end_time).zfill(6)

        start_hour = int(start_time[:2])
        start_minute = int(start_time[2:4])
        end_hour = int(end_time[:2])
        end_minute = int(end_time[2:4])

        start_total_minutes = start_hour * 60 + start_minute
        end_total_minutes = end_hour * 60 + end_minute

        return max(0, end_total_minutes - start_total_minutes)

    except (ValueError, IndexError):
        return 0


def validate_minute_data_continuity(data: pd.DataFrame, stock_code: str, 
                                    logger: Optional = None) -> dict:
    """
    1분봉 데이터 연속성 검증

    09:00부터 순서대로 1분 간격으로 데이터가 있는지 확인

    Args:
        data: 1분봉 DataFrame
        stock_code: 종목코드 (로깅용)
        logger: 로거 (옵션)

    Returns:
        dict: {'valid': bool, 'reason': str, 'missing_times': list}
    """
    try:
        if data.empty:
            return {'valid': False, 'reason': '데이터 없음', 'missing_times': []}

        # datetime 컬럼 확인 및 변환
        if 'datetime' in data.columns:
            data_copy = data.copy()
            data_copy['datetime'] = pd.to_datetime(data_copy['datetime'])

            # 첫 봉이 시장 시작 시간인지 확인 (동적 시간 적용)
            from config.market_hours import MarketHours
            first_time = data_copy['datetime'].iloc[0]
            market_hours = MarketHours.get_market_hours('KRX', first_time)
            market_open = market_hours['market_open']

            if first_time.hour != market_open.hour or first_time.minute != market_open.minute:
                return {
                    'valid': False,
                    'reason': f'첫 봉이 {market_open.strftime("%H:%M")} 아님 (실제: {first_time.strftime("%H:%M")})',
                    'missing_times': []
                }

            # 각 봉 사이의 시간 간격 계산 (초 단위)
            time_diffs = data_copy['datetime'].diff().dt.total_seconds().fillna(0)

            # 1분봉이므로 간격이 정확히 60초여야 함 (첫 봉은 0이므로 제외)
            invalid_gaps = time_diffs[1:][(time_diffs[1:] != 60.0) & (time_diffs[1:] != 0.0)]

            if len(invalid_gaps) > 0:
                # 불연속 구간 발견
                gap_indices = invalid_gaps.index.tolist()
                missing_times = []
                for idx in gap_indices[:5]:  # 최대 5개만 표시
                    prev_time = data_copy.loc[idx-1, 'datetime']
                    curr_time = data_copy.loc[idx, 'datetime']
                    gap_minutes = int(time_diffs[idx] / 60)
                    missing_times.append(f"{prev_time.strftime('%H:%M')}→{curr_time.strftime('%H:%M')} ({gap_minutes}분 간격)")

                return {
                    'valid': False,
                    'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                    'missing_times': missing_times
                }

            # 모든 검증 통과
            return {'valid': True, 'reason': 'OK', 'missing_times': []}

        elif 'time' in data.columns:
            # time 컬럼 기반 검증
            data_copy = data.copy()
            data_copy['time_int'] = data_copy['time'].astype(str).str.zfill(6).str[:4].astype(int)

            # 첫 봉이 시장 시작 시간인지 확인 (동적 시간 적용)
            from config.market_hours import MarketHours
            from utils.korean_time import now_kst

            # 데이터의 날짜 파악
            current_date = now_kst() if 'date' not in data.columns else pd.to_datetime(str(data['date'].iloc[0]), format='%Y%m%d')
            market_hours = MarketHours.get_market_hours('KRX', current_date)
            market_open = market_hours['market_open']
            expected_time_int = market_open.hour * 100 + market_open.minute

            if data_copy['time_int'].iloc[0] != expected_time_int:
                return {
                    'valid': False,
                    'reason': f'첫 봉이 {market_open.strftime("%H:%M")} 아님 (실제: {data_copy["time_int"].iloc[0]})',
                    'missing_times': []
                }

            # 시간 간격 계산
            time_diffs = data_copy['time_int'].diff().fillna(0)

            # 1분 간격 (0900→0901=1, 0959→1000=41 등 처리 필요)
            invalid_gaps = []
            missing_times = []

            for i in range(1, len(data_copy)):
                prev_time = data_copy['time_int'].iloc[i-1]
                curr_time = data_copy['time_int'].iloc[i]

                # 예상 다음 시간 계산
                prev_hour = prev_time // 100
                prev_min = prev_time % 100

                if prev_min == 59:
                    expected_next = (prev_hour + 1) * 100
                else:
                    expected_next = prev_time + 1

                if curr_time != expected_next:
                    invalid_gaps.append(i)
                    if len(missing_times) < 5:
                        missing_times.append(f"{prev_time:04d}→{curr_time:04d}")

            if invalid_gaps:
                return {
                    'valid': False,
                    'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                    'missing_times': missing_times
                }

            return {'valid': True, 'reason': 'OK', 'missing_times': []}

        else:
            # 시간 컬럼이 없으면 검증 불가
            return {'valid': True, 'reason': '시간컬럼없음(검증생략)', 'missing_times': []}

    except Exception as e:
        if logger:
            logger.error(f"❌ {stock_code} 연속성 검증 오류: {e}")
        return {'valid': True, 'reason': f'검증오류(통과처리): {str(e)}', 'missing_times': []}


def validate_today_data(data: pd.DataFrame) -> List[str]:
    """
    당일 데이터인지 검증
    
    Args:
        data: 검증할 DataFrame
        
    Returns:
        List[str]: 검증 이슈 목록 (비어있으면 정상)
    """
    issues = []

    try:
        from utils.korean_time import now_kst
        today_str = now_kst().strftime('%Y%m%d')

        # 1. date 컬럼이 있는 경우 (YYYYMMDD 형태)
        if 'date' in data.columns:
            unique_dates = data['date'].unique()
            wrong_dates = [d for d in unique_dates if str(d) != today_str]
            if wrong_dates:
                issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')

        # 2. datetime 컬럼이 있는 경우
        elif 'datetime' in data.columns:
            # datetime 컬럼에서 날짜 추출
            try:
                data_dates = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d').unique()
                wrong_dates = [d for d in data_dates if d != today_str]
                if wrong_dates:
                    issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')
            except Exception:
                # datetime 파싱 실패시 무시
                pass

        # 3. stck_bsop_date 컬럼이 있는 경우 (KIS API 응답)
        elif 'stck_bsop_date' in data.columns:
            unique_dates = data['stck_bsop_date'].unique()
            wrong_dates = [d for d in unique_dates if str(d) != today_str]
            if wrong_dates:
                issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')

    except Exception as e:
        issues.append(f'날짜 검증 오류: {str(e)[:30]}')

    return issues

