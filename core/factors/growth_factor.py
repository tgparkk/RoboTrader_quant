"""
Growth 팩터 계산 모듈 (20% 비중)
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


class GrowthFactor:
    """Growth 팩터 계산 클래스"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
    
    def calculate_growth_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """Growth 팩터 점수 계산 (0-100점)"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            financial_data = self._get_financial_history(stock_code, date, years=5)
            
            if financial_data is None or len(financial_data) < 2:
                return {
                    'growth_score': 0.0, 'revenue_growth_score': 0.0,
                    'earnings_growth_score': 0.0, 'growth_efficiency_score': 0.0,
                    'sustainability_score': 0.0, 'details': {}
                }
            
            revenue_growth_score = self._calculate_revenue_growth(financial_data)
            earnings_growth_score = self._calculate_earnings_growth(financial_data)
            growth_efficiency_score = self._calculate_growth_efficiency(financial_data)
            sustainability_score = self._calculate_sustainability(financial_data)
            
            growth_score = (
                revenue_growth_score * 0.30 + earnings_growth_score * 0.30 +
                growth_efficiency_score * 0.25 + sustainability_score * 0.15
            )
            
            return {
                'growth_score': min(100.0, max(0.0, growth_score)),
                'revenue_growth_score': revenue_growth_score,
                'earnings_growth_score': earnings_growth_score,
                'growth_efficiency_score': growth_efficiency_score,
                'sustainability_score': sustainability_score,
                'details': {
                    'revenue_growth_1yr': self._calculate_growth_rate(financial_data, 'revenue', 1),
                    'earnings_growth_1yr': self._calculate_growth_rate(financial_data, 'net_income', 1),
                }
            }
        except Exception as e:
            self.logger.error(f"Growth 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'growth_score': 0.0, 'revenue_growth_score': 0.0,
                'earnings_growth_score': 0.0, 'growth_efficiency_score': 0.0,
                'sustainability_score': 0.0, 'details': {}
            }
    
    def _calculate_revenue_growth(self, financial_data: List[Dict]) -> float:
        try:
            if len(financial_data) < 2: return 0.0
            r1 = self._normalize(self._calculate_growth_rate(financial_data, 'revenue', 1), -10, 30)
            r3 = self._normalize(self._calculate_cagr(financial_data, 'revenue', 3), -5, 25)
            r5 = self._normalize(self._calculate_cagr(financial_data, 'revenue', 5), 0, 20)
            return min(100.0, max(0.0, r1 * 0.50 + r3 * 0.30 + r5 * 0.20))
        except Exception as e:
            self.logger.error(f"매출 성장 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_earnings_growth(self, financial_data: List[Dict]) -> float:
        try:
            if len(financial_data) < 2: return 0.0
            e1 = self._normalize(self._calculate_growth_rate(financial_data, 'net_income', 1), -20, 50)
            e3 = self._normalize(self._calculate_cagr(financial_data, 'net_income', 3), -10, 40)
            op = self._normalize(self._calculate_growth_rate(financial_data, 'operating_profit', 1), -15, 40)
            return min(100.0, max(0.0, e1 * 0.40 + e3 * 0.30 + op * 0.30))
        except Exception as e:
            self.logger.error(f"이익 성장 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_growth_efficiency(self, financial_data: List[Dict]) -> float:
        try:
            if len(financial_data) < 2: return 0.0
            revenue_growth = self._calculate_growth_rate(financial_data, 'revenue', 1)
            earnings_growth = self._calculate_growth_rate(financial_data, 'net_income', 1)
            earnings_leverage = earnings_growth / revenue_growth if revenue_growth != 0 else 0
            earnings_leverage_score = self._normalize(earnings_leverage, 0, 3.0)
            
            current_margin = financial_data[-1].get('operating_margin') or 0
            prev_margin = financial_data[-2].get('operating_margin') or 0
            margin_expansion_score = self._normalize(current_margin - prev_margin, -5, 5)
            
            current_roe = financial_data[-1].get('roe') or 0
            prev_roe = financial_data[-2].get('roe') or 0
            roe_improvement_score = self._normalize(current_roe - prev_roe, -5, 10)
            
            return min(100.0, max(0.0,
                earnings_leverage_score * 0.40 + margin_expansion_score * 0.35 + roe_improvement_score * 0.25
            ))
        except Exception as e:
            self.logger.error(f"성장 효율성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_sustainability(self, financial_data: List[Dict]) -> float:
        try:
            if len(financial_data) < 4: return 0.0
            growth_quarters = 0
            for i in range(1, min(5, len(financial_data))):
                current_revenue = financial_data[-i].get('revenue') or 0
                prev_revenue = financial_data[-i-1].get('revenue') or 0 if len(financial_data) > i else 0
                if prev_revenue > 0 and current_revenue > prev_revenue:
                    growth_quarters += 1
            return min(100.0, max(0.0, (growth_quarters / 4) * 100))
        except Exception as e:
            self.logger.error(f"성장 지속성 계산 오류: {e}")
            return 0.0
    
    def _get_financial_history(self, stock_code: str, date: str, years: int = 5) -> Optional[List[Dict]]:
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT report_date, revenue, operating_profit, net_income,
                           operating_margin, roe
                    FROM financial_statements
                    WHERE stock_code = %s AND report_date <= %s
                    ORDER BY report_date DESC
                    LIMIT %s
                ''', (stock_code, date, years * 4))
                rows = cursor.fetchall()
                return [
                    {'report_date': r[0], 'revenue': r[1], 'operating_profit': r[2],
                     'net_income': r[3], 'operating_margin': r[4], 'roe': r[5]}
                    for r in rows
                ]
        except Exception as e:
            self.logger.error(f"재무 이력 조회 오류: {e}")
            return None
    
    def _calculate_growth_rate(self, financial_data: List[Dict], field: str, years: int = 1) -> float:
        try:
            if len(financial_data) < years + 1: return 0.0
            current_value = financial_data[-1].get(field) or 0
            past_value = financial_data[-years-1].get(field) or 0 if len(financial_data) > years else 0
            if past_value == 0: return 0.0
            return ((current_value - past_value) / abs(past_value)) * 100
        except Exception:
            return 0.0
    
    def _calculate_cagr(self, financial_data: List[Dict], field: str, years: int) -> float:
        try:
            if len(financial_data) < years + 1: return 0.0
            current_value = financial_data[-1].get(field) or 0
            past_value = financial_data[-years-1].get(field) or 0 if len(financial_data) > years else 0
            if past_value <= 0 or current_value <= 0: return 0.0
            return (pow(current_value / past_value, 1/years) - 1) * 100
        except Exception:
            return 0.0
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        if value <= min_val: return 0.0
        elif value >= max_val: return 100.0
        else: return ((value - min_val) / (max_val - min_val)) * 100.0
