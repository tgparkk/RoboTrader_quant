"""
백테스트 메트릭 계산 모듈

승률, 수익률, MDD, 샤프비율 등 계산
"""
import numpy as np
from typing import List, Dict, Any
from backtest.models import DailySnapshot, TradeRecord, TradeAction


class MetricsCalculator:
    """메트릭 계산기"""

    @staticmethod
    def calculate_all(snapshots: List[DailySnapshot], trades: List[TradeRecord]) -> Dict[str, Any]:
        """모든 메트릭 계산"""
        result = {
            # 기본값
            'max_drawdown': 0.0,
            'volatility': 0.0,
            'sharpe_ratio': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'total_profit': 0.0,
            'total_loss': 0.0,
            'profit_factor': 0.0,
            'avg_profit': 0.0,
            'avg_loss': 0.0,
            'total_trading_cost': 0.0,
        }

        # 스냅샷 기반 메트릭
        if snapshots:
            result['max_drawdown'] = MetricsCalculator.calculate_max_drawdown(snapshots)
            result['volatility'] = MetricsCalculator.calculate_volatility(snapshots)
            result['sharpe_ratio'] = MetricsCalculator.calculate_sharpe_ratio(snapshots)

        # 거래 기반 메트릭
        if trades:
            trade_metrics = MetricsCalculator.calculate_trade_metrics(trades)
            result.update(trade_metrics)

        return result

    @staticmethod
    def calculate_max_drawdown(snapshots: List[DailySnapshot]) -> float:
        """
        최대 낙폭(MDD) 계산

        MDD = (고점 - 저점) / 고점
        """
        if not snapshots:
            return 0.0

        values = [s.total_value for s in snapshots]
        if not values:
            return 0.0

        peak = values[0]
        max_drawdown = 0.0

        for value in values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

    @staticmethod
    def calculate_volatility(snapshots: List[DailySnapshot]) -> float:
        """
        변동성(표준편차) 계산

        연환산 변동성 = 일별 수익률 표준편차 * sqrt(252)
        """
        if len(snapshots) < 2:
            return 0.0

        daily_returns = [s.daily_return for s in snapshots]
        if not daily_returns:
            return 0.0

        std = np.std(daily_returns)
        annualized_volatility = std * np.sqrt(252)

        return annualized_volatility

    @staticmethod
    def calculate_sharpe_ratio(snapshots: List[DailySnapshot],
                               risk_free_rate: float = 0.035) -> float:
        """
        샤프 비율 계산

        Sharpe = (연환산 수익률 - 무위험 수익률) / 연환산 변동성

        Args:
            snapshots: 일별 스냅샷 리스트
            risk_free_rate: 무위험 수익률 (기본 3.5%)
        """
        if len(snapshots) < 2:
            return 0.0

        # 연환산 수익률 계산
        daily_returns = [s.daily_return for s in snapshots]
        if not daily_returns:
            return 0.0

        avg_daily_return = np.mean(daily_returns)
        annualized_return = (1 + avg_daily_return) ** 252 - 1

        # 연환산 변동성
        volatility = MetricsCalculator.calculate_volatility(snapshots)
        if volatility == 0:
            return 0.0

        # 샤프 비율
        sharpe = (annualized_return - risk_free_rate) / volatility

        return sharpe

    @staticmethod
    def calculate_trade_metrics(trades: List[TradeRecord]) -> Dict[str, Any]:
        """거래 기반 메트릭 계산"""
        # 매도 거래만 필터링
        sell_trades = [t for t in trades if t.action == TradeAction.SELL]

        total_trades = len(sell_trades)
        if total_trades == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'total_loss': 0.0,
                'profit_factor': 0.0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'total_trading_cost': sum(t.trading_cost for t in trades),
            }

        # 승/패 분류
        winning_trades = [t for t in sell_trades if t.profit_loss > 0]
        losing_trades = [t for t in sell_trades if t.profit_loss <= 0]

        # 합계
        total_profit = sum(t.profit_loss for t in winning_trades)
        total_loss = abs(sum(t.profit_loss for t in losing_trades))

        # 평균
        avg_profit = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        # 수익 팩터
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf') if total_profit > 0 else 0

        # 거래 비용
        total_trading_cost = sum(t.trading_cost for t in trades)

        return {
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / total_trades if total_trades > 0 else 0,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'profit_factor': profit_factor,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'total_trading_cost': total_trading_cost,
        }

    @staticmethod
    def calculate_sortino_ratio(snapshots: List[DailySnapshot],
                                risk_free_rate: float = 0.035) -> float:
        """
        소르티노 비율 계산 (하방 위험만 고려)

        Sortino = (연환산 수익률 - 무위험 수익률) / 하방 표준편차
        """
        if len(snapshots) < 2:
            return 0.0

        daily_returns = [s.daily_return for s in snapshots]
        if not daily_returns:
            return 0.0

        # 연환산 수익률
        avg_daily_return = np.mean(daily_returns)
        annualized_return = (1 + avg_daily_return) ** 252 - 1

        # 하방 수익률만 추출
        downside_returns = [r for r in daily_returns if r < 0]
        if not downside_returns:
            return float('inf') if annualized_return > risk_free_rate else 0

        # 하방 표준편차
        downside_std = np.std(downside_returns)
        annualized_downside_std = downside_std * np.sqrt(252)

        if annualized_downside_std == 0:
            return 0.0

        # 소르티노 비율
        sortino = (annualized_return - risk_free_rate) / annualized_downside_std

        return sortino

    @staticmethod
    def calculate_calmar_ratio(snapshots: List[DailySnapshot]) -> float:
        """
        칼마 비율 계산

        Calmar = 연환산 수익률 / MDD
        """
        if len(snapshots) < 2:
            return 0.0

        # 연환산 수익률
        daily_returns = [s.daily_return for s in snapshots]
        if not daily_returns:
            return 0.0

        avg_daily_return = np.mean(daily_returns)
        annualized_return = (1 + avg_daily_return) ** 252 - 1

        # MDD
        mdd = MetricsCalculator.calculate_max_drawdown(snapshots)
        if mdd == 0:
            return float('inf') if annualized_return > 0 else 0

        return annualized_return / mdd

    @staticmethod
    def calculate_win_loss_ratio(trades: List[TradeRecord]) -> float:
        """
        승패 비율 (평균 수익 / 평균 손실)
        """
        metrics = MetricsCalculator.calculate_trade_metrics(trades)
        avg_profit = metrics['avg_profit']
        avg_loss = metrics['avg_loss']

        if avg_loss == 0:
            return float('inf') if avg_profit > 0 else 0

        return avg_profit / avg_loss

    @staticmethod
    def calculate_expectancy(trades: List[TradeRecord]) -> float:
        """
        기대값 (1거래당 평균 손익)

        Expectancy = (승률 * 평균수익) - (패률 * 평균손실)
        """
        metrics = MetricsCalculator.calculate_trade_metrics(trades)

        win_rate = metrics['win_rate']
        avg_profit = metrics['avg_profit']
        avg_loss = metrics['avg_loss']

        expectancy = (win_rate * avg_profit) - ((1 - win_rate) * avg_loss)

        return expectancy

    @staticmethod
    def calculate_consecutive_stats(trades: List[TradeRecord]) -> Dict[str, int]:
        """
        연속 승/패 통계
        """
        sell_trades = [t for t in trades if t.action == TradeAction.SELL]
        if not sell_trades:
            return {
                'max_consecutive_wins': 0,
                'max_consecutive_losses': 0,
                'current_streak': 0,
            }

        # 연속 승리/패배 계산
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in sell_trades:
            if trade.profit_loss > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        # 현재 연속
        current_streak = current_wins if current_wins > 0 else -current_losses

        return {
            'max_consecutive_wins': max_wins,
            'max_consecutive_losses': max_losses,
            'current_streak': current_streak,
        }
