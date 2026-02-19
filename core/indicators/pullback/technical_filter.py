"""
기술 지표 기반 필터
OHLCV 데이터를 조합하여 승률 향상을 위한 추가 필터 제공
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import time

class TechnicalFilter:
    """기술 지표 필터 - 3분봉 기준"""

    def __init__(self,
                 use_ma5_filter: bool = True,
                 use_price_change_filter: bool = True,
                 use_volume_filter: bool = True,
                 use_daily_trend_filter: bool = True,

                 # 필터 임계값 (균형형)
                 ma5_threshold: float = 0.50,  # 5캔들 이평 대비 +0.5% 이상
                 price_change_5_threshold: float = 0.85,  # 5캔들 전 대비 +0.85% 이상
                 volume_trend_threshold: float = 2.2,  # 거래량 2.2배 이상 증가
                 daily_trend_threshold: float = 22.0,  # 5일간 22% 이상 상승

                 # 10:00 이전 완화 모드
                 early_mode_until: str = "10:00",  # 이 시간까지 완화된 조건 적용
                 early_min_candles: int = 5):  # 초반에는 최소 5개 캔들만 필요

        self.use_ma5_filter = use_ma5_filter
        self.use_price_change_filter = use_price_change_filter
        self.use_volume_filter = use_volume_filter
        self.use_daily_trend_filter = use_daily_trend_filter

        self.ma5_threshold = ma5_threshold
        self.price_change_5_threshold = price_change_5_threshold
        self.volume_trend_threshold = volume_trend_threshold
        self.daily_trend_threshold = daily_trend_threshold

        self.early_mode_until = early_mode_until
        self.early_min_candles = early_min_candles

    def check_filter(self,
                    data: pd.DataFrame,
                    current_idx: Optional[int] = None,
                    daily_data: Optional[pd.DataFrame] = None,
                    current_time: Optional[time] = None) -> Dict:
        """
        기술 지표 필터 체크

        Args:
            data: 3분봉 데이터
            current_idx: 현재 캔들 인덱스 (None이면 마지막)
            daily_data: 일봉 데이터 (5일 추세 계산용)
            current_time: 현재 시간 (09:15 이전 완화 모드 판단용)

        Returns:
            {
                'passed': bool,  # 필터 통과 여부
                'reasons': List[str],  # 통과/실패 이유
                'indicators': Dict  # 계산된 지표값들
            }
        """
        if current_idx is None:
            current_idx = len(data) - 1

        available_candles = current_idx + 1

        # 09:15 이전 완화 모드 판단
        is_early_mode = self._is_early_trading_time(data, current_idx, current_time)

        # 최소 캔들 수 체크
        min_required = self.early_min_candles if is_early_mode else 20
        if available_candles < min_required:
            return {
                'passed': False,
                'reasons': [f'캔들 수 부족 ({available_candles}개 < {min_required}개 필요)'],
                'indicators': {},
                'early_mode': is_early_mode
            }

        # 지표 계산
        indicators = self._calculate_indicators(data, current_idx, daily_data)

        # 필터 적용
        passed = True
        reasons = []

        # 1. 5캔들 이평 필터
        if self.use_ma5_filter and indicators.get('price_vs_ma5') is not None:
            if indicators['price_vs_ma5'] >= self.ma5_threshold:
                reasons.append(f"✅ 5캔들이평: {indicators['price_vs_ma5']:.2f}% >= {self.ma5_threshold}%")
            else:
                passed = False
                reasons.append(f"❌ 5캔들이평: {indicators['price_vs_ma5']:.2f}% < {self.ma5_threshold}%")

        # 2. 5캔들 전 가격변화 필터
        if self.use_price_change_filter and indicators.get('price_change_5') is not None:
            if indicators['price_change_5'] >= self.price_change_5_threshold:
                reasons.append(f"✅ 5캔들가격변화: {indicators['price_change_5']:.2f}% >= {self.price_change_5_threshold}%")
            else:
                passed = False
                reasons.append(f"❌ 5캔들가격변화: {indicators['price_change_5']:.2f}% < {self.price_change_5_threshold}%")

        # 3. 거래량 증가 필터
        if self.use_volume_filter and indicators.get('volume_trend_5') is not None:
            if indicators['volume_trend_5'] >= self.volume_trend_threshold:
                reasons.append(f"✅ 거래량증가: {indicators['volume_trend_5']:.2f}배 >= {self.volume_trend_threshold}배")
            else:
                passed = False
                reasons.append(f"❌ 거래량증가: {indicators['volume_trend_5']:.2f}배 < {self.volume_trend_threshold}배")

        # 4. 일봉 추세 필터 (10:00 이후에만 적용)
        if self.use_daily_trend_filter and not is_early_mode:
            if indicators.get('daily_trend_5') is not None:
                if indicators['daily_trend_5'] >= self.daily_trend_threshold:
                    reasons.append(f"✅ 일봉5일추세: {indicators['daily_trend_5']:.2f}% >= {self.daily_trend_threshold}%")
                else:
                    passed = False
                    reasons.append(f"❌ 일봉5일추세: {indicators['daily_trend_5']:.2f}% < {self.daily_trend_threshold}%")

        return {
            'passed': passed,
            'reasons': reasons,
            'indicators': indicators,
            'early_mode': is_early_mode
        }

    def _is_early_trading_time(self, data: pd.DataFrame, current_idx: int, current_time: Optional[time]) -> bool:
        """10:00 이전인지 판단"""
        if current_time is not None:
            hour, minute = map(int, self.early_mode_until.split(':'))
            return current_time < time(hour, minute)

        # datetime 컬럼에서 시간 추출
        if 'datetime' in data.columns:
            current_datetime = data.iloc[current_idx]['datetime']
            if hasattr(current_datetime, 'time'):
                hour, minute = map(int, self.early_mode_until.split(':'))
                return current_datetime.time() < time(hour, minute)

        # 판단 불가시 False (보수적)
        return False

    def _calculate_indicators(self, data: pd.DataFrame, current_idx: int, daily_data: Optional[pd.DataFrame]) -> Dict:
        """기술 지표 계산"""
        indicators = {}

        current = data.iloc[current_idx]
        available_candles = current_idx + 1

        # 5개 이상 캔들이 있으면 5캔들 지표 계산
        if available_candles >= 5:
            recent_5 = data.iloc[max(0, current_idx-4):current_idx+1]  # 현재 포함 5개

            # 5캔들 이동평균 대비 가격 위치
            ma5 = recent_5['close'].mean()
            indicators['price_vs_ma5'] = (current['close'] - ma5) / ma5 * 100 if ma5 > 0 else None

            # 5캔들 전 대비 가격 변화
            if len(recent_5) >= 5 and recent_5['close'].iloc[0] > 0:
                indicators['price_change_5'] = (current['close'] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0] * 100
            else:
                indicators['price_change_5'] = None

            # 거래량 증가 추세 (첫 캔들 대비 현재 캔들)
            if len(recent_5) >= 5 and recent_5['volume'].iloc[0] > 0:
                indicators['volume_trend_5'] = current['volume'] / recent_5['volume'].iloc[0]
            else:
                indicators['volume_trend_5'] = None

        # 일봉 5일 추세
        if daily_data is not None and len(daily_data) >= 5:
            try:
                # 컬럼명 정규화
                if 'stck_clpr' in daily_data.columns:
                    daily_close = pd.to_numeric(daily_data['stck_clpr'], errors='coerce')
                else:
                    daily_close = pd.to_numeric(daily_data['close'], errors='coerce')

                # 최근 5일 (첫 행이 최신)
                if len(daily_close) >= 5 and daily_close.iloc[4] > 0:
                    indicators['daily_trend_5'] = (daily_close.iloc[0] - daily_close.iloc[4]) / daily_close.iloc[4] * 100
                else:
                    indicators['daily_trend_5'] = None
            except:
                indicators['daily_trend_5'] = None
        else:
            indicators['daily_trend_5'] = None

        return indicators

    @staticmethod
    def create_conservative_filter():
        """보수적 필터 (승률 최우선, 거래 수 감소)"""
        return TechnicalFilter(
            ma5_threshold=0.60,
            price_change_5_threshold=0.95,
            volume_trend_threshold=2.5,
            daily_trend_threshold=25.0
        )

    @staticmethod
    def create_balanced_filter():
        """균형 필터 (기본값)"""
        return TechnicalFilter()

    @staticmethod
    def create_aggressive_filter():
        """공격적 필터 (거래 기회 많음, 승률 낮음)"""
        return TechnicalFilter(
            ma5_threshold=0.40,
            price_change_5_threshold=0.70,
            volume_trend_threshold=1.8,
            daily_trend_threshold=20.0
        )
