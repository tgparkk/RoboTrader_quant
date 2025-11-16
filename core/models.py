"""
데이터 모델 정의
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum


class OrderType(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"  # 🆕 타임아웃으로 인한 강제 정리


class PositionType(Enum):
    NONE = "none"
    LONG = "long"


class StockState(Enum):
    """종목 거래 상태"""
    SELECTED = "selected"           # 조건검색으로 선정됨 (매수 판단 대상)
    BUY_PENDING = "buy_pending"     # 매수 주문 중
    POSITIONED = "positioned"       # 매수 완료 (포지션 보유)
    SELL_CANDIDATE = "sell_candidate" # 매도 후보
    SELL_PENDING = "sell_pending"   # 매도 주문 중
    COMPLETED = "completed"         # 거래 완료 (재거래 가능)
    FAILED = "failed"              # 거래 실패


@dataclass
class OHLCVData:
    """OHLCV 데이터"""
    timestamp: datetime
    stock_code: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    
    def __post_init__(self):
        """데이터 검증"""
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("고가가 시가/종가보다 낮습니다")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("저가가 시가/종가보다 높습니다")


@dataclass
class Stock:
    """종목 정보"""
    code: str
    name: str
    ohlcv_data: List[OHLCVData] = field(default_factory=list)
    last_price: float = 0.0
    is_candidate: bool = False
    position: PositionType = PositionType.NONE
    position_quantity: int = 0
    position_avg_price: float = 0.0
    
    def add_ohlcv(self, ohlcv: OHLCVData):
        """OHLCV 데이터 추가"""
        self.ohlcv_data.append(ohlcv)
        self.last_price = ohlcv.close_price
        
        # 최대 1000개 데이터만 유지 (메모리 관리)
        if len(self.ohlcv_data) > 1000:
            self.ohlcv_data = self.ohlcv_data[-1000:]
    
    def get_recent_ohlcv(self, count: int = 20) -> List[OHLCVData]:
        """최근 N개 데이터 반환"""
        return self.ohlcv_data[-count:] if count <= len(self.ohlcv_data) else self.ohlcv_data


@dataclass
class Order:
    """주문 정보"""
    order_id: str
    stock_code: str
    order_type: OrderType
    price: float
    quantity: int
    timestamp: datetime
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    remaining_quantity: int = 0
    adjustment_count: int = 0  # 정정 횟수
    order_3min_candle_time: Optional[datetime] = None  # 주문 시점의 3분봉 시간 (3봉 후 취소용)
    
    def __post_init__(self):
        """초기화 후 처리"""
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity


@dataclass
class TradingSignal:
    """매매 신호"""
    stock_code: str
    signal_type: OrderType
    price: float
    quantity: int
    confidence: float  # 신호 신뢰도 (0.0 ~ 1.0)
    reason: str       # 신호 발생 이유
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """포지션 정보"""
    stock_code: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    
    def update_current_price(self, price: float):
        """현재가 업데이트 및 평가손익 계산"""
        self.current_price = price
        self.unrealized_pnl = (price - self.avg_price) * self.quantity


@dataclass
class TradingStock:
    """거래 종목 통합 정보"""
    stock_code: str
    stock_name: str
    state: StockState
    selected_time: datetime
    
    # 포지션 정보
    position: Optional[Position] = None
    
    # 주문 정보
    current_order_id: Optional[str] = None
    order_history: List[str] = field(default_factory=list)
    
    # 상태 변화 이력
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # 메타 정보
    selection_reason: str = ""
    prev_close: float = 0.0  # 전날 종가 (일봉 기준)
    last_update: datetime = field(default_factory=datetime.now)
    target_profit_rate: float = 0.03  # 목표수익률 (기본값 3%)
    
    # 🆕 레이스 컨디션 방지 플래그
    order_processed: bool = False  # 주문 체결 처리 완료 플래그
    is_buying: bool = False        # 매수 진행 중 플래그
    is_selling: bool = False       # 매도 진행 중 플래그
    
    # 가상매매 관련 정보
    _virtual_buy_record_id: Optional[int] = None  # 가상 매수 기록 ID
    _virtual_buy_price: Optional[float] = None    # 가상 매수가
    _virtual_quantity: Optional[int] = None       # 가상 매수 수량
    
    # 신호 중복 방지
    last_signal_candle_time: Optional[datetime] = None  # 마지막 매수 신호 발생 캔들 시점

    # 🆕 매수 시간 추적
    last_buy_time: Optional[datetime] = None  # 마지막 매수 체결 시간
    buy_cooldown_minutes: int = 25  # 매수 쿨다운 시간 (분)

    # 📊 패턴 데이터 로깅용 ID (매매 결과 연결)
    last_pattern_id: Optional[str] = None

    def change_state(self, new_state: StockState, reason: str = ""):
        """상태 변경 및 이력 기록"""
        old_state = self.state
        self.state = new_state
        self.last_update = datetime.now()
        
        # 상태 변화 이력 기록
        self.state_history.append({
            'from_state': old_state.value,
            'to_state': new_state.value,
            'reason': reason,
            'timestamp': self.last_update
        })
    
    def add_order(self, order_id: str):
        """주문 추가"""
        self.current_order_id = order_id
        self.order_history.append(order_id)
    
    def clear_current_order(self):
        """현재 주문 클리어"""
        self.current_order_id = None
    
    def set_position(self, quantity: int, avg_price: float):
        """포지션 설정"""
        self.position = Position(
            stock_code=self.stock_code,
            quantity=quantity,
            avg_price=avg_price
        )
    
    def clear_position(self):
        """포지션 클리어"""
        self.position = None
        # 매도 완료 시 신호 시점도 초기화 (새로운 매수 신호 허용)
        self.last_signal_candle_time = None
    
    def set_virtual_buy_info(self, record_id: int, price: float, quantity: int):
        """가상 매수 정보 설정"""
        self._virtual_buy_record_id = record_id
        self._virtual_buy_price = price
        self._virtual_quantity = quantity
    
    def clear_virtual_buy_info(self):
        """가상 매수 정보 클리어"""
        self._virtual_buy_record_id = None
        self._virtual_buy_price = None
        self._virtual_quantity = None
    
    def has_virtual_position(self) -> bool:
        """가상 포지션 보유 여부"""
        return all([
            self._virtual_buy_record_id is not None,
            self._virtual_buy_price is not None,
            self._virtual_quantity is not None
        ])

    def set_buy_time(self, buy_time: datetime):
        """매수 시간 설정"""
        self.last_buy_time = buy_time

    def is_buy_cooldown_active(self) -> bool:
        """매수 쿨다운 활성화 여부 확인"""
        if self.last_buy_time is None:
            return False

        from utils.korean_time import now_kst
        current_time = now_kst()
        time_diff = (current_time - self.last_buy_time).total_seconds() / 60  # 분 단위
        return time_diff < self.buy_cooldown_minutes

    def get_remaining_cooldown_minutes(self) -> int:
        """남은 쿨다운 시간 (분)"""
        if self.last_buy_time is None:
            return 0

        from utils.korean_time import now_kst
        current_time = now_kst()
        time_diff = (current_time - self.last_buy_time).total_seconds() / 60  # 분 단위
        remaining = self.buy_cooldown_minutes - time_diff
        return max(0, int(remaining))


@dataclass
class DataCollectionConfig:
    """데이터 수집 설정"""
    interval_seconds: int = 30
    candidate_stocks: List[str] = field(default_factory=list)


@dataclass
class OrderManagementConfig:
    """주문 관리 설정"""
    buy_timeout_seconds: int = 180
    sell_timeout_seconds: int = 180
    max_adjustments: int = 3
    adjustment_threshold_percent: float = 0.5
    market_order_threshold_percent: float = 2.0
    buy_budget_ratio: float = 0.20
    buy_cooldown_minutes: int = 20


@dataclass
class RiskManagementConfig:
    """리스크 관리 설정"""
    max_position_count: int = 20
    max_position_ratio: float = 0.3
    stop_loss_ratio: float = 0.025
    take_profit_ratio: float = 0.035
    max_daily_loss: float = 0.1


@dataclass
class StrategyConfig:
    """전략 설정"""
    name: str = "simple_momentum"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoggingConfig:
    """로깅 설정"""
    level: str = "INFO"
    file_retention_days: int = 30


@dataclass
class TradingConfig:
    """거래 설정 통합"""
    data_collection: DataCollectionConfig = field(default_factory=DataCollectionConfig)
    order_management: OrderManagementConfig = field(default_factory=OrderManagementConfig)
    risk_management: RiskManagementConfig = field(default_factory=RiskManagementConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    paper_trading: bool = True  # 🆕 가상 매매 모드 (기본 활성화)
    
    @classmethod
    def from_json(cls, json_data: Dict[str, Any]) -> 'TradingConfig':
        """JSON 데이터로부터 TradingConfig 객체 생성"""
        return cls(
            data_collection=DataCollectionConfig(
                interval_seconds=json_data.get('data_collection', {}).get('interval_seconds', 30),
                candidate_stocks=json_data.get('data_collection', {}).get('candidate_stocks', [])
            ),
            order_management=OrderManagementConfig(
                buy_timeout_seconds=json_data.get('order_management', {}).get('buy_timeout_seconds', 180),
                sell_timeout_seconds=json_data.get('order_management', {}).get('sell_timeout_seconds', 180),
                max_adjustments=json_data.get('order_management', {}).get('max_adjustments', 3),
                adjustment_threshold_percent=json_data.get('order_management', {}).get('adjustment_threshold_percent', 0.5),
                market_order_threshold_percent=json_data.get('order_management', {}).get('market_order_threshold_percent', 2.0),
                buy_budget_ratio=json_data.get('order_management', {}).get('buy_budget_ratio', 0.20),
                buy_cooldown_minutes=json_data.get('order_management', {}).get('buy_cooldown_minutes', 20)
            ),
            risk_management=RiskManagementConfig(
                max_position_count=json_data.get('risk_management', {}).get('max_position_count', 20),
                max_position_ratio=json_data.get('risk_management', {}).get('max_position_ratio', 0.3),
                stop_loss_ratio=json_data.get('risk_management', {}).get('stop_loss_ratio', 0.03),
                take_profit_ratio=json_data.get('risk_management', {}).get('take_profit_ratio', 0.05),
                max_daily_loss=json_data.get('risk_management', {}).get('max_daily_loss', 0.1)
            ),
            strategy=StrategyConfig(
                name=json_data.get('strategy', {}).get('name', 'simple_momentum'),
                parameters=json_data.get('strategy', {}).get('parameters', {})
            ),
            logging=LoggingConfig(
                level=json_data.get('logging', {}).get('level', 'INFO'),
                file_retention_days=json_data.get('logging', {}).get('file_retention_days', 30)
            ),
            paper_trading=json_data.get('paper_trading', True)
        )