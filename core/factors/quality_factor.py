"""
Quality 팩터 계산 모듈 (20% 비중)
15개 지표로 구성
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


class QualityFactor:
    """Quality 팩터 계산 클래스"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
    
    def calculate_quality_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """Quality 팩터 점수 계산 (0-100점)"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            financial_data = self._get_financial_data(stock_code, date)
            price_data = self._get_price_data(stock_code, date)
            
            if financial_data is None:
                return {
                    'quality_score': 0.0, 'profitability_score': 0.0,
                    'stability_score': 0.0, 'cashflow_quality_score': 0.0,
                    'earnings_quality_score': 0.0, 'details': {}
                }
            
            profitability_score = self._calculate_profitability_score(financial_data)
            stability_score = self._calculate_stability_score(financial_data)
            cashflow_quality_score = self._calculate_cashflow_quality(financial_data, price_data)
            earnings_quality_score = self._calculate_earnings_quality(stock_code, date)
            
            quality_score = (
                profitability_score * 0.35 + stability_score * 0.30 +
                cashflow_quality_score * 0.20 + earnings_quality_score * 0.15
            )
            
            return {
                'quality_score': min(100.0, max(0.0, quality_score)),
                'profitability_score': profitability_score,
                'stability_score': stability_score,
                'cashflow_quality_score': cashflow_quality_score,
                'earnings_quality_score': earnings_quality_score,
                'details': {
                    'roe': financial_data.get('roe'), 'roa': financial_data.get('roa'),
                    'roic': financial_data.get('roic'), 'debt_ratio': financial_data.get('debt_ratio'),
                }
            }
        except Exception as e:
            self.logger.error(f"Quality 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'quality_score': 0.0, 'profitability_score': 0.0,
                'stability_score': 0.0, 'cashflow_quality_score': 0.0,
                'earnings_quality_score': 0.0, 'details': {}
            }
    
    def _calculate_profitability_score(self, financial_data: Dict) -> float:
        try:
            roe = financial_data.get('roe', 0) or 0
            roe_score = self._normalize(roe, 0, 30)
            operating_margin = financial_data.get('operating_margin', 0) or 0
            operating_margin_score = self._normalize(operating_margin, 0, 25)
            net_margin = financial_data.get('net_margin', 0) or 0
            net_margin_score = self._normalize(net_margin, 0, 20)
            return min(100.0, max(0.0, roe_score * 0.50 + operating_margin_score * 0.25 + net_margin_score * 0.25))
        except Exception as e:
            self.logger.error(f"수익성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_stability_score(self, financial_data: Dict) -> float:
        try:
            debt_ratio = financial_data.get('debt_ratio', 0) or 0
            return min(100.0, max(0.0, self._normalize_inverse(debt_ratio, 0, 200)))
        except Exception as e:
            self.logger.error(f"재무 안정성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_cashflow_quality(self, financial_data: Dict, price_data: Optional[Dict]) -> float:
        try:
            return 50.0  # 중립 점수 (현금흐름 데이터 없음)
        except Exception as e:
            self.logger.error(f"현금창출력 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_earnings_quality(self, stock_code: str, date: str) -> float:
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
            self.logger.error(f"수익 안정성 계산 오류: {e}")
            return 0.0
    
    def _get_financial_data(self, stock_code: str, date: str) -> Optional[Dict]:
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT roe, operating_margin, net_margin, debt_ratio
                    FROM financial_statements
                    WHERE stock_code = %s AND report_date <= %s
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))
                row = cursor.fetchone()
                if row:
                    return {
                        'roe': row[0] if row[0] is not None else 0,
                        'roa': None, 'roic': None,
                        'operating_margin': row[1] if row[1] is not None else 0,
                        'net_margin': row[2] if row[2] is not None else 0,
                        'debt_ratio': row[3] if row[3] is not None else 0,
                        'interest_coverage': None, 'current_ratio': None,
                        'quick_ratio': None, 'net_debt_ratio': None,
                        'fcf_yield': None, 'ocf_to_ni': None,
                        'capex_ratio': None, 'cash_ratio': None,
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
