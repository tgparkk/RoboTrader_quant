"""
거래 전략 관리 클래스
기존 TradingStrategyConfig를 개선하고 확장
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from utils.logger import setup_logger


@dataclass
class TradingStrategy:
    """거래 전략 설정"""
    name: str
    timeframe: str  # "1min", "3min", or "5min"
    indicators: List[str]
    description: str
    enabled: bool = True
    priority: int = 1  # 우선순위 (낮을수록 높은 우선순위)


@dataclass  
class ChartData:
    """차트 데이터와 전략 정보"""
    stock_code: str
    stock_name: str
    timeframe: str
    strategy: TradingStrategy
    price_data: Any  # pd.DataFrame
    indicators_data: Dict[str, Any] = field(default_factory=dict)


class StrategyManager:
    """거래 전략 관리 클래스"""
    
    # 사전 정의된 전략들
    PREDEFINED_STRATEGIES = {
        "strategy1": TradingStrategy(
            name="가격박스+이등분선",
            timeframe="1min",
            indicators=["price_box", "bisector_line"],
            description="가격박스 지지/저항선과 이등분선을 활용한 매매",
            priority=1
        ),
        "strategy2": TradingStrategy(
            name="다중볼린저밴드+이등분선", 
            timeframe="5min",
            indicators=["multi_bollinger_bands", "bisector_line"],
            description="다중 볼린저밴드와 이등분선을 활용한 매매 (5분봉)",
            priority=2
        ),
        "strategy3": TradingStrategy(
            name="다중볼린저밴드",
            timeframe="5min", 
            indicators=["multi_bollinger_bands"],
            description="여러 기간의 볼린저밴드를 활용한 매매 (5분봉)",
            priority=3
        )
        ,
        "strategy4": TradingStrategy(
            name="눌림목 캔들패턴(3분봉)",
            timeframe="3min",
            indicators=["pullback_candle_pattern", "bisector_line"],
            description="저거래 하락 조정 후 회복 양봉 및 이등분선 회복 기반 (3분봉)",
            priority=2
        )
    }
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.strategies = self.PREDEFINED_STRATEGIES.copy()
        self.logger.info("전략 관리자 초기화 완료")
    
    def get_strategy(self, strategy_name: str) -> Optional[TradingStrategy]:
        """전략 정보 조회"""
        # 별칭 매핑
        strategy_aliases = {
            'price_box': 'strategy1',
            'multi_bollinger': 'strategy2',
            'pullback': 'strategy4',
            'pullback_candle': 'strategy4',
            'pullback_candle_pattern': 'strategy4',
            'pullback_3min': 'strategy4'
        }
        
        # 별칭 변환
        actual_name = strategy_aliases.get(strategy_name, strategy_name)
        return self.strategies.get(actual_name)
    
    def get_all_strategies(self) -> Dict[str, TradingStrategy]:
        """모든 전략 정보 조회"""
        return self.strategies
    
    def get_enabled_strategies(self) -> Dict[str, TradingStrategy]:
        """활성화된 전략들만 조회"""
        return {name: strategy for name, strategy in self.strategies.items() 
                if strategy.enabled}
    
    def get_strategies_by_priority(self) -> List[tuple]:
        """우선순위 순으로 정렬된 전략 리스트 반환"""
        enabled_strategies = self.get_enabled_strategies()
        return sorted(enabled_strategies.items(), key=lambda x: x[1].priority)
    
    def enable_strategy(self, strategy_name: str) -> bool:
        """전략 활성화"""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].enabled = True
            self.logger.info(f"전략 활성화: {strategy_name}")
            return True
        return False
    
    def disable_strategy(self, strategy_name: str) -> bool:
        """전략 비활성화"""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].enabled = False
            self.logger.info(f"전략 비활성화: {strategy_name}")
            return True
        return False
    
    def add_custom_strategy(self, strategy_name: str, strategy: TradingStrategy) -> bool:
        """사용자 정의 전략 추가"""
        try:
            self.strategies[strategy_name] = strategy
            self.logger.info(f"사용자 정의 전략 추가: {strategy_name}")
            return True
        except Exception as e:
            self.logger.error(f"전략 추가 실패: {e}")
            return False
    
    def remove_strategy(self, strategy_name: str) -> bool:
        """전략 제거 (사전 정의된 전략은 제거 불가)"""
        if strategy_name in self.PREDEFINED_STRATEGIES:
            self.logger.warning(f"사전 정의된 전략은 제거할 수 없습니다: {strategy_name}")
            return False
        
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            self.logger.info(f"전략 제거: {strategy_name}")
            return True
        return False
    
    def update_strategy_priority(self, strategy_name: str, new_priority: int) -> bool:
        """전략 우선순위 변경"""
        if strategy_name in self.strategies:
            old_priority = self.strategies[strategy_name].priority
            self.strategies[strategy_name].priority = new_priority
            self.logger.info(f"전략 우선순위 변경: {strategy_name} ({old_priority} → {new_priority})")
            return True
        return False
    
    def get_strategy_summary(self) -> Dict[str, Any]:
        """전략 현황 요약"""
        total_strategies = len(self.strategies)
        enabled_strategies = len(self.get_enabled_strategies())
        
        strategy_list = []
        for name, strategy in self.strategies.items():
            strategy_list.append({
                'name': name,
                'display_name': strategy.name,
                'timeframe': strategy.timeframe,
                'indicators': strategy.indicators,
                'enabled': strategy.enabled,
                'priority': strategy.priority
            })
        
        return {
            'total_strategies': total_strategies,
            'enabled_strategies': enabled_strategies,
            'disabled_strategies': total_strategies - enabled_strategies,
            'strategies': strategy_list
        }
    
    def validate_strategy(self, strategy: TradingStrategy) -> bool:
        """전략 유효성 검증"""
        try:
            # 필수 필드 검증
            if not strategy.name or not strategy.timeframe:
                return False
            
            # 시간프레임 검증
            if strategy.timeframe not in ["1min", "3min", "5min"]:
                return False
            
            # 지표 검증
            valid_indicators = ["price_box", "bisector_line", "bollinger_bands", "multi_bollinger_bands", "pullback_candle_pattern"]
            if not strategy.indicators or not all(ind in valid_indicators for ind in strategy.indicators):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"전략 검증 오류: {e}")
            return False
    
    def reset_to_defaults(self):
        """기본 전략으로 리셋"""
        self.strategies = self.PREDEFINED_STRATEGIES.copy()
        self.logger.info("전략을 기본값으로 리셋")


# 하위 호환성을 위한 별칭
TradingStrategyConfig = StrategyManager