"""
Value 팩터 계산 모듈 (30% 비중)
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


class ValueFactor:
    """Value 팩터 계산 클래스"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
    
    def calculate_value_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """Value 팩터 점수 계산 (0-100점)"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            financial_data = self._get_financial_data(stock_code, date)
            price_data = self._get_price_data(stock_code, date)
            
            if financial_data is None or price_data is None:
                return {
                    'value_score': 0.0, 'valuation_score': 0.0, 'dividend_score': 0.0,
                    'asset_value_score': 0.0, 'stability_score': 0.0, 'details': {}
                }
            
            valuation_score = self._calculate_valuation_score(financial_data, price_data)
            dividend_score = self._calculate_dividend_score(financial_data, price_data)
            asset_value_score = self._calculate_asset_value_score(financial_data, price_data)
            stability_score = self._calculate_stability_score(stock_code, date)
            
            value_score = (
                valuation_score * 0.40 + dividend_score * 0.20 +
                asset_value_score * 0.20 + stability_score * 0.20
            )
            
            return {
                'value_score': min(100.0, max(0.0, value_score)),
                'valuation_score': valuation_score,
                'dividend_score': dividend_score,
                'asset_value_score': asset_value_score,
                'stability_score': stability_score,
                'details': {
                    'per': financial_data.get('per'), 'pbr': financial_data.get('pbr'),
                    'pcr': financial_data.get('pcr'), 'psr': financial_data.get('psr'),
                    'dividend_yield': financial_data.get('dividend_yield'),
                }
            }
        except Exception as e:
            self.logger.error(f"Value 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'value_score': 0.0, 'valuation_score': 0.0, 'dividend_score': 0.0,
                'asset_value_score': 0.0, 'stability_score': 0.0, 'details': {}
            }
    
    def _calculate_valuation_score(self, financial_data: Dict, price_data: Dict) -> float:
        try:
            per = financial_data.get('per')
            per_score = self._normalize_inverse(per, 3, 30) if per and per > 0 else 0
            pbr = financial_data.get('pbr')
            pbr_score = self._normalize_inverse(pbr, 0.5, 3.0) if pbr and pbr > 0 else 0
            pcr = financial_data.get('pcr')
            pcr_score = self._normalize_inverse(pcr, 5, 20) if pcr and pcr > 0 else 0
            psr = financial_data.get('psr')
            psr_score = self._normalize_inverse(psr, 0.5, 3.0) if psr and psr > 0 else 0
            return min(100.0, max(0.0, per_score * 0.30 + pbr_score * 0.30 + pcr_score * 0.20 + psr_score * 0.20))
        except Exception as e:
            self.logger.error(f"밸류에이션 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_dividend_score(self, financial_data: Dict, price_data: Dict) -> float:
        try:
            dividend_yield = financial_data.get('dividend_yield', 0)
            dividend_yield_score = self._normalize(dividend_yield, 0, 5.0)
            dividend_growth = financial_data.get('dividend_growth_3yr', 0)
            dividend_growth_score = self._normalize(dividend_growth, -5, 15)
            dividend_capacity = financial_data.get('dividend_capacity', 0)
            dividend_capacity_score = self._normalize(dividend_capacity, 0, 70)
            return min(100.0, max(0.0, dividend_yield_score * 0.50 + dividend_growth_score * 0.30 + dividend_capacity_score * 0.20))
        except Exception as e:
            self.logger.error(f"배당 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_asset_value_score(self, financial_data: Dict, price_data: Dict) -> float:
        try:
            discount_to_nav = financial_data.get('discount_to_nav', 0)
            nav_score = self._normalize(discount_to_nav, -50, 50)
            liquidation_margin = financial_data.get('liquidation_margin', 0)
            liquidation_score = self._normalize(liquidation_margin, -30, 30)
            return min(100.0, max(0.0, nav_score * 0.60 + liquidation_score * 0.40))
        except Exception as e:
            self.logger.error(f"자산가치 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_stability_score(self, stock_code: str, date: str) -> float:
        try:
            earnings_data = self._get_earnings_history(stock_code, date, years=5)
            if earnings_data is None or len(earnings_data) < 3:
                return 0.0
            earnings_values = [e['net_income'] for e in earnings_data if e['net_income']]
            if len(earnings_values) < 3:
                return 0.0
            mean_earnings = np.mean(earnings_values)
            if mean_earnings == 0:
                return 0.0
            volatility = np.std(earnings_values) / abs(mean_earnings)
            stability = 1 / (1 + volatility)
            return min(100.0, max(0.0, stability * 100))
        except Exception as e:
            self.logger.error(f"안정성 점수 계산 오류: {e}")
            return 0.0
    
    def _get_financial_data(self, stock_code: str, date: str) -> Optional[Dict]:
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT per, pbr, psr, dividend_yield, roe,
                           debt_ratio, operating_margin, net_margin,
                           revenue, operating_profit, net_income
                    FROM financial_statements
                    WHERE stock_code = %s AND report_date <= %s
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))
                row = cursor.fetchone()
                if row:
                    return {
                        'per': row[0], 'pbr': row[1], 'pcr': None, 'psr': row[2],
                        'dividend_yield': row[3], 'dividend_growth_3yr': None,
                        'dividend_capacity': None, 'discount_to_nav': None,
                        'liquidation_margin': None, 'roe': row[4], 'roa': None,
                        'net_income': row[10], 'equity': None, 'debt_ratio': row[5],
                        'operating_margin': row[6], 'net_margin': row[7],
                        'revenue': row[8], 'operating_profit': row[9],
                    }
                return None
        except Exception as e:
            self.logger.error(f"재무 데이터 조회 오류: {e}")
            return None
    
    def _get_price_data(self, stock_code: str, date: str) -> Optional[Dict]:
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT close, market_cap
                    FROM daily_prices
                    WHERE stock_code = %s AND date = %s
                ''', (stock_code, date))
                row = cursor.fetchone()
                if row:
                    close = row[0]
                    market_cap = row[1]
                    if market_cap is None or market_cap <= 0:
                        self.logger.warning(f"⚠️ [{stock_code}] 시가총액 NULL 또는 0")
                        return None
                    return {'close': close, 'market_cap': market_cap}
                return None
        except Exception as e:
            self.logger.error(f"가격 데이터 조회 오류: {e}")
            return None
    
    def _get_earnings_history(self, stock_code: str, date: str, years: int = 5) -> Optional[List[Dict]]:
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT report_date, net_income
                    FROM financial_statements
                    WHERE stock_code = %s AND report_date <= %s
                    ORDER BY report_date DESC
                    LIMIT %s
                ''', (stock_code, date, years * 4))
                rows = cursor.fetchall()
                return [{'report_date': r[0], 'net_income': r[1]} for r in rows]
        except Exception as e:
            self.logger.error(f"이익 이력 조회 오류: {e}")
            return None
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        if value <= min_val: return 0.0
        elif value >= max_val: return 100.0
        else: return ((value - min_val) / (max_val - min_val)) * 100.0
    
    def _normalize_inverse(self, value: float, min_val: float, max_val: float) -> float:
        if value <= min_val: return 100.0
        elif value >= max_val: return 0.0
        else: return ((max_val - value) / (max_val - min_val)) * 100.0
