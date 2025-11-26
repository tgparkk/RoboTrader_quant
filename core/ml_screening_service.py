"""
ML 멀티팩터 시스템 스크리닝 서비스
- 매일 자동 스코어링 및 포트폴리오 구성
- 기존 QuantScreeningService와 통합
"""
import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.ml_portfolio_builder import MLPortfolioBuilder
from core.ml_factor_calculator import MLFactorCalculator


logger = setup_logger(__name__)


class MLScreeningService:
    """ML 멀티팩터 스크리닝 서비스"""
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로
        """
        self.logger = setup_logger(__name__)
        self.portfolio_builder = MLPortfolioBuilder(db_path)
        self.calculator = MLFactorCalculator(db_path)
        
        self.logger.info("ML 스크리닝 서비스 초기화 완료")
    
    async def run_daily_screening(self, date: str = None, top_n: int = 10) -> Dict[str, Any]:
        """
        일일 스크리닝 실행
        
        Args:
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            top_n: 선정할 종목 수 (기본 10개)
            
        Returns:
            Dict: 스크리닝 결과
            {
                'success': bool,
                'date': str,
                'portfolio': List[Dict],
                'stats': Dict
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            self.logger.info("=" * 80)
            self.logger.info(f"🔍 ML 멀티팩터 스크리닝 시작: {date}")
            self.logger.info("=" * 80)
            
            # 1. 포트폴리오 구성
            portfolio = self.portfolio_builder.build_portfolio(date=date, top_n=top_n)
            
            if not portfolio:
                self.logger.warning("⚠️ 포트폴리오 구성 실패")
                return {
                    'success': False,
                    'date': date,
                    'portfolio': [],
                    'stats': {}
                }
            
            # 2. 각 종목의 팩터 점수 및 ML 피처 저장
            saved_count = 0
            for stock in portfolio:
                try:
                    # 팩터 점수 저장
                    self.calculator.save_factor_scores(stock['stock_code'], date)
                    
                    # ML 피처 저장
                    self.calculator.save_ml_features(stock['stock_code'], date)
                    
                    saved_count += 1
                except Exception as e:
                    self.logger.warning(f"⚠️ {stock['stock_code']} 데이터 저장 실패: {e}")
            
            # 3. 포트폴리오 저장
            self.portfolio_builder.save_portfolio(portfolio, date)
            
            # 4. 통계 계산
            stats = self._calculate_stats(portfolio)
            
            # 결과 출력
            self.logger.info("=" * 80)
            self.logger.info(f"✅ ML 스크리닝 완료: {date}")
            self.logger.info(f"📊 선정 종목: {len(portfolio)}개")
            self.logger.info(f"📈 평균 점수: {stats['avg_score']:.2f}")
            self.logger.info(f"📉 최저 점수: {stats['min_score']:.2f}")
            self.logger.info(f"📈 최고 점수: {stats['max_score']:.2f}")
            self.logger.info("=" * 80)
            
            return {
                'success': True,
                'date': date,
                'portfolio': portfolio,
                'stats': stats
            }
            
        except Exception as e:
            self.logger.error(f"❌ ML 스크리닝 오류: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'date': date if 'date' in locals() else now_kst().strftime("%Y-%m-%d"),
                'portfolio': [],
                'stats': {}
            }
    
    def _calculate_stats(self, portfolio: List[Dict]) -> Dict[str, Any]:
        """포트폴리오 통계 계산"""
        try:
            if not portfolio:
                return {}
            
            scores = [s['total_score'] for s in portfolio]
            value_scores = [s['value_score'] for s in portfolio]
            momentum_scores = [s['momentum_score'] for s in portfolio]
            quality_scores = [s['quality_score'] for s in portfolio]
            growth_scores = [s['growth_score'] for s in portfolio]
            
            return {
                'count': len(portfolio),
                'avg_score': sum(scores) / len(scores) if scores else 0,
                'min_score': min(scores) if scores else 0,
                'max_score': max(scores) if scores else 0,
                'avg_value': sum(value_scores) / len(value_scores) if value_scores else 0,
                'avg_momentum': sum(momentum_scores) / len(momentum_scores) if momentum_scores else 0,
                'avg_quality': sum(quality_scores) / len(quality_scores) if quality_scores else 0,
                'avg_growth': sum(growth_scores) / len(growth_scores) if growth_scores else 0,
            }
            
        except Exception as e:
            self.logger.error(f"통계 계산 오류: {e}")
            return {}



