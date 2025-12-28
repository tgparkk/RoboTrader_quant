"""
한국 공휴일 캘린더

주식 시장 휴장일을 판단하기 위한 유틸리티입니다.
"""
from datetime import datetime, timedelta
from typing import Set

# 고정 공휴일 (매년 동일)
FIXED_HOLIDAYS = {
    (1, 1): "신정",
    (3, 1): "삼일절",
    (5, 5): "어린이날",
    (6, 6): "현충일",
    (8, 15): "광복절",
    (10, 3): "개천절",
    (10, 9): "한글날",
    (12, 25): "크리스마스",
}

# 음력 공휴일 (설날, 추석)은 매년 변동되므로 수동 관리
# 2024-2030년 음력 공휴일 (설날 3일, 추석 3일)
LUNAR_HOLIDAYS = {
    # 2024년
    "2024-02-09": "설날 전날",
    "2024-02-10": "설날",
    "2024-02-11": "설날 다음날",
    "2024-02-12": "설날 대체공휴일",
    "2024-09-16": "추석 전날",
    "2024-09-17": "추석",
    "2024-09-18": "추석 다음날",

    # 2025년
    "2025-01-28": "설날 전날",
    "2025-01-29": "설날",
    "2025-01-30": "설날 다음날",
    "2025-10-05": "추석 전날",
    "2025-10-06": "추석",
    "2025-10-07": "추석 다음날",
    "2025-10-08": "추석 대체공휴일",

    # 2026년
    "2026-02-16": "설날 전날",
    "2026-02-17": "설날",
    "2026-02-18": "설날 다음날",
    "2026-09-24": "추석 전날",
    "2026-09-25": "추석",
    "2026-09-26": "추석 다음날",
    "2026-09-28": "추석 대체공휴일",

    # 2027년
    "2027-02-06": "설날 전날",
    "2027-02-07": "설날",
    "2027-02-08": "설날 다음날",
    "2027-09-14": "추석 전날",
    "2027-09-15": "추석",
    "2027-09-16": "추석 다음날",

    # 2028년
    "2028-01-26": "설날 전날",
    "2028-01-27": "설날",
    "2028-01-28": "설날 다음날",
    "2028-10-02": "추석 전날",
    "2028-10-03": "추석",
    "2028-10-04": "추석 다음날",

    # 2029년
    "2029-02-12": "설날 전날",
    "2029-02-13": "설날",
    "2029-02-14": "설날 다음날",
    "2029-09-21": "추석 전날",
    "2029-09-22": "추석",
    "2029-09-23": "추석 다음날",
    "2029-09-24": "추석 대체공휴일",

    # 2030년
    "2030-02-02": "설날 전날",
    "2030-02-03": "설날",
    "2030-02-04": "설날 다음날",
    "2030-09-11": "추석 전날",
    "2030-09-12": "추석",
    "2030-09-13": "추석 다음날",
}

# 임시 공휴일 (선거일 등)
SPECIAL_HOLIDAYS = {
    "2024-04-10": "제22대 국회의원 선거",
    # 향후 선거일 추가 필요
}


def is_weekend(date: datetime) -> bool:
    """주말 여부 확인 (토요일=5, 일요일=6)"""
    return date.weekday() >= 5


def is_fixed_holiday(date: datetime) -> bool:
    """고정 공휴일 여부 확인"""
    return (date.month, date.day) in FIXED_HOLIDAYS


def is_lunar_holiday(date: datetime) -> bool:
    """음력 공휴일 여부 확인"""
    date_str = date.strftime("%Y-%m-%d")
    return date_str in LUNAR_HOLIDAYS


def is_special_holiday(date: datetime) -> bool:
    """임시 공휴일 여부 확인"""
    date_str = date.strftime("%Y-%m-%d")
    return date_str in SPECIAL_HOLIDAYS


def is_holiday(date: datetime) -> bool:
    """
    공휴일 여부 확인 (주말 포함)

    Args:
        date: 확인할 날짜

    Returns:
        bool: 공휴일이면 True
    """
    return (
        is_weekend(date) or
        is_fixed_holiday(date) or
        is_lunar_holiday(date) or
        is_special_holiday(date)
    )


