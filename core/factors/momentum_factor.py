"""
Momentum 팩터 계산 모듈 (30% 비중)
10개 지표로 구성
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import sqlite3

from utils.logger import setup_logger
from utils.korean_time import now_kst


logger = setup_logger(__name__)


class MomentumFactor:
    """Momentum 팩터 계산 클래스"""
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로
        """
        self.logger = setup_logger(__name__)
        
        if db_path is None:
            from pathlib import Path
            db_dir = Path(__file__).parent.parent.parent / "data"
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
    
    def calculate_momentum_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """
        Momentum 팩터 점수 계산 (0-100점)
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            Dict: {
                'momentum_score': float,  # 최종 점수 (0-100)
                'price_momentum_score': float,  # 가격 모멘텀 (40%)
                'volume_momentum_score': float,  # 거래량 모멘텀 (25%)
                'relative_strength_score': float,  # 상대 강도 (20%)
                'persistence_score': float,  # 지속성 (15%)
                'details': Dict  # 상세 지표
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 가격 데이터 조회
            price_data = self._get_price_history(stock_code, date, days=252)  # 1년치
            
            if price_data is None or len(price_data) < 20:
                return {
                    'momentum_score': 0.0,
                    'price_momentum_score': 0.0,
                    'volume_momentum_score': 0.0,
                    'relative_strength_score': 0.0,
                    'persistence_score': 0.0,
                    'details': {}
                }
            
            # 1. 가격 모멘텀 (40%)
            price_momentum_score = self._calculate_price_momentum(price_data)
            
            # 2. 거래량 모멘텀 (25%)
            volume_momentum_score = self._calculate_volume_momentum(price_data)
            
            # 3. 상대 강도 (20%)
            relative_strength_score = self._calculate_relative_strength(stock_code, date, price_data)
            
            # 4. 모멘텀 지속성 (15%)
            persistence_score = self._calculate_persistence(price_data)
            
            # 최종 점수 계산
            momentum_score = (
                price_momentum_score * 0.40 +
                volume_momentum_score * 0.25 +
                relative_strength_score * 0.20 +
                persistence_score * 0.15
            )
            
            return {
                'momentum_score': min(100.0, max(0.0, momentum_score)),
                'price_momentum_score': price_momentum_score,
                'volume_momentum_score': volume_momentum_score,
                'relative_strength_score': relative_strength_score,
                'persistence_score': persistence_score,
                'details': {
                    'returns_1m': self._calculate_return(price_data, days=20),
                    'returns_3m': self._calculate_return(price_data, days=60),
                    'returns_6m': self._calculate_return(price_data, days=120),
                    'returns_12m': self._calculate_return(price_data, days=252),
                }
            }
            
        except Exception as e:
            self.logger.error(f"Momentum 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'momentum_score': 0.0,
                'price_momentum_score': 0.0,
                'volume_momentum_score': 0.0,
                'relative_strength_score': 0.0,
                'persistence_score': 0.0,
                'details': {}
            }
    
    def _calculate_price_momentum(self, price_data: pd.DataFrame) -> float:
        """가격 모멘텀 점수 계산 (40%)"""
        try:
            if len(price_data) < 252:
                return 0.0
            
            current_price = price_data.iloc[-1]['close']
            
            # 1. 1개월 수익률 (40%)
            if len(price_data) >= 20:
                price_20d_ago = price_data.iloc[-20]['close']
                returns_1m = ((current_price - price_20d_ago) / price_20d_ago) * 100
                returns_1m_score = self._normalize(returns_1m, -10, 20)
            else:
                returns_1m_score = 0
            
            # 2. 3개월 수익률 (30%)
            if len(price_data) >= 60:
                price_60d_ago = price_data.iloc[-60]['close']
                returns_3m = ((current_price - price_60d_ago) / price_60d_ago) * 100
                returns_3m_score = self._normalize(returns_3m, -15, 30)
            else:
                returns_3m_score = 0
            
            # 3. 6개월 수익률 (20%)
            if len(price_data) >= 120:
                price_120d_ago = price_data.iloc[-120]['close']
                returns_6m = ((current_price - price_120d_ago) / price_120d_ago) * 100
                returns_6m_score = self._normalize(returns_6m, -20, 40)
            else:
                returns_6m_score = 0
            
            # 4. 12개월 수익률 (10%)
            if len(price_data) >= 252:
                price_252d_ago = price_data.iloc[-252]['close']
                returns_12m = ((current_price - price_252d_ago) / price_252d_ago) * 100
                returns_12m_score = self._normalize(returns_12m, -30, 60)
            else:
                returns_12m_score = 0
            
            price_momentum_score = (
                returns_1m_score * 0.40 +
                returns_3m_score * 0.30 +
                returns_6m_score * 0.20 +
                returns_12m_score * 0.10
            )
            
            return min(100.0, max(0.0, price_momentum_score))
            
        except Exception as e:
            self.logger.error(f"가격 모멘텀 계산 오류: {e}")
            return 0.0
    
    def _calculate_volume_momentum(self, price_data: pd.DataFrame) -> float:
        """거래량 모멘텀 점수 계산 (25%)"""
        try:
            if 'volume' not in price_data.columns or len(price_data) < 120:
                return 0.0
            
            # 1. 단기 거래량 추세 1개월 (60%)
            if len(price_data) >= 60:
                ma20 = price_data['volume'].tail(20).mean()
                ma60 = price_data['volume'].tail(60).mean()
                if ma60 > 0:
                    volume_trend_1m = ((ma20 / ma60) - 1) * 100
                    volume_trend_1m_score = self._normalize(volume_trend_1m, -30, 50)
                else:
                    volume_trend_1m_score = 0
            else:
                volume_trend_1m_score = 0
            
            # 2. 중기 거래량 추세 3개월 (40%)
            if len(price_data) >= 120:
                ma60 = price_data['volume'].tail(60).mean()
                ma120 = price_data['volume'].tail(120).mean()
                if ma120 > 0:
                    volume_trend_3m = ((ma60 / ma120) - 1) * 100
                    volume_trend_3m_score = self._normalize(volume_trend_3m, -20, 40)
                else:
                    volume_trend_3m_score = 0
            else:
                volume_trend_3m_score = 0
            
            volume_momentum_score = (
                volume_trend_1m_score * 0.60 +
                volume_trend_3m_score * 0.40
            )
            
            return min(100.0, max(0.0, volume_momentum_score))
            
        except Exception as e:
            self.logger.error(f"거래량 모멘텀 계산 오류: {e}")
            return 0.0
    
    def _calculate_relative_strength(self, stock_code: str, date: str, price_data: pd.DataFrame) -> float:
        """상대 강도 점수 계산 (20%)"""
        try:
            # 시장 대비 상대 강도 (50%)
            # TODO: KOSPI 데이터 조회 필요
            relative_market_score = 50.0  # 임시값
            
            # 섹터 대비 상대 강도 (50%)
            # TODO: 섹터 데이터 조회 필요
            relative_sector_score = 50.0  # 임시값
            
            relative_strength_score = (
                relative_market_score * 0.50 +
                relative_sector_score * 0.50
            )
            
            return min(100.0, max(0.0, relative_strength_score))
            
        except Exception as e:
            self.logger.error(f"상대 강도 계산 오류: {e}")
            return 0.0
    
    def _calculate_persistence(self, price_data: pd.DataFrame) -> float:
        """모멘텀 지속성 점수 계산 (15%)"""
        try:
            if len(price_data) < 20:
                return 0.0
            
            # 1. 상승일 비율 (40%)
            recent_20 = price_data.tail(20)
            if 'returns_1d' in recent_20.columns:
                up_days = (recent_20['returns_1d'] > 0).sum()
                up_days_ratio = (up_days / 20) * 100
                up_days_ratio_score = self._normalize(up_days_ratio, 30, 70)
            else:
                # returns_1d가 없으면 close 비교
                up_days = 0
                for i in range(1, len(recent_20)):
                    if recent_20.iloc[i]['close'] > recent_20.iloc[i-1]['close']:
                        up_days += 1
                up_days_ratio = (up_days / (len(recent_20) - 1)) * 100
                up_days_ratio_score = self._normalize(up_days_ratio, 30, 70)
            
            # 2. 52주 신고가 근접도 (30%)
            if len(price_data) >= 252:
                current_price = price_data.iloc[-1]['close']
                high_52w = price_data.tail(252)['high'].max()
                if high_52w > 0:
                    proximity_to_high = (current_price / high_52w) * 100
                    proximity_score = self._normalize(proximity_to_high, 70, 100)
                else:
                    proximity_score = 0
            else:
                proximity_score = 0
            
            # 3. 이동평균 정렬 (30%)
            # TODO: MA 정렬 점수 계산
            ma_alignment_score = 50.0  # 임시값
            
            persistence_score = (
                up_days_ratio_score * 0.40 +
                proximity_score * 0.30 +
                ma_alignment_score * 0.30
            )
            
            return min(100.0, max(0.0, persistence_score))
            
        except Exception as e:
            self.logger.error(f"지속성 계산 오류: {e}")
            return 0.0
    
    def _get_price_history(self, stock_code: str, date: str, days: int = 252) -> Optional[pd.DataFrame]:
        """가격 이력 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT date, open, high, low, close, volume, returns_1d
                    FROM daily_prices
                    WHERE stock_code = ? AND date <= ?
                    ORDER BY date DESC
                    LIMIT ?
                '''
                df = pd.read_sql_query(query, conn, params=(stock_code, date, days))
                
                if df.empty:
                    return None
                
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                
                return df
                
        except Exception as e:
            self.logger.error(f"가격 이력 조회 오류: {e}")
            return None
    
    def _calculate_return(self, price_data: pd.DataFrame, days: int) -> float:
        """수익률 계산"""
        try:
            if len(price_data) < days:
                return 0.0
            
            current_price = price_data.iloc[-1]['close']
            past_price = price_data.iloc[-days]['close']
            
            if past_price > 0:
                return ((current_price - past_price) / past_price) * 100
            return 0.0
            
        except Exception as e:
            return 0.0
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """값을 0-100 스케일로 정규화 (높을수록 좋음)"""
        if value <= min_val:
            return 0.0
        elif value >= max_val:
            return 100.0
        else:
            return ((value - min_val) / (max_val - min_val)) * 100.0



