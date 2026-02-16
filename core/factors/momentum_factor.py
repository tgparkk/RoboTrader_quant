"""
Momentum 팩터 계산 모듈 (30% 비중)
10개 지표로 구성
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import psycopg2

from utils.logger import setup_logger
from utils.korean_time import now_kst
from config.pg_helper import pg_connection


logger = setup_logger(__name__)


class MomentumFactor:
    """Momentum 팩터 계산 클래스"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
    
    def calculate_momentum_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """Momentum 팩터 점수 계산 (0-100점)"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            price_data = self._get_price_history(stock_code, date, days=252)
            
            if price_data is None or len(price_data) < 20:
                return {
                    'momentum_score': 0.0, 'price_momentum_score': 0.0,
                    'volume_momentum_score': 0.0, 'relative_strength_score': 0.0,
                    'persistence_score': 0.0, 'details': {}
                }
            
            price_momentum_score = self._calculate_price_momentum(price_data)
            volume_momentum_score = self._calculate_volume_momentum(price_data)
            relative_strength_score = self._calculate_relative_strength(stock_code, date, price_data)
            persistence_score = self._calculate_persistence(price_data)
            
            momentum_score = (
                price_momentum_score * 0.40 + volume_momentum_score * 0.25 +
                relative_strength_score * 0.20 + persistence_score * 0.15
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
                'momentum_score': 0.0, 'price_momentum_score': 0.0,
                'volume_momentum_score': 0.0, 'relative_strength_score': 0.0,
                'persistence_score': 0.0, 'details': {}
            }
    
    def _calculate_price_momentum(self, price_data: pd.DataFrame) -> float:
        try:
            if len(price_data) < 252:
                return 0.0
            current_price = price_data.iloc[-1]['close']
            
            returns_1m_score = 0
            if len(price_data) >= 20:
                r = ((current_price - price_data.iloc[-20]['close']) / price_data.iloc[-20]['close']) * 100
                returns_1m_score = self._normalize(r, -10, 20)
            
            returns_3m_score = 0
            if len(price_data) >= 60:
                r = ((current_price - price_data.iloc[-60]['close']) / price_data.iloc[-60]['close']) * 100
                returns_3m_score = self._normalize(r, -15, 30)
            
            returns_6m_score = 0
            if len(price_data) >= 120:
                r = ((current_price - price_data.iloc[-120]['close']) / price_data.iloc[-120]['close']) * 100
                returns_6m_score = self._normalize(r, -20, 40)
            
            returns_12m_score = 0
            if len(price_data) >= 252:
                r = ((current_price - price_data.iloc[-252]['close']) / price_data.iloc[-252]['close']) * 100
                returns_12m_score = self._normalize(r, -30, 60)
            
            return min(100.0, max(0.0,
                returns_1m_score * 0.40 + returns_3m_score * 0.30 +
                returns_6m_score * 0.20 + returns_12m_score * 0.10
            ))
        except Exception as e:
            self.logger.error(f"가격 모멘텀 계산 오류: {e}")
            return 0.0
    
    def _calculate_volume_momentum(self, price_data: pd.DataFrame) -> float:
        try:
            if 'volume' not in price_data.columns or len(price_data) < 120:
                return 0.0
            
            volume_trend_1m_score = 0
            if len(price_data) >= 60:
                ma20 = price_data['volume'].tail(20).mean()
                ma60 = price_data['volume'].tail(60).mean()
                if ma60 > 0:
                    volume_trend_1m_score = self._normalize(((ma20 / ma60) - 1) * 100, -30, 50)
            
            volume_trend_3m_score = 0
            if len(price_data) >= 120:
                ma60 = price_data['volume'].tail(60).mean()
                ma120 = price_data['volume'].tail(120).mean()
                if ma120 > 0:
                    volume_trend_3m_score = self._normalize(((ma60 / ma120) - 1) * 100, -20, 40)
            
            return min(100.0, max(0.0, volume_trend_1m_score * 0.60 + volume_trend_3m_score * 0.40))
        except Exception as e:
            self.logger.error(f"거래량 모멘텀 계산 오류: {e}")
            return 0.0
    
    def _calculate_relative_strength(self, stock_code: str, date: str, price_data: pd.DataFrame) -> float:
        try:
            return 50.0  # TODO: KOSPI/섹터 데이터 필요
        except Exception as e:
            self.logger.error(f"상대 강도 계산 오류: {e}")
            return 0.0
    
    def _calculate_persistence(self, price_data: pd.DataFrame) -> float:
        try:
            if len(price_data) < 20:
                return 0.0
            
            recent_20 = price_data.tail(20)
            if 'returns_1d' in recent_20.columns:
                up_days = (recent_20['returns_1d'] > 0).sum()
                up_days_ratio = (up_days / 20) * 100
            else:
                up_days = 0
                for i in range(1, len(recent_20)):
                    if recent_20.iloc[i]['close'] > recent_20.iloc[i-1]['close']:
                        up_days += 1
                up_days_ratio = (up_days / (len(recent_20) - 1)) * 100
            up_days_ratio_score = self._normalize(up_days_ratio, 30, 70)
            
            proximity_score = 0
            if len(price_data) >= 252:
                current_price = price_data.iloc[-1]['close']
                high_52w = price_data.tail(252)['high'].max()
                if high_52w > 0:
                    proximity_score = self._normalize((current_price / high_52w) * 100, 70, 100)
            
            ma_alignment_score = 50.0
            
            return min(100.0, max(0.0,
                up_days_ratio_score * 0.40 + proximity_score * 0.30 + ma_alignment_score * 0.30
            ))
        except Exception as e:
            self.logger.error(f"지속성 계산 오류: {e}")
            return 0.0
    
    def _get_price_history(self, stock_code: str, date: str, days: int = 252) -> Optional[pd.DataFrame]:
        try:
            with pg_connection() as conn:
                query = '''
                    SELECT date, open, high, low, close, volume, returns_1d
                    FROM daily_prices
                    WHERE stock_code = %s AND date <= %s
                    ORDER BY date DESC
                    LIMIT %s
                '''
                df = pd.read_sql_query(query, conn, params=(stock_code, date, days))
                if df.empty:
                    return None
                try:
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                    df = df.dropna(subset=['date'])
                except Exception:
                    return None
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception as e:
            self.logger.error(f"가격 이력 조회 오류: {e}")
            return None
    
    def _calculate_return(self, price_data: pd.DataFrame, days: int) -> float:
        try:
            if len(price_data) < days:
                return 0.0
            current_price = price_data.iloc[-1]['close']
            past_price = price_data.iloc[-days]['close']
            if past_price > 0:
                return ((current_price - past_price) / past_price) * 100
            return 0.0
        except Exception:
            return 0.0
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        if value <= min_val: return 0.0
        elif value >= max_val: return 100.0
        else: return ((value - min_val) / (max_val - min_val)) * 100.0