def get_holiday_name(date: datetime) -> str:
    """
    공휴일 이름 반환

    Args:
        date: 확인할 날짜

    Returns:
        str: 공휴일 이름 (공휴일이 아니면 빈 문자열)
    """
    if is_weekend(date):
        return "주말" if date.weekday() == 6 else "토요일"

    key = (date.month, date.day)
    if key in FIXED_HOLIDAYS:
        return FIXED_HOLIDAYS[key]

    date_str = date.strftime("%Y-%m-%d")
    if date_str in LUNAR_HOLIDAYS:
        return LUNAR_HOLIDAYS[date_str]

    if date_str in SPECIAL_HOLIDAYS:
        return SPECIAL_HOLIDAYS[date_str]

    return ""


def get_previous_trading_day(date: datetime = None, max_lookback_days: int = 10) -> datetime:
    """
    이전 영업일 반환 (주말 및 공휴일 자동 건너뛰기)

    Args:
        date: 기준 날짜 (None이면 오늘)
        max_lookback_days: 최대 조회일수 (기본 10일)

    Returns:
        datetime: 이전 영업일
    """
    if date is None:
        from utils.korean_time import now_kst
        date = now_kst()

    # 어제부터 시작
    current = date - timedelta(days=1)

    for _ in range(max_lookback_days):
        if not is_holiday(current):
            return current
        current -= timedelta(days=1)

    # 10일 이내에 영업일을 못 찾으면 그냥 어제 반환
    return date - timedelta(days=1)


def get_next_trading_day(date: datetime = None, max_lookforward_days: int = 10) -> datetime:
    """
    다음 영업일 반환 (주말 및 공휴일 자동 건너뛰기)

    Args:
        date: 기준 날짜 (None이면 오늘)
        max_lookforward_days: 최대 조회일수 (기본 10일)

    Returns:
        datetime: 다음 영업일
    """
    if date is None:
        from utils.korean_time import now_kst
        date = now_kst()

    # 내일부터 시작
    current = date + timedelta(days=1)

    for _ in range(max_lookforward_days):
        if not is_holiday(current):
            return current
        current += timedelta(days=1)

    # 10일 이내에 영업일을 못 찾으면 그냥 내일 반환
    return date + timedelta(days=1)


def count_trading_days_between(start_date: datetime, end_date: datetime) -> int:
    """
    두 날짜 사이의 영업일 수 계산

    Args:
        start_date: 시작 날짜
        end_date: 종료 날짜

    Returns:
        int: 영업일 수
    """
    count = 0
    current = start_date

    while current <= end_date:
        if not is_holiday(current):
            count += 1
        current += timedelta(days=1)

    return count


if __name__ == "__main__":
    # 테스트
    from utils.korean_time import now_kst

    print("=" * 80)
    print("한국 공휴일 캘린더 테스트")
    print("=" * 80)
    print()

    today = now_kst()
    print(f"오늘: {today.strftime('%Y-%m-%d')} ({today.strftime('%A')})")
    print(f"  공휴일 여부: {is_holiday(today)}")
    if is_holiday(today):
        print(f"  공휴일 이름: {get_holiday_name(today)}")
    print()

    prev_trading = get_previous_trading_day(today)
    print(f"이전 영업일: {prev_trading.strftime('%Y-%m-%d')} ({prev_trading.strftime('%A')})")
    print()

    next_trading = get_next_trading_day(today)
    print(f"다음 영업일: {next_trading.strftime('%Y-%m-%d')} ({next_trading.strftime('%A')})")
    print()

    # 2025년 주요 공휴일 출력
    print("2025년 주요 공휴일:")
    print("-" * 60)

    for month in range(1, 13):
        for day in range(1, 32):
            try:
                test_date = datetime(2025, month, day)
                if is_holiday(test_date) and not is_weekend(test_date):
                    holiday_name = get_holiday_name(test_date)
                    print(f"  {test_date.strftime('%Y-%m-%d')} ({test_date.strftime('%A')}): {holiday_name}")
            except ValueError:
                continue

    print()
    print("=" * 80)
