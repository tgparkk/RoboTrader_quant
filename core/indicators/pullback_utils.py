"""
눌림목 캔들패턴 유틸리티 함수들 (리팩토링된 버전)
기존 PullbackUtils 클래스의 호환성을 유지하면서 새로운 모듈 구조 사용
"""

from .pullback.types import (
    SignalType, BisectorStatus, RiskSignal, SignalStrength, 
    CandleAnalysis, VolumeAnalysis
)
from .pullback.volume_analyzer import VolumeAnalyzer
from .pullback.candle_analyzer import CandleAnalyzer
from .pullback.bisector_analyzer import BisectorAnalyzer
from .pullback.risk_detector import RiskDetector
from .pullback.signal_calculator import SignalCalculator

import pandas as pd
from typing import Dict, Optional, List


class PullbackUtils:
    """
    눌림목 캔들패턴 유틸리티 함수들 (리팩토링된 버전)
    기존 API 호환성을 유지하면서 내부적으로 새로운 모듈 구조 사용
    """
    
    # 거래량 분석 관련 메서드들
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산 (당일 최대 거래량을 실시간 추적)"""
        return VolumeAnalyzer.calculate_daily_baseline_volume(data)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10, 
                      baseline_volumes: Optional[pd.Series] = None) -> VolumeAnalysis:
        """거래량 분석 (개선된 기준거래량 사용)"""
        return VolumeAnalyzer.analyze_volume(data, period, baseline_volumes)
    
    @staticmethod
    def analyze_price_trend(data: pd.DataFrame, period: int = 10) -> Dict[str, float]:
        """가격 트렌드 분석"""
        return VolumeAnalyzer.analyze_price_trend(data, period)
    
    @staticmethod
    def check_low_volume_retrace(data: pd.DataFrame, lookback: int = 3, volume_threshold: float = 0.25) -> bool:
        """저거래량 조정 확인"""
        return VolumeAnalyzer.check_low_volume_retrace(data, lookback, volume_threshold)
    
    @staticmethod
    def check_volume_recovery(data: pd.DataFrame, retrace_lookback: int = 3) -> bool:
        """거래량 회복 여부 확인"""
        return VolumeAnalyzer.check_volume_recovery(data, retrace_lookback)
    
    @staticmethod
    def check_low_volume_breakout_signal(data: pd.DataFrame, baseline_volumes: pd.Series,
                                       min_low_volume_candles: int = 2,
                                       volume_threshold: float = 0.3) -> bool:
        """저거래량 조정 후 회복 양봉 신호 확인"""
        return VolumeAnalyzer.check_low_volume_breakout_signal(
            data, baseline_volumes, min_low_volume_candles, volume_threshold
        )
    
    # 캔들 분석 관련 메서드들
    @staticmethod
    def is_recovery_candle(data: pd.DataFrame, index: int) -> bool:
        """회복 양봉 여부 확인"""
        return CandleAnalyzer.is_recovery_candle(data, index)
    
    @staticmethod
    def analyze_candle_size(data: pd.DataFrame, period: int = 20) -> Dict[str, float]:
        """캔들 크기 분석"""
        return CandleAnalyzer.analyze_candle_size(data, period)
    
    @staticmethod
    def check_overhead_supply(data: pd.DataFrame, lookback: int = 10, threshold_hits: int = 2) -> bool:
        """머리 위 물량 확인"""
        return CandleAnalyzer.check_overhead_supply(data, lookback, threshold_hits)
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10, prev_close: Optional[float] = None) -> CandleAnalysis:
        """캔들 분석 (변곡캔들 검증 로직 강화)"""
        return CandleAnalyzer.analyze_candle(data, period, prev_close)
    
    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05, 
                          baseline_volume: Optional[float] = None) -> bool:
        """선행 상승 확인 (개선된 버전)"""
        return CandleAnalyzer.check_prior_uptrend(data, min_gain, baseline_volume)
    
    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        return CandleAnalyzer.check_price_trend(data, period)
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉)"""
        return CandleAnalyzer.find_recent_low(data, period)
    
    # 이등분선 분석 관련 메서드들
    @staticmethod
    def analyze_bisector_status(data: pd.DataFrame, tolerance: float = 0.005) -> BisectorStatus:
        """이등분선 지지/저항 상태 분석"""
        return BisectorAnalyzer.analyze_bisector_status(data, tolerance)
    
    @staticmethod
    def check_bisector_cross_up(data: pd.DataFrame, tolerance: float = 0.002) -> bool:
        """이등분선 상향 돌파 확인 (허용 오차 0.2%)"""
        return BisectorAnalyzer.check_bisector_cross_up(data, tolerance)
    
    @staticmethod
    def get_bisector_status(current_price: float, bisector_line: float) -> BisectorStatus:
        """지지선 상태 판단 (제시된 로직 적용)"""
        return BisectorAnalyzer.get_bisector_status(current_price, bisector_line)
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인 (기존 호환성)"""
        return BisectorAnalyzer.check_price_above_bisector(data)
    
    # 위험 신호 감지 관련 메서드들
    @staticmethod
    def detect_risk_signals(
        data: pd.DataFrame,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        target_profit_rate: float = 0.03
    ) -> List[RiskSignal]:
        """위험 신호 감지"""
        return RiskDetector.detect_risk_signals(data, entry_price, entry_low, target_profit_rate)
    
    @staticmethod
    def check_risk_signals(current: pd.Series, bisector_line: float, entry_low: Optional[float], 
                          recent_low: float, entry_price: Optional[float], 
                          volume_analysis: VolumeAnalysis, candle_analysis: CandleAnalysis) -> List[RiskSignal]:
        """위험 신호 최우선 체크 (제시된 로직 적용)"""
        return RiskDetector.check_risk_signals(
            current, bisector_line, entry_low, recent_low, entry_price, volume_analysis, candle_analysis
        )
    
    # 신호 강도 계산 관련 메서드들
    @staticmethod
    def calculate_signal_strength(
        volume_analysis: VolumeAnalysis,
        bisector_status: BisectorStatus,
        is_recovery_candle: bool,
        volume_recovers: bool,
        has_retrace: bool,
        crosses_bisector_up: bool,
        has_overhead_supply: bool,
        data: Optional[pd.DataFrame] = None
    ) -> SignalStrength:
        """신호 강도 계산"""
        return SignalCalculator.calculate_signal_strength(
            volume_analysis, bisector_status, is_recovery_candle, volume_recovers,
            has_retrace, crosses_bisector_up, has_overhead_supply, data
        )
    
    @staticmethod
    def format_signal_info(signal_strength: SignalStrength, additional_info: Dict = None) -> str:
        """신호 정보 포맷팅"""
        return SignalCalculator.format_signal_info(signal_strength, additional_info)
    
    @staticmethod
    def handle_avoid_conditions(has_selling_pressure: bool, has_bearish_volume_restriction: bool, 
                              bisector_breakout_volume_ok: bool, current: pd.Series,
                              volume_analysis: VolumeAnalysis, bisector_line: float,
                              data: pd.DataFrame = None, debug: bool = False, logger = None) -> Optional[SignalStrength]:
        """회피 조건들 처리"""
        return SignalCalculator.handle_avoid_conditions(
            has_selling_pressure, has_bearish_volume_restriction, bisector_breakout_volume_ok,
            current, volume_analysis, bisector_line, data, debug, logger
        )
    
    # 추가: 내부 메서드 (호환성 유지)
    @staticmethod
    def _check_sustained_uptrend(segment_data: pd.DataFrame) -> bool:
        """구간 내 지속적 상승 패턴 확인"""
        return CandleAnalyzer._check_sustained_uptrend(segment_data)