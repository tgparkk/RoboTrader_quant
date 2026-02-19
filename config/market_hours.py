"""
시장별 거래시간 설정
해외주식 확장을 고려한 시장별/날짜별 거래시간 관리
"""
from datetime import time, datetime
from typing import Dict, Optional
import pytz


class MarketHours:
    """시장별 거래시간 설정"""

    # 시장별 기본 거래시간 설정
    MARKET_CONFIG = {
        'KRX': {  # 한국거래소
            'timezone': 'Asia/Seoul',
            'default': {
                'market_open': time(9, 0),      # 09:00
                'market_close': time(15, 30),   # 15:30
                'buy_cutoff_hour': 12,          # 12시 이후 매수 중단
                'eod_liquidation_hour': 15,     # 15시 시장가 일괄매도
                'eod_liquidation_minute': 0,    # 15:00 정각
            },
            'special_days': {
                # 수능일 (2025년)
                '2025-11-13': {
                    'market_open': time(10, 0),     # 10:00
                    'market_close': time(16, 30),   # 16:30
                    'buy_cutoff_hour': 13,          # 13시 이후 매수 중단
                    'eod_liquidation_hour': 16,     # 16시 시장가 일괄매도
                    'eod_liquidation_minute': 0,    # 16:00 정각
                    'reason': '수능일 (1시간 지연)'
                },
                # 향후 특수일 추가 가능
                # '2025-12-31': { ... },  # 연말 단축거래
            }
        },

        # 나중에 해외 시장 추가
        'NYSE': {  # 뉴욕증권거래소
            'timezone': 'America/New_York',
            'default': {
                'market_open': time(9, 30),
                'market_close': time(16, 0),
                'buy_cutoff_hour': 15,          # 3PM ET
                'eod_liquidation_hour': 15,
                'eod_liquidation_minute': 55,
            },
            'special_days': {}
        },

        'NASDAQ': {  # 나스닥
            'timezone': 'America/New_York',
            'default': {
                'market_open': time(9, 30),
                'market_close': time(16, 0),
                'buy_cutoff_hour': 15,
                'eod_liquidation_hour': 15,
                'eod_liquidation_minute': 55,
            },
            'special_days': {}
        },

        'TSE': {  # 도쿄증권거래소
            'timezone': 'Asia/Tokyo',
            'default': {
                'market_open': time(9, 0),
                'market_close': time(15, 0),    # 점심시간 11:30-12:30 있음 (추후 구현)
                'buy_cutoff_hour': 14,
                'eod_liquidation_hour': 14,
                'eod_liquidation_minute': 55,
            },
            'special_days': {}
        }
    }

    @classmethod
    def get_market_hours(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> Dict:
        """특정 날짜의 시장 거래시간 반환

        Args:
            market: 시장 코드 (KRX, NYSE, NASDAQ, TSE 등)
            dt: 확인할 날짜 (None이면 오늘)

        Returns:
            거래시간 설정 딕셔너리
        """
        if market not in cls.MARKET_CONFIG:
            raise ValueError(f"Unknown market: {market}")

        market_config = cls.MARKET_CONFIG[market]

        # 날짜가 없으면 오늘 날짜 사용
        if dt is None:
            tz = pytz.timezone(market_config['timezone'])
            dt = datetime.now(tz)

        # 해당 날짜의 특수일 설정 확인
        date_str = dt.strftime('%Y-%m-%d')
        special_days = market_config.get('special_days', {})

        if date_str in special_days:
            # 특수일 설정 사용
            special_config = special_days[date_str].copy()
            special_config['timezone'] = market_config['timezone']
            special_config['is_special_day'] = True
            return special_config
        else:
            # 기본 설정 사용
            default_config = market_config['default'].copy()
            default_config['timezone'] = market_config['timezone']
            default_config['is_special_day'] = False
            return default_config

    @classmethod
    def is_market_open(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> bool:
        """장중 시간인지 확인

        Args:
            market: 시장 코드
            dt: 확인할 시간 (None이면 현재)

        Returns:
            장중이면 True
        """
        hours = cls.get_market_hours(market, dt)
        tz = pytz.timezone(hours['timezone'])

        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = tz.localize(dt)

        # 평일만 확인 (월-금)
        if dt.weekday() >= 5:  # 토요일(5), 일요일(6)
            return False

        market_open = hours['market_open']
        market_close = hours['market_close']
        current_time = dt.time()

        return market_open <= current_time <= market_close

    @classmethod
    def is_before_market_open(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> bool:
        """장 시작 전인지 확인"""
        hours = cls.get_market_hours(market, dt)
        tz = pytz.timezone(hours['timezone'])

        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = tz.localize(dt)

        # 평일이 아니면 False
        if dt.weekday() >= 5:
            return False

        market_open = hours['market_open']
        current_time = dt.time()
        return current_time < market_open

    @classmethod
    def get_market_status(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> str:
        """시장 상태 반환

        Returns:
            'weekend', 'pre_market', 'market_open', 'after_market'
        """
        hours = cls.get_market_hours(market, dt)
        tz = pytz.timezone(hours['timezone'])

        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = tz.localize(dt)

        if dt.weekday() >= 5:
            return "weekend"
        elif cls.is_before_market_open(market, dt):
            return "pre_market"
        elif cls.is_market_open(market, dt):
            return "market_open"
        else:
            return "after_market"

    @classmethod
    def should_stop_buying(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> bool:
        """매수 중단 시간인지 확인 (buy_cutoff_hour 이후)

        Args:
            market: 시장 코드
            dt: 확인할 시간 (None이면 현재)

        Returns:
            매수 중단 시간이면 True
        """
        hours = cls.get_market_hours(market, dt)
        tz = pytz.timezone(hours['timezone'])

        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = tz.localize(dt)

        buy_cutoff_hour = hours.get('buy_cutoff_hour', 12)
        return dt.hour >= buy_cutoff_hour

    @classmethod
    def is_eod_liquidation_time(cls, market: str = 'KRX', dt: Optional[datetime] = None) -> bool:
        """장마감 일괄청산 시간인지 확인 (eod_liquidation_hour 이후)

        Args:
            market: 시장 코드
            dt: 확인할 시간 (None이면 현재)

        Returns:
            청산 시간이면 True
        """
        hours = cls.get_market_hours(market, dt)
        tz = pytz.timezone(hours['timezone'])

        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = tz.localize(dt)

        eod_hour = hours.get('eod_liquidation_hour', 15)
        eod_minute = hours.get('eod_liquidation_minute', 0)

        # 지정된 시간 이후인지 확인
        if dt.hour > eod_hour:
            return True
        elif dt.hour == eod_hour and dt.minute >= eod_minute:
            return True
        else:
            return False

    @classmethod
    def get_today_info(cls, market: str = 'KRX') -> str:
        """오늘 거래시간 정보를 문자열로 반환 (로깅용)"""
        hours = cls.get_market_hours(market)

        info = f"[{market}] "
        if hours.get('is_special_day', False):
            reason = hours.get('reason', '특수일')
            info += f"[!] {reason}\n"

        info += f"장 시작: {hours['market_open'].strftime('%H:%M')}\n"
        info += f"장 마감: {hours['market_close'].strftime('%H:%M')}\n"
        info += f"매수 중단: {hours['buy_cutoff_hour']:02d}:00 이후\n"
        info += f"일괄 청산: {hours['eod_liquidation_hour']:02d}:{hours['eod_liquidation_minute']:02d}"

        return info


# 하위 호환성을 위한 전역 함수들 (기존 코드와의 호환성 유지)
def now_kst() -> datetime:
    """현재 한국 시간 반환"""
    return datetime.now(pytz.timezone('Asia/Seoul'))


def is_market_open(dt: datetime = None) -> bool:
    """장중 시간인지 확인 (KRX 기준)"""
    return MarketHours.is_market_open('KRX', dt)


def is_before_market_open(dt: datetime = None) -> bool:
    """장 시작 전인지 확인 (KRX 기준)"""
    return MarketHours.is_before_market_open('KRX', dt)


def get_market_status() -> str:
    """시장 상태 반환 (KRX 기준)"""
    return MarketHours.get_market_status('KRX')


# 편의 함수
KST = pytz.timezone('Asia/Seoul')
