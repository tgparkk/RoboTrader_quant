"""
Quality 팩터 계산 모듈 (20% 비중)
15개 지표로 구성
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import sqlite3

from utils.logger import setup_logger
from utils.korean_time import now_kst


logger = setup_logger(__name__)


class QualityFactor:
    """Quality 팩터 계산 클래스"""
    
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
    
    def calculate_quality_factor(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """
        Quality 팩터 점수 계산 (0-100점)
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            Dict: {
                'quality_score': float,  # 최종 점수 (0-100)
                'profitability_score': float,  # 수익성 (35%)
                'stability_score': float,  # 재무 안정성 (30%)
                'cashflow_quality_score': float,  # 현금창출력 (20%)
                'earnings_quality_score': float,  # 수익 안정성 (15%)
                'details': Dict  # 상세 지표
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 재무 데이터 조회
            financial_data = self._get_financial_data(stock_code, date)
            price_data = self._get_price_data(stock_code, date)
            
            if financial_data is None:
                return {
                    'quality_score': 0.0,
                    'profitability_score': 0.0,
                    'stability_score': 0.0,
                    'cashflow_quality_score': 0.0,
                    'earnings_quality_score': 0.0,
                    'details': {}
                }
            
            # 1. 수익성 지표 (35%)
            profitability_score = self._calculate_profitability_score(financial_data)
            
            # 2. 재무 안정성 (30%)
            stability_score = self._calculate_stability_score(financial_data)
            
            # 3. 현금창출력 (20%)
            cashflow_quality_score = self._calculate_cashflow_quality(financial_data, price_data)
            
            # 4. 수익 안정성 (15%)
            earnings_quality_score = self._calculate_earnings_quality(stock_code, date)
            
            # 최종 점수 계산
            quality_score = (
                profitability_score * 0.35 +
                stability_score * 0.30 +
                cashflow_quality_score * 0.20 +
                earnings_quality_score * 0.15
            )
            
            return {
                'quality_score': min(100.0, max(0.0, quality_score)),
                'profitability_score': profitability_score,
                'stability_score': stability_score,
                'cashflow_quality_score': cashflow_quality_score,
                'earnings_quality_score': earnings_quality_score,
                'details': {
                    'roe': financial_data.get('roe'),
                    'roa': financial_data.get('roa'),
                    'roic': financial_data.get('roic'),
                    'debt_ratio': financial_data.get('debt_ratio'),
                }
            }
            
        except Exception as e:
            self.logger.error(f"Quality 팩터 계산 오류 ({stock_code}): {e}")
            return {
                'quality_score': 0.0,
                'profitability_score': 0.0,
                'stability_score': 0.0,
                'cashflow_quality_score': 0.0,
                'earnings_quality_score': 0.0,
                'details': {}
            }
    
    def _calculate_profitability_score(self, financial_data: Dict) -> float:
        """수익성 점수 계산 (35%)"""
        try:
            # 1. ROE (30%)
            roe = financial_data.get('roe', 0)
            roe_score = self._normalize(roe, 0, 30)
            
            # 2. ROA (20%)
            roa = financial_data.get('roa', 0)
            roa_score = self._normalize(roa, 0, 15)
            
            # 3. ROIC (20%)
            roic = financial_data.get('roic', 0)
            roic_score = self._normalize(roic, 0, 20)
            
            # 4. 영업이익률 (15%)
            operating_margin = financial_data.get('operating_margin', 0)
            operating_margin_score = self._normalize(operating_margin, 0, 25)
            
            # 5. 순이익률 (15%)
            net_margin = financial_data.get('net_margin', 0)
            net_margin_score = self._normalize(net_margin, 0, 20)
            
            profitability_score = (
                roe_score * 0.30 +
                roa_score * 0.20 +
                roic_score * 0.20 +
                operating_margin_score * 0.15 +
                net_margin_score * 0.15
            )
            
            return min(100.0, max(0.0, profitability_score))
            
        except Exception as e:
            self.logger.error(f"수익성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_stability_score(self, financial_data: Dict) -> float:
        """재무 안정성 점수 계산 (30%)"""
        try:
            # 1. 부채비율 (25%)
            debt_ratio = financial_data.get('debt_ratio', 0)
            debt_ratio_score = self._normalize_inverse(debt_ratio, 0, 200)
            
            # 2. 이자보상배율 (25%)
            interest_coverage = financial_data.get('interest_coverage', 0)
            interest_coverage_score = self._normalize(interest_coverage, 1, 10)
            
            # 3. 유동비율 (20%)
            current_ratio = financial_data.get('current_ratio', 0)
            current_ratio_score = self._normalize(current_ratio, 50, 200)
            
            # 4. 당좌비율 (15%)
            quick_ratio = financial_data.get('quick_ratio', 0)
            quick_ratio_score = self._normalize(quick_ratio, 50, 150)
            
            # 5. 순차입금비율 (15%)
            net_debt_ratio = financial_data.get('net_debt_ratio', 0)
            net_debt_ratio_score = self._normalize_inverse(net_debt_ratio, -50, 150)
            
            stability_score = (
                debt_ratio_score * 0.25 +
                interest_coverage_score * 0.25 +
                current_ratio_score * 0.20 +
                quick_ratio_score * 0.15 +
                net_debt_ratio_score * 0.15
            )
            
            return min(100.0, max(0.0, stability_score))
            
        except Exception as e:
            self.logger.error(f"재무 안정성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_cashflow_quality(self, financial_data: Dict, price_data: Optional[Dict]) -> float:
        """현금창출력 점수 계산 (20%)"""
        try:
            # 1. FCF 수익률 (35%)
            fcf_yield = financial_data.get('fcf_yield', 0)
            fcf_yield_score = self._normalize(fcf_yield, 0, 10)
            
            # 2. 영업현금흐름/순이익 비율 (30%)
            ocf_to_ni = financial_data.get('ocf_to_ni', 0)
            ocf_ni_score = self._normalize(ocf_to_ni, 50, 150)
            
            # 3. CAPEX 비율 (20%)
            capex_ratio = financial_data.get('capex_ratio', 0)
            capex_ratio_score = self._normalize_inverse(capex_ratio, 0, 70)
            
            # 4. 현금보유 수준 (15%)
            cash_ratio = financial_data.get('cash_ratio', 0)
            cash_ratio_score = self._normalize(cash_ratio, 0, 30)
            
            cashflow_quality_score = (
                fcf_yield_score * 0.35 +
                ocf_ni_score * 0.30 +
                capex_ratio_score * 0.20 +
                cash_ratio_score * 0.15
            )
            
            return min(100.0, max(0.0, cashflow_quality_score))
            
        except Exception as e:
            self.logger.error(f"현금창출력 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_earnings_quality(self, stock_code: str, date: str) -> float:
        """수익 안정성 점수 계산 (15%)"""
        try:
            # 5년간 순이익 데이터 조회
            earnings_data = self._get_earnings_history(stock_code, date, years=5)
            
            if earnings_data is None or len(earnings_data) < 3:
                return 0.0
            
            # 이익 변동성 계산
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
            earnings_quality_score = stability * 100
            
            return min(100.0, max(0.0, earnings_quality_score))
            
        except Exception as e:
            self.logger.error(f"수익 안정성 계산 오류: {e}")
            return 0.0
    
    def _get_financial_data(self, stock_code: str, date: str) -> Optional[Dict]:
        """재무 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT roe, roa, roic, operating_margin, net_margin,
                           debt_ratio, interest_coverage, current_ratio, quick_ratio,
                           net_debt_ratio, fcf_yield, ocf_to_ni, capex_ratio, cash_ratio
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'roe': row[0],
                        'roa': row[1],
                        'roic': row[2],
                        'operating_margin': row[3],
                        'net_margin': row[4],
                        'debt_ratio': row[5],
                        'interest_coverage': row[6],
                        'current_ratio': row[7],
                        'quick_ratio': row[8],
                        'net_debt_ratio': row[9],
                        'fcf_yield': row[10],
                        'ocf_to_ni': row[11],
                        'capex_ratio': row[12],
                        'cash_ratio': row[13],
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
                ''', (stock_code, date, years * 4))
                
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



