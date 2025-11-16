"""
통합 전략 (10단계 기준)
- quant 40%, pullback 20%, momentum 15%, breakout 10%, 기타 15%
"""

from typing import Optional, Dict, Any, Tuple
from utils.logger import setup_logger
from strategies.quant_strategy import QuantStrategy


class CombinedStrategy:
    """통합 전략 - 여러 전략을 조합"""
    
    def __init__(self, db_manager, quant_strategy: Optional[QuantStrategy] = None):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
            quant_strategy: QuantStrategy 인스턴스 (없으면 생성)
        """
        self.db_manager = db_manager
        self.quant_strategy = quant_strategy or QuantStrategy(db_manager)
        self.logger = setup_logger(__name__)
        
        # 전략 가중치 (계획서 기준)
        self.weights = {
            'quant': 0.40,      # 퀀트 전략 40%
            'pullback': 0.20,  # 눌림목 전략 20%
            'momentum': 0.15,  # 모멘텀 전략 15%
            'breakout': 0.10,  # 돌파 전략 10%
            'other': 0.15      # 기타 전략 15%
        }
    
    def should_buy(self, stock_code: str, 
                   pullback_signal: bool = False,
                   momentum_signal: bool = False,
                   breakout_signal: bool = False,
                   other_signal: bool = False,
                   calc_date: Optional[str] = None) -> Tuple[bool, float, str]:
        """
        통합 매수 신호 판단
        
        Args:
            stock_code: 종목코드
            pullback_signal: 눌림목 신호 여부
            momentum_signal: 모멘텀 신호 여부
            breakout_signal: 돌파 신호 여부
            other_signal: 기타 신호 여부
            calc_date: 계산 날짜
        
        Returns:
            (BUY 여부, 신뢰도 점수, 이유)
        """
        try:
            # 1. 퀀트 전략 점수
            quant_buy, quant_reason = self.quant_strategy.should_buy(stock_code, calc_date)
            quant_score = self.weights['quant'] if quant_buy else 0.0
            
            # 2. 각 전략 점수 계산
            pullback_score = self.weights['pullback'] if pullback_signal else 0.0
            momentum_score = self.weights['momentum'] if momentum_signal else 0.0
            breakout_score = self.weights['breakout'] if breakout_signal else 0.0
            other_score = self.weights['other'] if other_signal else 0.0
            
            # 3. 총점 계산
            total_score = quant_score + pullback_score + momentum_score + breakout_score + other_score
            
            # 4. 신호 여부 판단 (임계값: 50% 이상)
            threshold = 0.50
            should_buy = total_score >= threshold
            
            # 5. 이유 구성
            reasons = []
            if quant_buy:
                reasons.append(f"퀀트({quant_score:.0%})")
            if pullback_signal:
                reasons.append(f"눌림목({pullback_score:.0%})")
            if momentum_signal:
                reasons.append(f"모멘텀({momentum_score:.0%})")
            if breakout_signal:
                reasons.append(f"돌파({breakout_score:.0%})")
            if other_signal:
                reasons.append(f"기타({other_score:.0%})")
            
            reason = f"통합 점수 {total_score:.0%}" + (f" ({', '.join(reasons)})" if reasons else "")
            
            if should_buy:
                self.logger.debug(
                    f"✅ {stock_code} 통합 매수 신호: {total_score:.0%} "
                    f"(퀀트:{quant_score:.0%}, 눌림목:{pullback_score:.0%}, "
                    f"모멘텀:{momentum_score:.0%}, 돌파:{breakout_score:.0%}, 기타:{other_score:.0%})"
                )
            else:
                self.logger.debug(
                    f"❌ {stock_code} 통합 매수 신호 없음: {total_score:.0%} < {threshold:.0%}"
                )
            
            return should_buy, total_score, reason
            
        except Exception as e:
            self.logger.error(f"❌ 통합 전략 판단 오류 {stock_code}: {e}")
            return False, 0.0, f"전략 오류: {str(e)}"
    
    def get_strategy_breakdown(self, stock_code: str,
                               pullback_signal: bool = False,
                               momentum_signal: bool = False,
                               breakout_signal: bool = False,
                               other_signal: bool = False,
                               calc_date: Optional[str] = None) -> Dict[str, Any]:
        """
        전략별 점수 상세 정보
        
        Returns:
            {
                'quant': {'signal': bool, 'score': float, 'reason': str},
                'pullback': {'signal': bool, 'score': float},
                'momentum': {'signal': bool, 'score': float},
                'breakout': {'signal': bool, 'score': float},
                'other': {'signal': bool, 'score': float},
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
            'pullback': {
                'signal': pullback_signal,
                'score': self.weights['pullback'] if pullback_signal else 0.0
            },
            'momentum': {
                'signal': momentum_signal,
                'score': self.weights['momentum'] if momentum_signal else 0.0
            },
            'breakout': {
                'signal': breakout_signal,
                'score': self.weights['breakout'] if breakout_signal else 0.0
            },
            'other': {
                'signal': other_signal,
                'score': self.weights['other'] if other_signal else 0.0
            },
            'total_score': (
                (self.weights['quant'] if quant_buy else 0.0) +
                (self.weights['pullback'] if pullback_signal else 0.0) +
                (self.weights['momentum'] if momentum_signal else 0.0) +
                (self.weights['breakout'] if breakout_signal else 0.0) +
                (self.weights['other'] if other_signal else 0.0)
            ),
            'should_buy': False  # should_buy() 호출로 계산
        }

