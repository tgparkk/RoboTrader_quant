"""
백테스트 데이터 모델 정의
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TradeAction(Enum):
    """거래 유형"""
    BUY = "BUY"
    SELL = "SELL"


class SellReason(Enum):
    """매도 사유"""
    TAKE_PROFIT = "익절"
    STOP_LOSS = "손절"
    REBALANCING = "리밸런싱"
    HARD_STOP = "긴급매도"
    SOFT_STOP = "조건부매도"
    MAX_HOLD = "최대보유초과"
    END_OF_BACKTEST = "백테스트종료"


class MarketRegime(Enum):
    """시장 국면"""
    BULL = "상승"
    BEAR = "하락"
    FLAT = "횡보"


@dataclass
class BacktestParams:
    """백테스트 파라미터"""
    # 기본 설정
    initial_capital: float = 50_000_000  # 초기 자본 (5천만원)
    portfolio_size: int = 10  # 포트폴리오 종목 수 (라이브 설정과 일치)

    # 손익절 파라미터 (워크포워드 검증: TP16/SL8이 종합 2위, 안정성 0.89)
    target_profit_rate: float = 0.16  # 익절률 (16%)
    stop_loss_rate: float = 0.08  # 손절률 (8%)

    # 리밸런싱 기준 (라이브 설정과 일치)
    hard_stop_score: float = 65.0  # 긴급 매도 점수
    soft_stop_score: float = 67.0  # 조건부 매도 점수
    soft_stop_rank: int = 30  # 조건부 매도 순위
    safe_score: float = 75.0  # 안전 유지 점수
    safe_rank: int = 25  # 안전 유지 순위

    # 최소 보유일수 (리밸런싱 매도 보호, 손절은 항상 허용)
    min_hold_days: int = 0

    # 최대 보유일수 (0 = 무제한, N > 0이면 N일 초과 시 종가 강제 매도)
    max_hold_days: int = 0

    # 매수 최소 점수 (0이면 필터 미적용 = 상대순위만 사용)
    buy_min_score: float = 0.0

    # 동적 목표율 사용 여부
    use_dynamic_targets: bool = True

    # 거래 비용 (한국 실제: 매수 0.015%, 매도 0.245%)
    trading_cost_rate: float = 0.0025  # 0.25% (하위호환용, 실제로는 buy/sell_cost_rate 사용)
    buy_cost_rate: float = 0.00015    # 매수 위탁수수료 0.015%
    sell_cost_rate: float = 0.00245   # 매도 위탁수수료 0.015% + 거래세 0.18% + 농특세 0.05%

    # 슬리피지 (시장가 주문 체결 미끄러짐)
    # 실측값 (2026-04-13, 2/27~3/26 실전 81건): 매수 +0.222%, 매도 -0.229%, 왕복 0.451%
    slippage_rate: float = 0.0025     # 0.25% (실측 반영)

    # 장전 레짐 필터 (NXT 프록시 + 미장)
    regime_filter_enabled: bool = False      # 레짐 필터 사용 여부
    gap_caution_pct: float = -0.02           # KOSPI 시가 갭 -2% 이하 → CAUTION
    gap_crisis_pct: float = -0.05            # KOSPI 시가 갭 -5% 이하 → CRISIS
    sp500_caution_pct: float = -0.03         # S&P500 전일 -3% 이하 → CAUTION
    sp500_crisis_pct: float = -0.05          # S&P500 전일 -5% 이하 → CRISIS
    vix_caution: float = 30.0               # VIX > 30 → CAUTION
    vix_crisis: float = 40.0                # VIX > 40 → CRISIS
    caution_max_buy: int = 5                 # CAUTION 시 최대 매수 종목 수

    # CRISIS 전량 매도 (레짐 필터와 독립적으로 사용 가능)
    crisis_sell_all: bool = False            # CRISIS 시 보유 전량 시가 매도
    crisis_sell_gap_pct: float = -0.03       # 예상 KOSPI 갭 -3% 이하 → 전량 매도
    crisis_sell_sp500_pct: float = -0.05     # S&P500 전일 -5% 이하 → 전량 매도
    crisis_sell_vix: float = 40.0            # VIX ≥ 40 → 전량 매도

    # 리밸런싱 매도 후 재매수 차단 일수 (0 = 차단 없음, 실전 기본값 3일)
    rebalancing_sell_cooldown_days: int = 0

    # 5일 수익률 하드게이트 (None이면 비활성)
    buy_ret5d_min: float = None

    # 스마트 Hard Cap: 포트폴리오 평균 점수에 따라 보유 상한 동적 조절 (default OFF)
    use_smart_hard_cap: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'initial_capital': self.initial_capital,
            'portfolio_size': self.portfolio_size,
            'target_profit_rate': self.target_profit_rate,
            'stop_loss_rate': self.stop_loss_rate,
            'hard_stop_score': self.hard_stop_score,
            'soft_stop_score': self.soft_stop_score,
            'soft_stop_rank': self.soft_stop_rank,
            'safe_score': self.safe_score,
            'safe_rank': self.safe_rank,
            'min_hold_days': self.min_hold_days,
            'max_hold_days': self.max_hold_days,
            'buy_min_score': self.buy_min_score,
            'use_dynamic_targets': self.use_dynamic_targets,
            'trading_cost_rate': self.trading_cost_rate,
            'buy_cost_rate': self.buy_cost_rate,
            'sell_cost_rate': self.sell_cost_rate,
            'slippage_rate': self.slippage_rate,
            'regime_filter_enabled': self.regime_filter_enabled,
            'gap_caution_pct': self.gap_caution_pct,
            'gap_crisis_pct': self.gap_crisis_pct,
            'sp500_caution_pct': self.sp500_caution_pct,
            'sp500_crisis_pct': self.sp500_crisis_pct,
            'vix_caution': self.vix_caution,
            'vix_crisis': self.vix_crisis,
            'caution_max_buy': self.caution_max_buy,
            'buy_ret5d_min': self.buy_ret5d_min,
            'use_smart_hard_cap': self.use_smart_hard_cap,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BacktestParams':
        """딕셔너리에서 생성"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Position:
    """포지션 정보"""
    stock_code: str
    stock_name: str
    quantity: int
    buy_price: float
    buy_date: str
    target_profit_rate: float = 0.15
    stop_loss_rate: float = 0.08
    total_score: float = 0.0
    factor_rank: int = 999

    @property
    def total_cost(self) -> float:
        """총 매수 금액"""
        return self.quantity * self.buy_price

    def calculate_profit_rate(self, current_price: float) -> float:
        """수익률 계산"""
        if self.buy_price <= 0:
            return 0.0
        return (current_price - self.buy_price) / self.buy_price

    def calculate_profit_loss(self, current_price: float) -> float:
        """손익 금액 계산"""
        return (current_price - self.buy_price) * self.quantity

    def should_take_profit(self, current_price: float) -> bool:
        """익절 조건 체크"""
        profit_rate = self.calculate_profit_rate(current_price)
        return profit_rate >= self.target_profit_rate

    def should_stop_loss(self, current_price: float) -> bool:
        """손절 조건 체크"""
        profit_rate = self.calculate_profit_rate(current_price)
        return profit_rate <= -self.stop_loss_rate


