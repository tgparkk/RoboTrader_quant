"""
Value 팩터 계산 모듈 (30% 비중)
10개 지표로 구성
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import sqlite3

from utils.logger import setup_logger
from utils.korean_time import now_kst


logger = setup_logger(__name__)


class ValueFactor:
    """Value 팩터 계산 클래스"""
    
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
    
    def calculate_value_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """
        Value 팩터 점수 계산 (0-100점)
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            Dict: {
                'value_score': float,  # 최종 점수 (0-100)
                'valuation_score': float,  # 밸류에이션 점수 (40%)
                'dividend_score': float,  # 배당 점수 (20%)
                'asset_value_score': float,  # 자산가치 점수 (20%)
                'stability_score': float,  # 안정성 점수 (20%)
                'details': Dict  # 상세 지표
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 재무 데이터 조회
            financial_data = self._get_financial_data(stock_code, date)
            price_data = self._get_price_data(stock_code, date)
            
            if financial_data is None or price_data is None:
                return {
                    'value_score': 0.0,
                    'valuation_score': 0.0,
                    'dividend_score': 0.0,
                    'asset_value_score': 0.0,
                    'stability_score': 0.0,
                    'details': {}
                }
            
            # 1. 밸류에이션 지표 (40%)
            valuation_score = self._calculate_valuation_score(financial_data, price_data)
            
            # 2. 배당 지표 (20%)
            dividend_score = self._calculate_dividend_score(financial_data, price_data)
            
            # 3. 자산가치 지표 (20%)
            asset_value_score = self._calculate_asset_value_score(financial_data, price_data)
            
            # 4. 이익 안정성 (20%)
            stability_score = self._calculate_stability_score(stock_code, date)
            
            # 최종 점수 계산
            value_score = (
                valuation_score * 0.40 +
                dividend_score * 0.20 +
                asset_value_score * 0.20 +
                stability_score * 0.20
            )
            
            return {
                'value_score': min(100.0, max(0.0, value_score)),
                'valuation_score': valuation_score,
                'dividend_score': dividend_score,
                'asset_value_score': asset_value_score,
                'stability_score': stability_score,
                'details': {
                    'per': financial_data.get('per'),
                    'pbr': financial_data.get('pbr'),
                    'pcr': financial_data.get('pcr'),
                    'psr': financial_data.get('psr'),
                    'dividend_yield': financial_data.get('dividend_yield'),
                }
            }
            
        except Exception as e:
            self.logger.error(f"Value 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'value_score': 0.0,
                'valuation_score': 0.0,
                'dividend_score': 0.0,
                'asset_value_score': 0.0,
                'stability_score': 0.0,
                'details': {}
            }
    
    def _calculate_valuation_score(self, financial_data: Dict, price_data: Dict) -> float:
        """밸류에이션 점수 계산 (40%)"""
        try:
            # 1. PER 점수 (30%)
            per = financial_data.get('per')
            per_score = self._normalize_inverse(per, 3, 30) if per and per > 0 else 0
            
            # 2. PBR 점수 (30%)
            pbr = financial_data.get('pbr')
            pbr_score = self._normalize_inverse(pbr, 0.5, 3.0) if pbr and pbr > 0 else 0
            
            # 3. PCR 점수 (20%)
            pcr = financial_data.get('pcr')
            pcr_score = self._normalize_inverse(pcr, 5, 20) if pcr and pcr > 0 else 0
            
            # 4. PSR 점수 (20%)
            psr = financial_data.get('psr')
            psr_score = self._normalize_inverse(psr, 0.5, 3.0) if psr and psr > 0 else 0
            
            valuation_score = (
                per_score * 0.30 +
                pbr_score * 0.30 +
                pcr_score * 0.20 +
                psr_score * 0.20
            )
            
            return min(100.0, max(0.0, valuation_score))
            
        except Exception as e:
            self.logger.error(f"밸류에이션 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_dividend_score(self, financial_data: Dict, price_data: Dict) -> float:
        """배당 점수 계산 (20%)"""
        try:
            # 1. 배당수익률 (50%)
            dividend_yield = financial_data.get('dividend_yield', 0)
            dividend_yield_score = self._normalize(dividend_yield, 0, 5.0)
            
            # 2. 배당성장률 3년 CAGR (30%)
            dividend_growth = financial_data.get('dividend_growth_3yr', 0)
            dividend_growth_score = self._normalize(dividend_growth, -5, 15)
            
            # 3. 배당여력 (20%)
            dividend_capacity = financial_data.get('dividend_capacity', 0)
            dividend_capacity_score = self._normalize(dividend_capacity, 0, 70)
            
            dividend_score = (
                dividend_yield_score * 0.50 +
                dividend_growth_score * 0.30 +
                dividend_capacity_score * 0.20
            )
            
            return min(100.0, max(0.0, dividend_score))
            
        except Exception as e:
            self.logger.error(f"배당 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_asset_value_score(self, financial_data: Dict, price_data: Dict) -> float:
        """자산가치 점수 계산 (20%)"""
        try:
            # 1. NAV 대비 할인율 (60%)
            discount_to_nav = financial_data.get('discount_to_nav', 0)
            nav_score = self._normalize(discount_to_nav, -50, 50)
            
            # 2. 청산가치 마진 (40%)
            liquidation_margin = financial_data.get('liquidation_margin', 0)
            liquidation_score = self._normalize(liquidation_margin, -30, 30)
            
            asset_value_score = (
                nav_score * 0.60 +
                liquidation_score * 0.40
            )
            
            return min(100.0, max(0.0, asset_value_score))
            
        except Exception as e:
            self.logger.error(f"자산가치 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_stability_score(self, stock_code: str, date: str) -> float:
        """이익 안정성 점수 계산 (20%)"""
        try:
            # 5년간 순이익 데이터 조회
            earnings_data = self._get_earnings_history(stock_code, date, years=5)
            
            if earnings_data is None or len(earnings_data) < 3:
                return 0.0
            
            # 변동성 계산
            earnings_values = [e['net_income'] for e in earnings_data if e['net_income']]
            if len(earnings_values) < 3:
                return 0.0
            
            mean_earnings = np.mean(earnings_values)
            if mean_earnings == 0:
                return 0.0
            
            volatility = np.std(earnings_values) / abs(mean_earnings)
            
            # 안정성 = 1 / (1 + 변동성)
            stability = 1 / (1 + volatility)
            
            # 0-100 스케일로 변환
            stability_score = stability * 100
            
            return min(100.0, max(0.0, stability_score))
            
        except Exception as e:
            self.logger.error(f"안정성 점수 계산 오류: {e}")
            return 0.0
    
    def _get_financial_data(self, stock_code: str, date: str) -> Optional[Dict]:
        """재무 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT per, pbr, pcr, psr, dividend_yield, dividend_growth_3yr,
                           dividend_capacity, discount_to_nav, liquidation_margin,
                           roe, roa, net_income, equity
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'per': row[0],
                        'pbr': row[1],
                        'pcr': row[2],
                        'psr': row[3],
                        'dividend_yield': row[4],
                        'dividend_growth_3yr': row[5],
                        'dividend_capacity': row[6],
                        'discount_to_nav': row[7],
                        'liquidation_margin': row[8],
                        'roe': row[9],
                        'roa': row[10],
                        'net_income': row[11],
                        'equity': row[12],
                    }
                return None
                
        except Exception as e:
            self.logger.error(f"재무 데이터 조회 오류: {e}")
            return None
    
    def _get_price_data(self, stock_code: str, date: str) -> Optional[Dict]:
        """가격 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT close, market_cap
                    FROM daily_prices
                    WHERE stock_code = ? AND date = ?
                ''', (stock_code, date))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'close': row[0],
                        'market_cap': row[1],
                    }
                return None
                
        except Exception as e:
            self.logger.error(f"가격 데이터 조회 오류: {e}")
            return None
    
    def _get_earnings_history(self, stock_code: str, date: str, years: int = 5) -> Optional[List[Dict]]:
        """과거 이익 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT report_date, net_income
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT ?
                ''', (stock_code, date, years * 4))  # 분기별 데이터
                
                rows = cursor.fetchall()
                return [{'report_date': r[0], 'net_income': r[1]} for r in rows]
                
        except Exception as e:
            self.logger.error(f"이익 이력 조회 오류: {e}")
            return None
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """값을 0-100 스케일로 정규화 (높을수록 좋음)"""
        if value <= min_val:
            return 0.0
        elif value >= max_val:
            return 100.0
        else:
            return ((value - min_val) / (max_val - min_val)) * 100.0
    
    def _normalize_inverse(self, value: float, min_val: float, max_val: float) -> float:
        """값을 0-100 스케일로 역정규화 (낮을수록 좋음)"""
        if value <= min_val:
            return 100.0
        elif value >= max_val:
            return 0.0
        else:
            return ((max_val - value) / (max_val - min_val)) * 100.0

