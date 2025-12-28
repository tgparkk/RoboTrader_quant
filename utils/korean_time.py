"""
한국 시장 시간 관련 유틸리티
market_hours.py로 이관됨 (하위 호환성 유지)
"""
from datetime import datetime
import pytz

# 하위 호환성을 위해 기존 함수들 유지
# 실제 구현은 config.market_hours.MarketHours 사용
try:
    from config.market_hours import MarketHours, KST as _KST
    KST = _KST
except ImportError:
    # fallback: config.market_hours를 찾을 수 없을 때
    KST = pytz.timezone('Asia/Seoul')
    from datetime import time

    def now_kst() -> datetime:
        """현재 한국 시간 반환"""
        return datetime.now(KST)

    def is_market_open(dt: datetime = None) -> bool:
        """장중 시간인지 확인 (fallback)"""
        if dt is None:
            dt = now_kst()

        if dt.weekday() >= 5:
            return False

        market_open = time(9, 0)
        market_close = time(15, 30)
        current_time = dt.time()
        return market_open <= current_time <= market_close

    def is_before_market_open(dt: datetime = None) -> bool:
        """장 시작 전인지 확인 (fallback)"""
        if dt is None:
            dt = now_kst()

        if dt.weekday() >= 5:
            return False

        market_open = time(9, 0)
        current_time = dt.time()
        return current_time < market_open

    def get_market_status() -> str:
        """시장 상태 반환 (fallback)"""
        now = now_kst()

        if now.weekday() >= 5:
            return "weekend"
        elif is_before_market_open(now):
            return "pre_market"
        elif is_market_open(now):
            return "market_open"
        else:
            return "after_market"
else:
    # config.market_hours를 정상적으로 import한 경우
    def now_kst() -> datetime:
        """현재 한국 시간 반환"""
        return datetime.now(KST)

    def is_market_open(dt: datetime = None) -> bool:
        """장중 시간인지 확인 (KRX 기준, 특수일 자동 반영)"""
        return MarketHours.is_market_open('KRX', dt)

    def is_before_market_open(dt: datetime = None) -> bool:
        """장 시작 전인지 확인 (KRX 기준, 특수일 자동 반영)"""
        return MarketHours.is_before_market_open('KRX', dt)

    def get_market_status() -> str:
        """시장 상태 반환 (KRX 기준, 특수일 자동 반영)"""
        return MarketHours.get_market_status('KRX')

    def get_previous_trading_day(dt: datetime = None, market: str = 'KRX') -> datetime:
        """전 영업일 반환 (주말, 공휴일 자동 건너뛰기)

        Args:
            dt: 기준 날짜 (None이면 오늘)
            market: 시장 코드 (기본값: KRX)

        Returns:
            전 영업일 datetime (시간은 00:00:00)

        Examples:
            >>> # 2025-12-26(목) → 2025-12-25(수)
            >>> get_previous_trading_day(datetime(2025, 12, 26))
            datetime(2025, 12, 25, 0, 0, 0)

            >>> # 2025-12-23(월) → 2025-12-20(금) (주말 건너뛰기)
            >>> get_previous_trading_day(datetime(2025, 12, 23))
            datetime(2025, 12, 20, 0, 0, 0)

            >>> # 2025-01-30(목) → 2025-01-27(월) (설날 연휴 건너뛰기)
            >>> get_previous_trading_day(datetime(2025, 1, 30))
            datetime(2025, 1, 27, 0, 0, 0)
        """
        from datetime import timedelta

        if dt is None:
            dt = now_kst()

        # 하루 전부터 시작
        prev_day = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

        # 공휴일 캘린더 import (fallback: 주말만 체크)
        try:
            from utils.korean_holidays import is_holiday
            use_holiday_calendar = True
        except ImportError:
            use_holiday_calendar = False

        # 최대 10일 전까지 검색 (연휴 대비)
        for _ in range(10):
            if use_holiday_calendar:
                # 공휴일 캘린더 사용
                if not is_holiday(prev_day):
                    return prev_day
            else:
                # Fallback: 주말만 체크
                if prev_day.weekday() < 5:  # 월(0) ~ 금(4)
                    return prev_day

            prev_day -= timedelta(days=1)

        # 10일 전까지 영업일이 없으면 (비정상) 그냥 10일 전 반환
        return prev_day