@dataclass
class TradeRecord:
    """거래 기록"""
    date: str
    stock_code: str
    stock_name: str
    action: TradeAction
    quantity: int
    price: float
    amount: float  # 거래 금액
    reason: str
    profit_loss: float = 0.0  # 손익 (매도시)
    profit_rate: float = 0.0  # 수익률 (매도시)
    trading_cost: float = 0.0  # 거래 비용
    regime: Optional[str] = None  # 시장 국면 (후처리 태깅용)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'date': self.date,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'action': self.action.value,
            'quantity': self.quantity,
            'price': self.price,
            'amount': self.amount,
            'reason': self.reason,
            'profit_loss': self.profit_loss,
            'profit_rate': self.profit_rate,
            'trading_cost': self.trading_cost,
            'regime': self.regime,
        }


@dataclass
class DailySnapshot:
    """일별 스냅샷"""
    date: str
    capital: float  # 현금
    positions_value: float  # 보유 종목 평가액
    total_value: float  # 총 자산 (현금 + 평가액)
    position_count: int  # 보유 종목 수
    daily_return: float = 0.0  # 일별 수익률
    cumulative_return: float = 0.0  # 누적 수익률
    regime: Optional[str] = None  # 시장 국면 (후처리 태깅용)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'date': self.date,
            'capital': self.capital,
            'positions_value': self.positions_value,
            'total_value': self.total_value,
            'position_count': self.position_count,
            'daily_return': self.daily_return,
            'cumulative_return': self.cumulative_return,
            'regime': self.regime,
        }


