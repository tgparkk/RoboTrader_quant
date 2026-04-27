"""거래 캘린더 — 첫 거래일 판정 (월간 리밸런싱 트리거).

KRX 영업일 기준. 기존 `utils/korean_holidays.is_holiday()` 를 재사용
(주말 + 고정 공휴일 + 음력 공휴일 + 임시 공휴일 통합 판정).

monthly 리밸런싱 트리거 로직:
    if is_first_trading_day_of_month(today):
        execute_rebalancing()
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from utils.korean_holidays import is_holiday


def _to_datetime(d: date) -> datetime:
    """date → datetime (00:00) 변환. is_holiday 가 datetime 시그니처를 요구."""
    return datetime(d.year, d.month, d.day)


def is_trading_day(d: date) -> bool:
    """주말 + KRX 공휴일 제외."""
    return not is_holiday(_to_datetime(d))


def is_first_trading_day_of_month(d: date) -> bool:
    """d 가 그 달의 첫 거래일이면 True.

    그 달 1일부터 d 직전까지 모든 날이 비-거래일이어야 하고, d 자신은 거래일이어야 함.
    """
    if not is_trading_day(d):
        return False
    cur = d.replace(day=1)
    while cur < d:
        if is_trading_day(cur):
            return False
        cur += timedelta(days=1)
    return True
