"""
Growth 팩터 계산 모듈 (20% 비중)
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


class GrowthFactor:
    """Growth 팩터 계산 클래스"""
    
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
    
    def calculate_growth_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """
        Growth 팩터 점수 계산 (0-100점)
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            Dict: {
                'growth_score': float,  # 최종 점수 (0-100)
                'revenue_growth_score': float,  # 매출 성장 (30%)
                'earnings_growth_score': float,  # 이익 성장 (30%)
                'growth_efficiency_score': float,  # 성장 효율성 (25%)
                'sustainability_score': float,  # 성장 지속성 (15%)
                'details': Dict  # 상세 지표
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 재무 데이터 조회
            financial_data = self._get_financial_history(stock_code, date, years=5)
            
            if financial_data is None or len(financial_data) < 2:
                return {
                    'growth_score': 0.0,
                    'revenue_growth_score': 0.0,
                    'earnings_growth_score': 0.0,
                    'growth_efficiency_score': 0.0,
                    'sustainability_score': 0.0,
                    'details': {}
                }
            
            # 1. 매출 성장 (30%)
            revenue_growth_score = self._calculate_revenue_growth(financial_data)
            
            # 2. 이익 성장 (30%)
            earnings_growth_score = self._calculate_earnings_growth(financial_data)
            
            # 3. 성장 효율성 (25%)
            growth_efficiency_score = self._calculate_growth_efficiency(financial_data)
            
            # 4. 성장 지속성 (15%)
            sustainability_score = self._calculate_sustainability(financial_data)
            
            # 최종 점수 계산
            growth_score = (
                revenue_growth_score * 0.30 +
                earnings_growth_score * 0.30 +
                growth_efficiency_score * 0.25 +
                sustainability_score * 0.15
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
                'growth_score': 0.0,
                'revenue_growth_score': 0.0,
                'earnings_growth_score': 0.0,
                'growth_efficiency_score': 0.0,
                'sustainability_score': 0.0,
                'details': {}
            }
    
    def _calculate_revenue_growth(self, financial_data: List[Dict]) -> float:
        """매출 성장 점수 계산 (30%)"""
        try:
            if len(financial_data) < 2:
                return 0.0
            
            # 1. 1년 매출 성장률 (50%)
            revenue_growth_1yr = self._calculate_growth_rate(financial_data, 'revenue', 1)
            revenue_growth_1yr_score = self._normalize(revenue_growth_1yr, -10, 30)
            
            # 2. 3년 매출 CAGR (30%)
            revenue_cagr_3yr = self._calculate_cagr(financial_data, 'revenue', 3)
            revenue_cagr_3yr_score = self._normalize(revenue_cagr_3yr, -5, 25)
            
            # 3. 5년 매출 CAGR (20%)
            revenue_cagr_5yr = self._calculate_cagr(financial_data, 'revenue', 5)
            revenue_cagr_5yr_score = self._normalize(revenue_cagr_5yr, 0, 20)
            
            revenue_growth_score = (
                revenue_growth_1yr_score * 0.50 +
                revenue_cagr_3yr_score * 0.30 +
                revenue_cagr_5yr_score * 0.20
            )
            
            return min(100.0, max(0.0, revenue_growth_score))
            
        except Exception as e:
            self.logger.error(f"매출 성장 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_earnings_growth(self, financial_data: List[Dict]) -> float:
        """이익 성장 점수 계산 (30%)"""
        try:
            if len(financial_data) < 2:
                return 0.0
            
            # 1. 1년 순이익 성장률 (40%)
            earnings_growth_1yr = self._calculate_growth_rate(financial_data, 'net_income', 1)
            earnings_growth_1yr_score = self._normalize(earnings_growth_1yr, -20, 50)
            
            # 2. 3년 순이익 CAGR (30%)
            earnings_cagr_3yr = self._calculate_cagr(financial_data, 'net_income', 3)
            earnings_cagr_3yr_score = self._normalize(earnings_cagr_3yr, -10, 40)
            
            # 3. 영업이익 성장률 (30%)
            op_income_growth = self._calculate_growth_rate(financial_data, 'operating_profit', 1)
            op_income_growth_score = self._normalize(op_income_growth, -15, 40)
            
            earnings_growth_score = (
                earnings_growth_1yr_score * 0.40 +
                earnings_cagr_3yr_score * 0.30 +
                op_income_growth_score * 0.30
            )
            
            return min(100.0, max(0.0, earnings_growth_score))
            
        except Exception as e:
            self.logger.error(f"이익 성장 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_growth_efficiency(self, financial_data: List[Dict]) -> float:
        """성장 효율성 점수 계산 (25%)"""
        try:
            if len(financial_data) < 2:
                return 0.0
            
            # 1. 이익 레버리지 (40%)
            revenue_growth = self._calculate_growth_rate(financial_data, 'revenue', 1)
            earnings_growth = self._calculate_growth_rate(financial_data, 'net_income', 1)
            
            if revenue_growth != 0:
                earnings_leverage = earnings_growth / revenue_growth
                earnings_leverage_score = self._normalize(earnings_leverage, 0, 3.0)
            else:
                earnings_leverage_score = 0
            
            # 2. 마진 개선도 (35%)
            current_margin = financial_data[-1].get('operating_margin', 0)
            prev_margin = financial_data[-2].get('operating_margin', 0) if len(financial_data) >= 2 else 0
            margin_expansion = current_margin - prev_margin
            margin_expansion_score = self._normalize(margin_expansion, -5, 5)
            
            # 3. ROE 개선도 (25%)
            current_roe = financial_data[-1].get('roe', 0)
            prev_roe = financial_data[-2].get('roe', 0) if len(financial_data) >= 2 else 0
            roe_improvement = current_roe - prev_roe
            roe_improvement_score = self._normalize(roe_improvement, -5, 10)
            
            growth_efficiency_score = (
                earnings_leverage_score * 0.40 +
                margin_expansion_score * 0.35 +
                roe_improvement_score * 0.25
            )
            
            return min(100.0, max(0.0, growth_efficiency_score))
            
        except Exception as e:
            self.logger.error(f"성장 효율성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_sustainability(self, financial_data: List[Dict]) -> float:
        """성장 지속성 점수 계산 (15%)"""
        try:
            if len(financial_data) < 4:
                return 0.0
            
            # 최근 4분기 중 전분기 대비 성장한 분기 수
            growth_quarters = 0
            for i in range(1, min(5, len(financial_data))):
                current_revenue = financial_data[-i].get('revenue', 0)
                prev_revenue = financial_data[-i-1].get('revenue', 0) if len(financial_data) > i else 0
                
                if prev_revenue > 0 and current_revenue > prev_revenue:
                    growth_quarters += 1
            
            # 4분기 연속 성장 = 100점
            growth_consistency_score = (growth_quarters / 4) * 100
            
            return min(100.0, max(0.0, growth_consistency_score))
            
        except Exception as e:
            self.logger.error(f"성장 지속성 계산 오류: {e}")
            return 0.0
    
    def _get_financial_history(self, stock_code: str, date: str, years: int = 5) -> Optional[List[Dict]]:
        """재무 이력 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT report_date, revenue, operating_profit, net_income,
                           operating_margin, roe
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT ?
                ''', (stock_code, date, years * 4))
                
                rows = cursor.fetchall()
                return [
                    {
                        'report_date': r[0],
                        'revenue': r[1],
                        'operating_profit': r[2],
                        'net_income': r[3],
                        'operating_margin': r[4],
                        'roe': r[5],
                    }
                    for r in rows
                ]
                
        except Exception as e:
            self.logger.error(f"재무 이력 조회 오류: {e}")
            return None
    
    def _calculate_growth_rate(self, financial_data: List[Dict], field: str, years: int = 1) -> float:
        """성장률 계산"""
        try:
            if len(financial_data) < years + 1:
                return 0.0
            
            current_value = financial_data[-1].get(field, 0)
            past_value = financial_data[-years-1].get(field, 0) if len(financial_data) > years else 0
            
            if past_value == 0:
                return 0.0
            
            return ((current_value - past_value) / abs(past_value)) * 100
            
        except Exception as e:
            return 0.0
    
    def _calculate_cagr(self, financial_data: List[Dict], field: str, years: int) -> float:
        """CAGR 계산"""
        try:
            if len(financial_data) < years + 1:
                return 0.0
            
            current_value = financial_data[-1].get(field, 0)
            past_value = financial_data[-years-1].get(field, 0) if len(financial_data) > years else 0
            
            if past_value <= 0:
                return 0.0
            
            cagr = (pow(current_value / past_value, 1/years) - 1) * 100
            return cagr
            
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

