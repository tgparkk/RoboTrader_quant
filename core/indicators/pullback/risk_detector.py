"""
위험 신호 감지 모듈
"""

import pandas as pd
from typing import List, Optional
from .types import RiskSignal, VolumeAnalysis, CandleAnalysis
from .volume_analyzer import VolumeAnalyzer
from .bisector_analyzer import BisectorAnalyzer


class RiskDetector:
    """위험 신호 감지 클래스"""
    
    @staticmethod
    def detect_risk_signals(
        data: pd.DataFrame,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        target_profit_rate: float = 0.03
    ) -> List[RiskSignal]:
        """위험 신호 감지"""
        risk_signals = []
        
        if len(data) == 0:
            return risk_signals
        
        current_candle = data.iloc[-1]
        current_price = current_candle['close']
        
        # 목표 수익 달성
        if entry_price and current_price >= entry_price * (1 + target_profit_rate):
            risk_signals.append(RiskSignal.TARGET_REACHED)
        
        # 이등분선 이탈
        try:
            bisector_status = BisectorAnalyzer.analyze_bisector_status(data)
            if bisector_status.name == 'BROKEN':
                risk_signals.append(RiskSignal.BISECTOR_BREAK)
        except Exception:
            pass
        
        # 진입 양봉 저가 이탈 (0.2% 허용오차) - 주석처리: 손익비로만 판단
        # if entry_low and current_price < entry_low * 0.998:
        #     risk_signals.append(RiskSignal.ENTRY_LOW_BREAK)
        
        # 장대 음봉 + 대량 거래량
        volume_analysis = VolumeAnalyzer.analyze_volume(data)
        is_large_bearish = (
            float(current_candle['close']) < float(current_candle['open']) and  # 음봉
            abs(float(current_candle['close']) - float(current_candle['open'])) > 
            (float(current_candle['high']) - float(current_candle['low'])) * 0.6 and  # 장대
            volume_analysis.is_volume_surge  # 대량거래량
        )
        
        if is_large_bearish:
            risk_signals.append(RiskSignal.LARGE_BEARISH_VOLUME)
        
        # 지지 저점 이탈 (최근 10개 중 최저점)
        if len(data) >= 10:
            recent_lows = data['low'].iloc[-10:]
            support_level = recent_lows.min()
            if current_price < support_level * 0.998:  # 0.2% 허용오차
                risk_signals.append(RiskSignal.SUPPORT_BREAK)
        
        return risk_signals
    
    @staticmethod
    def check_risk_signals(current: pd.Series, bisector_line: float, entry_low: Optional[float], 
                          recent_low: float, entry_price: Optional[float], 
                          volume_analysis: VolumeAnalysis, candle_analysis: CandleAnalysis) -> List[RiskSignal]:
        """위험 신호 최우선 체크 (제시된 로직 적용)"""
        risk_signals = []
        
        # 1. 장대음봉 + 대량거래량 (50% 이상)
        if (not candle_analysis.is_bullish and 
            candle_analysis.is_large_candle and 
            volume_analysis.is_high_volume):
            risk_signals.append(RiskSignal.LARGE_BEARISH_VOLUME)
        
        # 2. 이등분선 이탈 (0.2% 기준)
        if bisector_line is not None and float(current['close']) < bisector_line * 0.998:
            risk_signals.append(RiskSignal.BISECTOR_BREAK)
        
        # 3. 변곡캔들 저가 이탈 (0.2% 기준) - 주석처리: 손익비로만 판단
        # if entry_low is not None and current['close'] <= entry_low * 0.998:
        #     risk_signals.append(RiskSignal.ENTRY_LOW_BREAK)
        
        # 4. 지지 저점 이탈
        if float(current['close']) < recent_low:
            risk_signals.append(RiskSignal.SUPPORT_BREAK)
        
        # 5. 목표 수익 3% 달성
        if entry_price is not None and float(current['close']) >= entry_price * 1.03:
            risk_signals.append(RiskSignal.TARGET_REACHED)
        
        return risk_signals