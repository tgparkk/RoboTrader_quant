"""
캔들 분석 모듈
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from .types import CandleAnalysis


class CandleAnalyzer:
    """캔들 분석 클래스"""
    
    @staticmethod
    def is_recovery_candle(data: pd.DataFrame, index: int) -> bool:
        """회복 양봉 여부 확인"""
        if index < 0 or index >= len(data):
            return False
        
        candle = data.iloc[index]
        return candle['close'] > candle['open']  # 양봉
    
    @staticmethod
    def analyze_candle_size(data: pd.DataFrame, period: int = 20) -> Dict[str, float]:
        """캔들 크기 분석"""
        if len(data) < period:
            return {'body_ratio': 0, 'total_range': 0, 'expansion_ratio': 1.0}
        
        recent_data = data.iloc[-period:]
        current_candle = data.iloc[-1]
        
        # 캔들 몸체 크기
        current_body = abs(current_candle['close'] - current_candle['open'])
        current_range = current_candle['high'] - current_candle['low']
        
        # 몸체 비율 (전체 범위 대비)
        body_ratio = current_body / current_range if current_range > 0 else 0
        
        # 최근 평균 범위
        avg_range = (recent_data['high'] - recent_data['low']).mean()
        
        # 확대 비율
        expansion_ratio = current_range / avg_range if avg_range > 0 else 1.0
        
        return {
            'body_ratio': body_ratio,
            'total_range': current_range,
            'expansion_ratio': expansion_ratio
        }
    
    @staticmethod
    def check_overhead_supply(data: pd.DataFrame, lookback: int = 10, threshold_hits: int = 2) -> bool:
        """머리 위 물량 확인"""
        if len(data) < lookback + 1:
            return False
        
        current_high = data['high'].iloc[-1]
        
        # 과거 lookback 기간의 고가들 중 현재 고가보다 높은 것들
        past_highs = data['high'].iloc[-lookback-1:-1]  # 현재 제외
        overhead_levels = past_highs[past_highs > current_high * 1.01]  # 1% 이상 높은 수준
        
        # 임계값 이상의 머리 위 물량이 있는지 확인
        return len(overhead_levels) >= threshold_hits
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10, prev_close: Optional[float] = None) -> CandleAnalysis:
        """캔들 분석 (변곡캔들 검증 로직 강화)"""
        if len(data) < period:
            return CandleAnalysis(False, 0, 0, 0, 0, 'stable', False, False, False)
        
        current = data.iloc[-1]
        
        # 기본 캔들 정보
        is_bullish = float(current['close']) > float(current['open'])
        body_size = abs(float(current['close']) - float(current['open']))
        
        # 캔들 실체 크기 비율 계산 (실제 전일 종가 기준)
        if prev_close is None or prev_close <= 0:
            # prev_close가 제공되지 않았다면 직전 캔들 종가나 현재 시가 사용
            prev_close = float(data['close'].iloc[-2]) if len(data) >= 2 else float(current['open'])
        body_pct = (body_size / prev_close) * 100 if prev_close > 0 else 0
        
        # 캔듡 크기 계산 (high - low)
        candle_sizes = data['high'].astype(float).values - data['low'].astype(float).values
        current_candle_size = candle_sizes[-1]
        avg_recent_candle_size = np.mean(candle_sizes[-period:])
        
        # 캔들 크기 추세 분석
        if len(candle_sizes) >= 3:
            recent_3 = candle_sizes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                candle_trend = 'expanding'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                candle_trend = 'shrinking'
            else:
                candle_trend = 'stable'
        else:
            candle_trend = 'stable'
        
        # 캔들 크기 상태
        is_small_candle = current_candle_size < avg_recent_candle_size * 0.7
        is_large_candle = current_candle_size > avg_recent_candle_size * 1.3
        
        # 의미있는 실체 크기 검증 (제시된 로직: 0.5% 이상)
        is_meaningful_body = body_pct >= 0.5
        
        return CandleAnalysis(
            is_bullish=is_bullish,
            body_size=body_size,
            body_pct=body_pct,
            current_candle_size=current_candle_size,
            avg_recent_candle_size=avg_recent_candle_size,
            candle_trend=candle_trend,
            is_small_candle=is_small_candle,
            is_large_candle=is_large_candle,
            is_meaningful_body=is_meaningful_body
        )

    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.03, 
                          baseline_volume: Optional[float] = None) -> bool:
        """
        선행 상승 확인 (완화된 버전)
        
        조건:
        1. 현재가가 첫봉(09:00) 시가 대비 4% 이상 상승
        2. 현재시간부터 과거로 탐색하여 n개의 봉이 합해서 3% 이상 상승
        3. 하락할 때는 기준 거래량의 1/2 수준 유지
        4. 1/2를 넘는 거래량의 하락은 최대 1개만 허용
        
        Args:
            data: 분봉 데이터
            min_gain: 최소 상승률 (기본값: 2%)
            
        Returns:
            bool: 눌림목 선행 조건 만족 여부
        """
        if len(data) < 5:  # 최소 5개 봉 필요
            return False
        
        try:
            # 당일 데이터 추출
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
                today = dates.iloc[-1]
                today_data = data[dates == today].reset_index(drop=True)
                
                if len(today_data) < 5:
                    return False
            else:
                # datetime 정보가 없으면 전체 데이터를 당일로 간주
                today_data = data.copy()
            
            # 기준 거래량 계산 (최적화: 이미 계산된 값 재사용)
            if baseline_volume is None:
                baseline_volume = today_data['volume'].max()
            low_volume_threshold = baseline_volume * 0.5  # 1/2 수준
            
            # 현재 캔들이 양봉인지 확인 (완화: 연속 상승 패턴도 허용)
            current_candle = today_data.iloc[-1]
            
            # 기본 양봉 조건
            is_bullish = current_candle['close'] > current_candle['open']
            
            # 연속 상승 패턴 확인 (양봉이 아니어도 전체적 상승 흐름이면 허용)
            is_consecutive_rise = False
            if len(today_data) >= 3:  # 최소 3개 봉 확인
                # 최근 3개 봉의 전체적 상승 흐름 확인
                recent_candles = today_data.iloc[-3:]
                
                # 시작점과 끝점 비교로 전체 흐름 판단
                start_price = recent_candles.iloc[0]['low']  # 첫 번째 봉의 저가
                end_price = current_candle['close']          # 현재 봉의 종가
                
                # 전체적으로 상승했는지 확인 (중간에 음봉이 있어도 허용)
                if end_price > start_price:
                    # 추가로 고점들이 상승 추세인지 확인
                    highs = recent_candles['high'].values
                    # 최근 고점이 이전 고점들보다 높은 경우가 많은지 확인
                    rising_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
                    if rising_highs >= len(highs) // 2:  # 절반 이상이 상승
                        is_consecutive_rise = True
            
            # 디버그: 특정 시점 분석
            debug_mode = (abs(current_candle['close'] - 2440) < 10 or  # 391710 09:42
                         abs(current_candle['close'] - 35850) < 10 or  # 290650 10:00
                         abs(current_candle['close'] - 33950) < 10)    # 039200 09:30
            
            if not is_bullish and not is_consecutive_rise:
                return False
            
            # 추가 조건: 현재가가 첫봉(09:00) 시가 대비 +4% 이상 상승했는지 확인
            first_candle = today_data.iloc[0]  # 09:00 3분봉 (첫 번째 봉)
            first_candle_open = first_candle['open']  # 첫봉의 시가
            current_close = current_candle['close']
            
            if first_candle_open > 0:
                gain_from_first = (current_close - first_candle_open) / first_candle_open
                min_gain_from_first = 0.04  # 4%
                
                if debug_mode:
                    print(f"첫봉 시가 대비 상승률: {first_candle_open:.0f}→{current_close:.0f} = {gain_from_first*100:.1f}% (최소: {min_gain_from_first*100}%)")
                
                if gain_from_first < min_gain_from_first:
                    if debug_mode:
                        print(f"❌ 첫봉 시가 대비 상승률 부족: {gain_from_first*100:.1f}% < {min_gain_from_first*100}%")
                    return False
            else:
                # 첫봉 시가가 0인 경우 (비정상적 상황)
                if debug_mode:
                    print("⚠️ 첫봉 시가가 0 - 첫봉 대비 상승률 확인 불가")
                return False
            if debug_mode:
                print(f"\n🔍 [DEBUG] 09:42 선행상승 분석 시작")
                print(f"현재 캔들: {current_candle['close']:.0f}원 (양봉: {current_candle['close'] > current_candle['open']})")
                print(f"기준거래량: {baseline_volume:,.0f}, 1/2수준: {low_volume_threshold:,.0f}")
                print(f"당일 데이터 개수: {len(today_data)}")
            
            # 현재부터 과거로 탐색 (최대 20개 봉)
            lookback_period = min(20, len(today_data))
            
            # 다양한 구간에서 상승 패턴 찾기
            for start_offset in range(3, lookback_period):  # 최소 3개 봉부터 시작
                if start_offset >= len(today_data):
                    continue
                
                # 구간 데이터 (현재부터 start_offset 봉 전까지)
                segment_data = today_data.iloc[-start_offset-1:-1].reset_index(drop=True)
                
                if len(segment_data) < 3:
                    continue
                
                # 1. 상승률 체크: 구간 시작 저가 → 구간 내 최고가
                segment_start_low = segment_data['low'].iloc[0]
                segment_high = segment_data['high'].max()
                
                if segment_start_low > 0:
                    total_gain = (segment_high - segment_start_low) / segment_start_low
                    
                    if debug_mode:
                        print(f"구간[{start_offset}봉]: {segment_start_low:.0f}→{segment_high:.0f} = {total_gain*100:.1f}%")
                    
                    if total_gain >= min_gain:  # 2% 이상 상승 확인
                        
                        # 2. 하락 구간의 거래량 체크
                        high_volume_decline_count = 0
                        
                        for i in range(len(segment_data)):
                            candle = segment_data.iloc[i]
                            
                            # 음봉이면서 거래량이 1/2를 넘는 경우 카운트
                            if (candle['close'] < candle['open'] and 
                                candle['volume'] > low_volume_threshold):
                                high_volume_decline_count += 1
                        
                        if debug_mode:
                            print(f"  고거래량 하락 개수: {high_volume_decline_count}")
                        
                        # 3. 고거래량 하락이 1개 이하인지 확인
                        if high_volume_decline_count <= 1:
                            
                            # 4. 추가 검증: 현재 캔들이 회복 신호인지 확인
                            segment_low = segment_data['low'].min()
                            current_close = current_candle['close']
                            
                            if debug_mode:
                                print(f"  구간최저: {segment_low:.0f}, 현재가: {current_close:.0f}, 회복: {current_close > segment_low}")
                            
                            # 구간 내 최저점 대비 현재가가 상승했는지 확인
                            if current_close > segment_low:
                                if debug_mode:
                                    print(f"✅ 선행상승 조건 만족! (구간: {start_offset}봉)")
                                return True
            
            if debug_mode:
                print("❌ 선행상승 조건 미충족")
            
            return False
            
        except Exception:
            # 오류 시 기존 로직으로 폴백
            if len(data) >= 10:
                start_price = data['close'].iloc[-10]
                current_price = data['close'].iloc[-1]
                gain_pct = (current_price - start_price) / start_price if start_price > 0 else 0
                return gain_pct >= min_gain
            return False
    
    @staticmethod
    def _check_sustained_uptrend(segment_data: pd.DataFrame) -> bool:
        """
        구간 내 지속적 상승 패턴 확인
        
        조건:
        1. 최소 60% 이상의 봉이 상승 방향
        2. 큰 하락봉(2% 이상 하락)이 없음
        
        Args:
            segment_data: 구간 데이터
            
        Returns:
            bool: 지속적 상승 패턴 여부
        """
        try:
            if len(segment_data) < 2:
                return True  # 데이터 부족시 허용
            
            # 1. 상승 봉의 비율 체크
            price_changes = segment_data['close'].diff().iloc[1:]  # 첫 번째 NaN 제외
            if len(price_changes) == 0:
                return True
            
            up_count = (price_changes > 0).sum()
            up_ratio = up_count / len(price_changes)
            
            # 60% 이상이 상승 방향이어야 함
            if up_ratio < 0.6:
                return False
            
            # 2. 큰 하락봉 체크 (개별 봉의 하락률 2% 이상)
            for _, candle in segment_data.iterrows():
                open_price = candle['open']
                close_price = candle['close']
                
                if open_price > 0:
                    candle_change = (close_price - open_price) / open_price
                    # 개별 봉이 2% 이상 하락하면 지속적 상승 패턴 아님
                    if candle_change <= -0.02:
                        return False
            
            return True
            
        except Exception:
            return True  # 오류 시 허용

    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        if len(data) < period:
            return 'stable'
        
        closes = data['close'].values
        recent_closes = closes[-period:]
        
        # 선형 회귀로 추세 판단
        x = np.arange(len(recent_closes))
        slope = np.polyfit(x, recent_closes, 1)[0]
        
        if slope > 0:
            return 'uptrend'
        elif slope < 0:
            return 'downtrend'
        else:
            return 'stable'
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉)"""
        if len(data) < period:
            return None
        
        recent_lows = data['low'].values[-period:]
        return np.min(recent_lows)