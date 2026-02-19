"""
눌림목 캔들패턴 분석을 위한 데이터 타입 정의
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class SignalType(Enum):
    """신호 타입"""
    STRONG_BUY = "STRONG_BUY"
    CAUTIOUS_BUY = "CAUTIOUS_BUY" 
    WAIT = "WAIT"
    AVOID = "AVOID"
    SELL = "SELL"


class BisectorStatus(Enum):
    """이등분선 상태"""
    HOLDING = "HOLDING"        # 현재가 >= 이등분선
    NEAR_SUPPORT = "NEAR_SUPPORT"  # 이등분선 ± 0.5% 범위
    BROKEN = "BROKEN"          # 현재가 < 이등분선 - 0.5%


class RiskSignal(Enum):
    """위험 신호 타입"""
    LARGE_BEARISH_VOLUME = "LARGE_BEARISH_VOLUME"  # 장대음봉 + 대량거래량
    BISECTOR_BREAK = "BISECTOR_BREAK"              # 이등분선 이탈
    ENTRY_LOW_BREAK = "ENTRY_LOW_BREAK"            # 변곡캔들 저가 이탈
    SUPPORT_BREAK = "SUPPORT_BREAK"                # 지지 저점 이탈
    TARGET_REACHED = "TARGET_REACHED"              # 목표 수익 달성


@dataclass
class SignalStrength:
    """신호 강도 정보"""
    signal_type: SignalType
    confidence: float          # 0-100 신뢰도
    target_profit: float       # 목표 수익률
    reasons: List[str]         # 신호 근거
    volume_ratio: float        # 거래량 비율
    bisector_status: BisectorStatus  # 이등분선 상태
    buy_price: float = 0.0     # 매수 권장가격 (4/5가 등)
    entry_low: float = 0.0     # 진입 저가 (손절 기준)
    pattern_data: dict = None  # 4단계 패턴 구간 데이터 (analyze_support_pattern 결과)


@dataclass
class CandleAnalysis:
    """캔들 분석 결과"""
    is_bullish: bool             # 양봉 여부
    body_size: float             # 캔들 실체 크기
    body_pct: float              # 실체 크기 비율 (%)
    current_candle_size: float   # 현재 캔들 크기 (high-low)
    avg_recent_candle_size: float # 최근 평균 캔들 크기
    candle_trend: str           # 'expanding', 'shrinking', 'stable'
    is_small_candle: bool       # 작은 캔들 여부
    is_large_candle: bool       # 큰 캔들 여부
    is_meaningful_body: bool    # 의미있는 실체 크기 (0.5% 이상)


@dataclass
class VolumeAnalysis:
    """거래량 분석 결과"""
    baseline_volume: float       # 기준 거래량
    current_volume: float        # 현재 거래량
    avg_recent_volume: float     # 최근 평균 거래량
    volume_ratio: float          # 거래량 비율
    volume_trend: str           # 거래량 추세
    is_volume_surge: bool       # 거래량 급증
    is_low_volume: bool         # 낮은 거래량 (25% 이하)
    is_moderate_volume: bool    # 보통 거래량 (25-50%)
    is_high_volume: bool        # 높은 거래량 (50% 이상)