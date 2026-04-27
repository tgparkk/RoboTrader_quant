"""거래 캘린더 첫 거래일 판정 테스트."""
from datetime import date

from utils.trading_calendar import is_first_trading_day_of_month, is_trading_day


def test_first_trading_day_of_april_2026():
    """2026-04-01 (수) 평일/공휴일 아님 → 4월 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 4, 1)) is True


def test_first_trading_day_when_1st_is_holiday():
    """2026-01-01 (목) 신정 휴일 → 2026-01-02 (금) 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 1, 1)) is False
    assert is_first_trading_day_of_month(date(2026, 1, 2)) is True


def test_first_trading_day_when_1st_is_weekend():
    """2026-02-01 (일요일) → 2026-02-02 (월) 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 2, 1)) is False
    assert is_first_trading_day_of_month(date(2026, 2, 2)) is True


def test_mid_month_returns_false():
    """월 중간 영업일은 False."""
    assert is_first_trading_day_of_month(date(2026, 4, 15)) is False


def test_weekend_returns_false():
    """주말은 첫 거래일 아님."""
    assert is_first_trading_day_of_month(date(2026, 3, 1)) is False  # 일요일+삼일절


def test_is_trading_day_basic():
    """is_trading_day: 주말/공휴일 제외 평일 → True."""
    assert is_trading_day(date(2026, 4, 1)) is True   # 수요일 평일
    assert is_trading_day(date(2026, 1, 1)) is False  # 신정
    assert is_trading_day(date(2026, 2, 17)) is False  # 설날 (LUNAR_HOLIDAYS)
    assert is_trading_day(date(2026, 3, 14)) is False  # 토요일


def test_first_trading_day_after_lunar_holiday_block():
    """2026-02-16~18 설날 연휴 + 2/14-15 주말 → 2/2 (월) 가 2월 첫 거래일."""
    assert is_first_trading_day_of_month(date(2026, 2, 2)) is True
    # 2/16 (월, 설날 전날 = LUNAR_HOLIDAY) → 첫 거래일 아님
    assert is_first_trading_day_of_month(date(2026, 2, 16)) is False