@dataclass
class BacktestResult:
    """백테스트 결과"""
    # 기본 정보
    params: BacktestParams
    start_date: str
    end_date: str
    trading_days: int

    # 수익률 지표
    total_return: float = 0.0  # 총 수익률
    annualized_return: float = 0.0  # 연환산 수익률

    # 위험 지표
    max_drawdown: float = 0.0  # 최대 낙폭 (MDD)
    volatility: float = 0.0  # 변동성 (표준편차)
    sharpe_ratio: float = 0.0  # 샤프 비율

    # 거래 통계
    total_trades: int = 0  # 총 거래 수
    winning_trades: int = 0  # 수익 거래 수
    losing_trades: int = 0  # 손실 거래 수
    win_rate: float = 0.0  # 승률

    # 손익 통계
    total_profit: float = 0.0  # 총 수익
    total_loss: float = 0.0  # 총 손실
    profit_factor: float = 0.0  # 수익/손실 비율
    avg_profit: float = 0.0  # 평균 수익
    avg_loss: float = 0.0  # 평균 손실

    # 거래 비용
    total_trading_cost: float = 0.0  # 총 거래 비용

    # 상세 데이터
    trades: List[TradeRecord] = field(default_factory=list)
    daily_snapshots: List[DailySnapshot] = field(default_factory=list)

    # 최종 상태
    final_capital: float = 0.0
    final_positions_value: float = 0.0
    final_total_value: float = 0.0

    def to_summary_dict(self) -> Dict[str, Any]:
        """요약 딕셔너리로 변환"""
        return {
            'period': f"{self.start_date} ~ {self.end_date}",
            'trading_days': self.trading_days,
            'total_return': f"{self.total_return:.2%}",
            'annualized_return': f"{self.annualized_return:.2%}",
            'max_drawdown': f"{self.max_drawdown:.2%}",
            'volatility': f"{self.volatility:.2%}",
            'sharpe_ratio': f"{self.sharpe_ratio:.2f}",
            'total_trades': self.total_trades,
            'win_rate': f"{self.win_rate:.1%}",
            'profit_factor': f"{self.profit_factor:.2f}",
            'total_trading_cost': f"{self.total_trading_cost:,.0f}원",
            'final_total_value': f"{self.final_total_value:,.0f}원",
        }

    def print_summary(self):
        """결과 요약 출력"""
        print("\n" + "=" * 60)
        print("백테스트 결과 요약")
        print("=" * 60)
        print(f"기간: {self.start_date} ~ {self.end_date} ({self.trading_days}일)")
        print("-" * 60)
        print(f"초기 자본: {self.params.initial_capital:,.0f}원")
        print(f"최종 자산: {self.final_total_value:,.0f}원")
        print("-" * 60)
        print(f"총 수익률: {self.total_return:.2%}")
        print(f"연환산 수익률: {self.annualized_return:.2%}")
        print(f"최대 낙폭(MDD): {self.max_drawdown:.2%}")
        print(f"변동성: {self.volatility:.2%}")
        print(f"샤프 비율: {self.sharpe_ratio:.2f}")
        print("-" * 60)
        print(f"총 거래 수: {self.total_trades}건")
        print(f"승률: {self.win_rate:.1%} ({self.winning_trades}/{self.winning_trades + self.losing_trades})")
        print(f"수익 팩터: {self.profit_factor:.2f}")
        print(f"평균 수익: {self.avg_profit:,.0f}원")
        print(f"평균 손실: {self.avg_loss:,.0f}원")
        print("-" * 60)
        print(f"총 거래 비용: {self.total_trading_cost:,.0f}원")
        print("=" * 60)
