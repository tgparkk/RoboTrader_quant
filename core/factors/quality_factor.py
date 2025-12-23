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
            # 1. ROE (50%) - roa, roic 없으므로 가중치 재조정
            roe = financial_data.get('roe', 0) or 0
            roe_score = self._normalize(roe, 0, 30)

            # 2. 영업이익률 (25%)
            operating_margin = financial_data.get('operating_margin', 0) or 0
            operating_margin_score = self._normalize(operating_margin, 0, 25)

            # 3. 순이익률 (25%)
            net_margin = financial_data.get('net_margin', 0) or 0
            net_margin_score = self._normalize(net_margin, 0, 20)

            profitability_score = (
                roe_score * 0.50 +
                operating_margin_score * 0.25 +
                net_margin_score * 0.25
            )

            return min(100.0, max(0.0, profitability_score))

        except Exception as e:
            self.logger.error(f"수익성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_stability_score(self, financial_data: Dict) -> float:
        """재무 안정성 점수 계산 (30%)"""
        try:
            # 부채비율만 사용 가능 (다른 지표들은 테이블에 없음)
            debt_ratio = financial_data.get('debt_ratio', 0) or 0
            debt_ratio_score = self._normalize_inverse(debt_ratio, 0, 200)

            # 다른 지표들이 없으므로 부채비율만으로 점수 계산
            stability_score = debt_ratio_score

            return min(100.0, max(0.0, stability_score))

        except Exception as e:
            self.logger.error(f"재무 안정성 점수 계산 오류: {e}")
            return 0.0
    
    def _calculate_cashflow_quality(self, financial_data: Dict, price_data: Optional[Dict]) -> float:
        """현금창출력 점수 계산 (20%)"""
        try:
            # 현금흐름 관련 데이터가 테이블에 없으므로 기본값 반환
            # TODO: 현금흐름 데이터 수집 후 실제 계산 구현 필요
            return 50.0  # 중립 점수

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
                # 실제 존재하는 컬럼만 조회
                cursor.execute('''
                    SELECT roe, operating_margin, net_margin, debt_ratio
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))

                row = cursor.fetchone()
                if row:
                    return {
                        'roe': row[0] if row[0] is not None else 0,
                        'roa': None,  # 테이블에 없음
                        'roic': None,  # 테이블에 없음
                        'operating_margin': row[1] if row[1] is not None else 0,
                        'net_margin': row[2] if row[2] is not None else 0,
                        'debt_ratio': row[3] if row[3] is not None else 0,
                        'interest_coverage': None,  # 테이블에 없음
                        'current_ratio': None,  # 테이블에 없음
                        'quick_ratio': None,  # 테이블에 없음
                        'net_debt_ratio': None,  # 테이블에 없음
                        'fcf_yield': None,  # 테이블에 없음
                        'ocf_to_ni': None,  # 테이블에 없음
                        'capex_ratio': None,  # 테이블에 없음
                        'cash_ratio': None,  # 테이블에 없음
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



