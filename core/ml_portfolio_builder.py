"""
ML 멀티팩터 시스템 포트폴리오 구성 모듈
- 상위 10종목 선정
- 비중 할당
- 리밸런싱 계획 생성
"""
import psycopg2
import pandas as pd
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime
from pathlib import Path

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.ml_factor_calculator import MLFactorCalculator
from config.pg_helper import pg_connection


logger = setup_logger(__name__)


class MLPortfolioBuilder:
    """ML 멀티팩터 포트폴리오 구성 클래스"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
        self.calculator = MLFactorCalculator(db_path)
        self.logger.info("ML 포트폴리오 빌더 초기화 완료 (PostgreSQL)")
    
    def build_portfolio(self, date: str = None, top_n: int = 10, 
                       universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """상위 N종목 선정 및 포트폴리오 구성"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            self.logger.info(f"📊 포트폴리오 구성 시작 ({date}, 상위 {top_n}개)")
            
            if universe is None:
                universe = self._get_universe(date)
            
            if not universe:
                self.logger.warning("⚠️ 대상 종목이 없습니다")
                return []
            
            self.logger.info(f"📋 대상 종목: {len(universe)}개")
            
            all_scores = []
            for i, stock_code in enumerate(universe, 1):
                try:
                    self.logger.debug(f"[{i}/{len(universe)}] {stock_code} 스코어링 중...")
                    score_result = self.calculator.calculate_total_score(stock_code, date)
                    
                    if score_result['total_score'] > 0:
                        all_scores.append({
                            'stock_code': stock_code,
                            'stock_name': self._get_stock_name(stock_code),
                            'total_score': score_result['total_score'],
                            'value_score': score_result['value'],
                            'momentum_score': score_result['momentum'],
                            'quality_score': score_result['quality'],
                            'growth_score': score_result['growth'],
                        })
                except Exception as e:
                    self.logger.warning(f"⚠️ {stock_code} 스코어링 실패: {e}")
                    continue
            
            if not all_scores:
                self.logger.warning("⚠️ 스코어링된 종목이 없습니다")
                return []
            
            all_scores.sort(key=lambda x: x['total_score'], reverse=True)
            top_stocks = all_scores[:top_n]
            portfolio = self._allocate_weights(top_stocks)
            
            for i, stock in enumerate(portfolio, 1):
                stock['rank'] = i
            
            self.logger.info(f"✅ 포트폴리오 구성 완료: {len(portfolio)}개 종목")
            for i, stock in enumerate(portfolio[:5], 1):
                self.logger.info(
                    f"  {i}. {stock['stock_code']}({stock['stock_name']}) "
                    f"점수={stock['total_score']:.2f}, 비중={stock['weight']:.2%}"
                )
            
            return portfolio
            
        except Exception as e:
            self.logger.error(f"❌ 포트폴리오 구성 오류: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _allocate_weights(self, stocks: List[Dict]) -> List[Dict]:
        """비중 할당 (점수 기반 차등 비중)"""
        try:
            if not stocks:
                return []
            
            total_score = sum(s['total_score'] for s in stocks)
            
            if total_score == 0:
                weight = 1.0 / len(stocks)
                for stock in stocks:
                    stock['weight'] = weight
            else:
                for stock in stocks:
                    stock['weight'] = stock['total_score'] / total_score
            
            weight_sum = sum(s['weight'] for s in stocks)
            if weight_sum > 0:
                for stock in stocks:
                    stock['weight'] = stock['weight'] / weight_sum
            
            return stocks
            
        except Exception as e:
            self.logger.error(f"비중 할당 오류: {e}")
            weight = 1.0 / len(stocks) if stocks else 0
            for stock in stocks:
                stock['weight'] = weight
            return stocks
    
    def save_portfolio(self, portfolio: List[Dict], date: str = None) -> bool:
        """포트폴리오를 DB에 저장"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            if not portfolio:
                self.logger.warning("⚠️ 저장할 포트폴리오가 없습니다")
                return False
            
            with pg_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('DELETE FROM quant_portfolio WHERE calc_date = %s', (date,))
                
                for stock in portfolio:
                    cursor.execute('''
                        INSERT INTO quant_portfolio
                        (calc_date, stock_code, stock_name, rank, total_score, reason)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (
                        date,
                        stock['stock_code'],
                        stock['stock_name'],
                        stock['rank'],
                        stock['total_score'],
                        f"Value:{stock['value_score']:.1f} "
                        f"Momentum:{stock['momentum_score']:.1f} "
                        f"Quality:{stock['quality_score']:.1f} "
                        f"Growth:{stock['growth_score']:.1f}"
                    ))
            
            self.logger.info(f"✅ 포트폴리오 저장 완료: {date}, {len(portfolio)}개 종목")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 포트폴리오 저장 오류: {e}")
            return False
    
    def get_current_portfolio(self, date: str = None) -> List[Dict]:
        """현재 포트폴리오 조회"""
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            with pg_connection() as conn:
                query = '''
                    SELECT stock_code, stock_name, rank, total_score, reason
                    FROM quant_portfolio
                    WHERE calc_date = %s
                    ORDER BY rank ASC
                '''
                df = pd.read_sql_query(query, conn, params=(date,))
                
                if df.empty:
                    return []
                
                return df.to_dict('records')
                
        except Exception as e:
            self.logger.error(f"포트폴리오 조회 오류: {e}")
            return []
    
    def calculate_rebalancing_plan(self, current_holdings: List[str], 
                                   target_portfolio: List[Dict]) -> Dict[str, Any]:
        """리밸런싱 계획 계산"""
        try:
            target_codes = {s['stock_code'] for s in target_portfolio}
            current_codes = set(current_holdings)
            
            to_sell = list(current_codes - target_codes)
            to_buy = [s for s in target_portfolio if s['stock_code'] not in current_codes]
            to_hold = list(current_codes & target_codes)
            
            return {'to_sell': to_sell, 'to_buy': to_buy, 'to_hold': to_hold}
            
        except Exception as e:
            self.logger.error(f"리밸런싱 계획 계산 오류: {e}")
            return {'to_sell': [], 'to_buy': [], 'to_hold': []}
    
    def _get_universe(self, date: str) -> List[str]:
        """대상 종목 리스트 조회"""
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT stock_code
                    FROM daily_prices
                    WHERE date = %s
                    ORDER BY stock_code
                ''', (date,))
                
                rows = cursor.fetchall()
                return [row[0] for row in rows]
                
        except Exception as e:
            self.logger.error(f"대상 종목 조회 오류: {e}")
            return []
    
    def _get_stock_name(self, stock_code: str) -> str:
        """종목명 조회"""
        try:
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT stock_name
                    FROM candidate_stocks
                    WHERE stock_code = %s
                    ORDER BY selection_date DESC
                    LIMIT 1
                ''', (stock_code,))
                
                row = cursor.fetchone()
                if row:
                    return row[0] or stock_code
                return stock_code
                
        except Exception as e:
            return stock_code
