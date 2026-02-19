"""
거래량 분석 모듈
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from .types import VolumeAnalysis


class VolumeAnalyzer:
    """거래량 분석 클래스"""
    
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산 (당일 최대 거래량을 실시간 추적)"""
        try:
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
            else:
                dates = pd.to_datetime(data.index).normalize()
            
            # 당일 누적 최대 거래량 (양봉/음봉 구분없이)
            daily_baseline = data['volume'].groupby(dates).cummax()
            
            return daily_baseline
            
        except Exception:
            # 날짜 정보가 없으면 전체 기간 중 최대값 사용
            max_vol = data['volume'].max()
            return pd.Series([max_vol] * len(data), index=data.index)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10, 
                      baseline_volumes: Optional[pd.Series] = None) -> VolumeAnalysis:
        """거래량 분석 (개선된 기준거래량 사용)"""
        if 'volume' not in data.columns or len(data) < period:
            return VolumeAnalysis(0, 0, 0, 0, 'stable', False, False, False, False)
        
        volumes = data['volume'].astype(float).values
        current_volume = volumes[-1]
        
        # 기준 거래량: 당일 최대 거래량 (실시간) - 최적화: 이미 계산된 값 재사용
        if baseline_volumes is None:
            baseline_volumes = VolumeAnalyzer.calculate_daily_baseline_volume(data)
        baseline_volume = float(baseline_volumes.iloc[-1])
        
        # 최근 평균 거래량
        avg_recent_volume = np.mean(volumes[-period:])
        
        # 거래량 비율 계산
        volume_ratio = float(current_volume) / float(baseline_volume) if float(baseline_volume) > 0 else 0
        
        # 거래량 추세 분석
        if len(volumes) >= 3:
            recent_3 = volumes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                volume_trend = 'increasing'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                volume_trend = 'decreasing'
            else:
                volume_trend = 'stable'
        else:
            volume_trend = 'stable'
        
        # 거래량 상태 분석 (제시된 로직에 따라)
        is_volume_surge = current_volume > avg_recent_volume * 1.5
        is_low_volume = volume_ratio <= 0.25      # 25% 이하: 매우 적음
        is_moderate_volume = 0.25 < volume_ratio <= 0.50  # 25-50%: 보통
        is_high_volume = volume_ratio > 0.50      # 50% 이상: 과다
        
        return VolumeAnalysis(
            baseline_volume=baseline_volume,
            current_volume=current_volume,
            avg_recent_volume=avg_recent_volume,
            volume_ratio=volume_ratio,
            volume_trend=volume_trend,
            is_volume_surge=is_volume_surge,
            is_low_volume=is_low_volume,
            is_moderate_volume=is_moderate_volume,
            is_high_volume=is_high_volume
        )
    
    @staticmethod
    def analyze_price_trend(data: pd.DataFrame, period: int = 10) -> Dict[str, float]:
        """가격 트렌드 분석"""
        if len(data) < period:
            return {'trend_strength': 0, 'volatility': 0, 'momentum': 0}
        
        closes = data['close'].values[-period:]
        
        # 트렌드 강도 (선형 회귀 기울기)
        x = np.arange(len(closes))
        slope = np.polyfit(x, closes, 1)[0]
        trend_strength = slope / closes[0] if closes[0] > 0 else 0
        
        # 변동성 (표준편차/평균)
        volatility = np.std(closes) / np.mean(closes) if np.mean(closes) > 0 else 0
        
        # 모멘텀 (최근/이전 비율)
        momentum = (closes[-1] / closes[0] - 1) if closes[0] > 0 else 0
        
        return {
            'trend_strength': trend_strength,
            'volatility': volatility,
            'momentum': momentum
        }
    
    @staticmethod
    def check_low_volume_retrace(data: pd.DataFrame, lookback: int = 3, volume_threshold: float = 0.25) -> bool:
        """저거래량 조정 확인"""
        if len(data) < lookback + 1:
            return False
        
        # 기준 거래량
        baseline_volumes = VolumeAnalyzer.calculate_daily_baseline_volume(data)
        baseline = baseline_volumes.iloc[-1] if not baseline_volumes.empty else data['volume'].iloc[-lookback-1:]
        
        # 최근 lookback개 캔들의 거래량과 가격 변화 확인
        recent_data = data.iloc[-lookback:]
        
        # 모든 캔들이 저거래량인지 확인
        low_volume_all = (recent_data['volume'] < baseline * volume_threshold).all()
        
        # 가격이 하락 추세인지 확인
        price_changes = recent_data['close'].diff().fillna(0)
        downtrend_all = (price_changes.iloc[1:] <= 0).all() if len(price_changes) > 1 else False
        
        return low_volume_all and downtrend_all
    
    @staticmethod
    def check_volume_recovery(data: pd.DataFrame, retrace_lookback: int = 3) -> bool:
        """거래량 회복 여부 확인"""
        if len(data) <= retrace_lookback:
            return False
        
        current_volume = data['volume'].iloc[-1]
        
        # 조정 기간 동안의 최대 거래량
        retrace_volumes = data['volume'].iloc[-retrace_lookback-1:-1]  # 현재 제외하고 직전 retrace_lookback개
        max_retrace_volume = retrace_volumes.max() if len(retrace_volumes) > 0 else 0
        
        # 최근 평균 거래량
        recent_avg_volume = data['volume'].iloc[-10:].mean() if len(data) >= 10 else current_volume
        
        # 거래량 회복 조건: 조정 기간 최대값 초과 또는 최근 평균 초과
        return current_volume > max_retrace_volume or current_volume > recent_avg_volume
    
    @staticmethod
    def check_low_volume_breakout_signal(data: pd.DataFrame, baseline_volumes: pd.Series,
                                       min_low_volume_candles: int = 2,
                                       volume_threshold: float = 0.3) -> bool:
        """
        저거래량 조정 후 회복 양봉 신호 확인 (중복 제거된 버전)
        
        조건:
        - 기준거래량의 1/4 수준으로 연속 5개 이상 거래
        - 1/4 수준을 넘는 직전봉보다 위에 있는 양봉 출현
        
        Args:
            data: 3분봉 데이터
            baseline_volumes: 기준거래량 시리즈
            min_low_volume_candles: 최소 저거래량 캔들 개수 (기본 5개)
            volume_threshold: 저거래량 기준 (기준거래량의 25%)
            
        Returns:
            bool: 저거래량 회복 신호 여부
        """
        if len(data) < min_low_volume_candles + 1 or len(baseline_volumes) < len(data):
            return False
        
        try:
            # 공통 거래량 분석 활용 (중복 제거)
            # 순환 참조 방지를 위해 직접 구현
            volume_info = VolumeAnalyzer._analyze_volume_pattern_internal(data, baseline_volumes)
            
            # 현재 캔들
            current_candle = data.iloc[-1]
            
            # 1. 현재 캔들이 양봉인지 확인
            if current_candle['close'] <= current_candle['open']:
                return False
            
            # 2. 연속 저거래량 개수 확인 (공통 함수 결과 활용)
            if volume_info['consecutive_low_count'] < min_low_volume_candles:
                return False
            
            # 3. 현재 캔들의 거래량이 threshold를 넘는지 확인
            if volume_info['current_vs_threshold'] <= volume_threshold:
                return False
            
            # 4. 현재 캔들이 직전봉보다 위에 있는지 확인
            if len(data) < 2:
                return True  # 비교할 직전봉이 없으면 통과
            
            prev_candle = data.iloc[-2]
            
            # 직전캔들이 음봉이면 시가보다 높은지, 직전캔들이 양봉이면 종가보다 높은지 확인
            prev_is_bearish = prev_candle['close'] < prev_candle['open']
            
            if prev_is_bearish:
                # 직전봉이 음봉인 경우: 현재 캔들의 종가가 직전봉의 시가보다 높은지 확인
                if current_candle['close'] <= prev_candle['open']:
                    return False
            else:
                # 직전봉이 양봉인 경우: 현재 캔들의 종가가 직전봉의 종가보다 높은지 확인
                if current_candle['close'] <= prev_candle['close']:
                    return False
            
            return True
            
        except Exception:
            return False
    
    @staticmethod
    def _analyze_volume_pattern_internal(data: pd.DataFrame, baseline_volumes: pd.Series, period: int = 3) -> dict:
        """거래량 패턴 분석 (내부 구현 - 순환 참조 방지)"""
        
        if len(data) < period + 1 or len(baseline_volumes) < len(data):
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }
        
        try:
            # 현재 캔들 정보
            current_volume = data['volume'].iloc[-1]
            current_baseline = baseline_volumes.iloc[-1]
            
            # 직전 period개 캔들 분석 (현재 제외)
            recent_data = data.iloc[-period-1:-1]  # 현재 캔들 제외
            recent_baselines = baseline_volumes.iloc[-period-1:-1]
            
            # 연속 저거래량 개수 계산
            volume_ratios = recent_data['volume'] / recent_baselines
            low_volume_threshold = 0.25  # 25%
            
            consecutive_low_count = 0
            for ratio in volume_ratios.iloc[::-1]:  # 최근부터 거슬러 올라감
                if ratio <= low_volume_threshold:
                    consecutive_low_count += 1
                else:
                    break
            
            # 현재 캔들의 거래량 비율
            current_vs_threshold = current_volume / current_baseline if current_baseline > 0 else 0
            
            # 저거래량 구간 평균 비율
            avg_low_volume_ratio = volume_ratios.mean() if len(volume_ratios) > 0 else 0
            
            # 거래량 추세
            if len(volume_ratios) >= 2:
                recent_trend = volume_ratios.iloc[-2:].values
                if recent_trend[-1] > recent_trend[-2]:
                    volume_trend = 'increasing'
                elif recent_trend[-1] < recent_trend[-2]:
                    volume_trend = 'decreasing'
                else:
                    volume_trend = 'stable'
            else:
                volume_trend = 'stable'
            
            return {
                'consecutive_low_count': consecutive_low_count,
                'current_vs_threshold': current_vs_threshold,
                'avg_low_volume_ratio': avg_low_volume_ratio,
                'volume_trend': volume_trend
            }
            
        except Exception:
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }