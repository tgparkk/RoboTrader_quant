"""
통합 전략 (퀀트 리밸런싱 전용)
- quant 100% (순수 리밸런싱 모드)
"""

from typing import Optional, Dict, Any, Tuple
from utils.logger import setup_logger
from strategies.quant_strategy import QuantStrategy


class CombinedStrategy:
    """통합 전략 - 퀀트 리밸런싱 전용"""
    
    def __init__(self, db_manager, quant_strategy: Optional[QuantStrategy] = None):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
            quant_strategy: QuantStrategy 인스턴스 (없으면 생성)
        """
        self.db_manager = db_manager
        self.quant_strategy = quant_strategy or QuantStrategy(db_manager)
        self.logger = setup_logger(__name__)
        
        # 전략 가중치 - 퀀트 100%
        self.weights = {
            'quant': 1.00,      # 퀀트 전략 100%
        }
    
    def should_buy(self, stock_code: str, calc_date: Optional[str] = None) -> Tuple[bool, float, str]:
        """
        퀀트 매수 신호 판단 (순수 리밸런싱 모드)
        
        Args:
            stock_code: 종목코드
            calc_date: 계산 날짜
        
        Returns:
            (BUY 여부, 신뢰도 점수, 이유)
        """
        try:
            # 퀀트 전략 점수만 사용 (100%)
            quant_buy, quant_reason = self.quant_strategy.should_buy(stock_code, calc_date)
            quant_score = self.weights['quant'] if quant_buy else 0.0
            
            reason = f"퀀트 점수 {quant_score:.0%}" + (f" ({quant_reason})" if quant_reason else "")
            
            if quant_buy:
                self.logger.debug(f"✅ {stock_code} 퀀트 매수 신호: {quant_reason}")
            else:
                self.logger.debug(f"❌ {stock_code} 퀀트 매수 신호 없음: {quant_reason}")
            
            return quant_buy, quant_score, reason
            
        except Exception as e:
            self.logger.error(f"❌ 퀀트 전략 판단 오류 {stock_code}: {e}")
            return False, 0.0, f"전략 오류: {str(e)}"
    
    def get_strategy_breakdown(self, stock_code: str, calc_date: Optional[str] = None) -> Dict[str, Any]:
        """
        퀀트 전략 상세 정보
        
        Returns:
            {
                'quant': {'signal': bool, 'score': float, 'reason': str},
                'total_score': float,
                'should_buy': bool
            }
        """
        quant_buy, quant_reason = self.quant_strategy.should_buy(stock_code, calc_date)
        
        return {
            'quant': {
                'signal': quant_buy,
                'score': self.weights['quant'] if quant_buy else 0.0,
                'reason': quant_reason
            },
            'total_score': self.weights['quant'] if quant_buy else 0.0,
            'should_buy': quant_buy
        }

