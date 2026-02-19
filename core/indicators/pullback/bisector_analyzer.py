"""
이등분선 분석 모듈
"""

import pandas as pd
from .types import BisectorStatus
from core.indicators.bisector_line import BisectorLine


class BisectorAnalyzer:
    """이등분선 분석 클래스"""
    
    @staticmethod
    def analyze_bisector_status(data: pd.DataFrame, tolerance: float = 0.005) -> BisectorStatus:
        """이등분선 지지/저항 상태 분석"""
        if len(data) < 5:
            return BisectorStatus.BROKEN
        
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            if bisector_line is None or bisector_line.empty:
                return BisectorStatus.BROKEN
            
            current_price = float(data['close'].iloc[-1])
            current_bisector = float(bisector_line.iloc[-1])
            
            if pd.isna(current_bisector) or current_bisector <= 0:
                return BisectorStatus.BROKEN
            
            # 이등분선 대비 현재가 위치
            price_ratio = current_price / current_bisector
            
            if price_ratio >= (1.0 + tolerance):
                return BisectorStatus.HOLDING
            elif price_ratio >= (1.0 - tolerance):
                return BisectorStatus.NEAR_SUPPORT
            else:
                return BisectorStatus.BROKEN
                
        except Exception:
            return BisectorStatus.BROKEN
    
    @staticmethod
    def check_bisector_cross_up(data: pd.DataFrame, tolerance: float = 0.002) -> bool:
        """이등분선 상향 돌파 확인 (허용 오차 0.2%)"""
        if len(data) < 2:
            return False
        
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            if bisector_line is None or len(bisector_line) < 2:
                return False
            
            current_candle = data.iloc[-1]
            current_bisector = bisector_line.iloc[-1]
            
            if pd.isna(current_bisector) or current_bisector <= 0:
                return False
            
            # 현재 캔들이 이등분선을 상향 돌파했는지 확인
            open_price = float(current_candle['open'])
            close_price = float(current_candle['close'])
            
            # 허용 오차를 고려한 돌파 확인
            bisector_with_tolerance = current_bisector * (1.0 - tolerance)
            
            # 시가가 이등분선(허용오차 포함) 이하이고, 종가가 이등분선 이상인 경우
            crosses_up = (open_price <= bisector_with_tolerance and 
                         close_price >= current_bisector)
            
            return crosses_up
            
        except Exception:
            return False
    
    @staticmethod
    def get_bisector_status(current_price: float, bisector_line: float) -> BisectorStatus:
        """지지선 상태 판단 (제시된 로직 적용)"""
        if bisector_line is None or pd.isna(bisector_line) or bisector_line == 0:
            return BisectorStatus.BROKEN
        
        diff_pct = (current_price - bisector_line) / bisector_line
        
        if diff_pct >= 0.005:  # +0.5% 이상
            return BisectorStatus.HOLDING
        elif diff_pct >= -0.005:  # ±0.5% 범위  
            return BisectorStatus.NEAR_SUPPORT
        else:  # -0.5% 미만
            return BisectorStatus.BROKEN
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인 (기존 호환성)"""
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            current_price = data['close'].iloc[-1]
            bl = bisector_line.iloc[-1]
            
            status = BisectorAnalyzer.get_bisector_status(current_price, bl)
            return status in [BisectorStatus.HOLDING, BisectorStatus.NEAR_SUPPORT]
        except:
            return False